"""Real-Redis smoke test for `RedisLockManager` (R-220 M4).

Validates the 3-layer lock (local in-process + reentrancy + Redis
SET NX PX) end-to-end against a real Redis 8.x instance. Tests
cover:

- `optimistic_lock` / `pessimistic_lock` / `lock_with_renewal` (Function).
- `optimistic` / `pessimistic` / `_with_ttl` / `_with_renewal` (Ops).
- Atomic release via Lua compare-and-delete.
- Renewal watchdog (lock survives past the initial TTL).
- Batch lock (deadlock-safe via sorted order).

The Lua release script is the only way to verify "stale holder
cannot release": we acquire a lock, manually overwrite the
request_id on the Redis side, and confirm `release()` returns
False.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisDistributedLock,
    RedisLockManager,
    RedisProviderRegistrar,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-220-M4-Lock:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        # Best-effort: clear all `lock:*` keys from the namespace.
        try:
            keys = list(client.scan_iter(match=f"{namespace}:lock:*", count=200))
            if keys:
                client.delete(*keys)
        finally:
            reg.close()


@pytest.fixture
def lock_mgr(registrar: RedisProviderRegistrar) -> RedisLockManager:
    return registrar.lock_ops()


# ── Optimistic + Pessimistic ─────────────────────────────────────────


class TestOptimisticLock:
    def test_acquire_and_release(
        self, lock_mgr: RedisLockManager
    ) -> None:
        handle = lock_mgr.optimistic("k1")
        assert handle.try_acquire() is True
        assert handle.release() is True

    def test_second_optimistic_fails_when_held(
        self, lock_mgr: RedisLockManager
    ) -> None:
        h1 = lock_mgr.optimistic("k1")
        assert h1.try_acquire() is True
        h2 = lock_mgr.optimistic("k1")
        assert h2.try_acquire() is False
        h1.release()
        # After release, a new acquisition succeeds.
        h3 = lock_mgr.optimistic("k1")
        assert h3.try_acquire() is True
        h3.release()


class TestPessimisticLock:
    def test_pessimistic_blocks_until_released(
        self, lock_mgr: RedisLockManager
    ) -> None:
        h1 = lock_mgr.optimistic("k2")
        assert h1.try_acquire() is True
        # Release the lock in a background thread.
        def release_later() -> None:
            time.sleep(0.1)
            h1.release()
        threading.Thread(target=release_later, daemon=True).start()
        # Pessimistic acquisition should succeed within ~200 ms.
        h2 = lock_mgr.pessimistic("k2")
        assert h2.try_acquire() is True
        h2.release()


class TestLockWithRenewal:
    def test_renewal_extends_ttl(
        self, lock_mgr: RedisLockManager
    ) -> None:
        """Acquire with a short TTL + renewal; sleep past the
        original TTL; the lock should still be held."""
        handle = lock_mgr.lock_with_renewal(
            "renew1", seconds=3, optimistic=True
        )
        assert handle.try_acquire() is True
        # Sleep 4 seconds — past the 3-second initial TTL.
        time.sleep(4)
        # The lock should still be held.
        h2 = lock_mgr.optimistic("renew1")
        assert h2.try_acquire() is False
        handle.release()

    def test_renewal_rejects_short_ttl(
        self, lock_mgr: RedisLockManager
    ) -> None:
        with pytest.raises(ValueError):
            lock_mgr.lock_with_renewal(
                "short", seconds=2, optimistic=True
            )


# ── Atomic release (compare-and-delete) ────────────────────────────


class TestAtomicRelease:
    def test_stale_holder_cannot_release(
        self, lock_mgr: RedisLockManager, registrar: RedisProviderRegistrar
    ) -> None:
        """The release Lua checks the request_id; a holder that has
        been overwritten (e.g. after TTL expiry + re-acquire by
        another caller) must NOT be able to release the new holder's
        lock."""
        h1 = lock_mgr.optimistic("atomic")
        assert h1.try_acquire() is True
        # The key the manager wrote is `{ns}:atomic` (no `lock:` prefix
        # in this Python implementation — the lock manager passes the
        # caller's key straight to `make_key`).
        ns_key = (
            registrar.value_ops()._backend.make_key("atomic")
        )
        # Simulate "TTL expired + re-acquired by a different request":
        # overwrite the key with a new request_id.
        registrar.value_ops()._backend.raw_client().set(ns_key, "stolen_id")
        # h1's release should return False.
        assert h1.release() is False
        # The "stolen" lock should still be present.
        assert (
            registrar.value_ops()._backend.raw_client().get(ns_key)
            == "stolen_id"
        )
        # Cleanup.
        registrar.value_ops()._backend.raw_client().delete(ns_key)

    def test_double_release_returns_false(
        self, lock_mgr: RedisLockManager
    ) -> None:
        h = lock_mgr.optimistic("k_double")
        assert h.try_acquire() is True
        assert h.release() is True
        # Second release is a no-op (returns False).
        assert h.release() is False


# ── TTL / expiry behaviour ───────────────────────────────────────────


class TestLockTtl:
    def test_optimistic_with_ttl_expires(
        self, lock_mgr: RedisLockManager, registrar: RedisProviderRegistrar
    ) -> None:
        h = lock_mgr.optimistic_with_ttl("k_ttl", seconds=1)
        assert h.try_acquire() is True
        # Wait for the TTL to expire.
        time.sleep(1.5)
        # The key is gone, so a new acquisition succeeds.
        h2 = lock_mgr.optimistic("k_ttl")
        assert h2.try_acquire() is True
        h2.release()


# ── Batch lock ───────────────────────────────────────────────────────


class TestBatchLock:
    def test_batch_acquires_all(
        self, lock_mgr: RedisLockManager
    ) -> None:
        handles = lock_mgr.batch(["b1", "b2", "b3"], timeout=10, unit=None)
        assert all(h.try_acquire() for h in handles.locks)
        released = handles.release_all()
        assert released == 3

    def test_batch_release_all_returns_count(
        self, lock_mgr: RedisLockManager
    ) -> None:
        handles = lock_mgr.batch(["b4"], timeout=10, unit=None)
        assert len(handles.locks) == 1
        assert handles.release_all() == 1


# ── Context manager ──────────────────────────────────────────────────


class TestContextManager:
    def test_with_statement_releases(
        self, lock_mgr: RedisLockManager
    ) -> None:
        with lock_mgr.optimistic("k_ctx") as h:
            assert h.try_acquire() is True
        # After the `with` block, the lock should be released.
        h2 = lock_mgr.optimistic("k_ctx")
        assert h2.try_acquire() is True
        h2.release()


# ── ProviderRegistrar wiring ─────────────────────────────────────────


class TestProviderRegistrarWiring:
    def test_lock_ops_returns_lock_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisLockManager

        assert isinstance(registrar.lock_ops(), RedisLockManager)

    def test_lock_function_is_lock_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """`lock_function()` returns the SAME instance as `lock_ops()`."""
        assert registrar.lock_function() is registrar.lock_ops()
