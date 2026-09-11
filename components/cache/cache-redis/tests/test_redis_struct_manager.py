"""Real-Redis smoke test for `RedisStructManager` (R-220 M3.C).

Validates the Python-only `StructOps` Protocol implementation:
whole-object read/write, typed read, TTL, and atomic read-modify-
write via `WATCH` / `MULTI` / `EXEC`.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisProviderRegistrar,
    RedisStructManager,
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
    namespace = f"R-220-M3C-Struct:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        try:
            keys = list(client.scan_iter(match=f"{namespace}:*", count=200))
            if keys:
                client.delete(*keys)
        finally:
            reg.close()


@pytest.fixture
def manager(registrar: RedisProviderRegistrar) -> RedisStructManager:
    return registrar.struct_ops()


class TestStructOpsCore:
    def test_set_get_dict(
        self, manager: RedisStructManager
    ) -> None:
        payload = {"name": "richie", "age": 42, "tags": ["a", "b"]}
        manager.set("user:42", payload)
        result = manager.get("user:42", dict)
        assert result == payload

    def test_set_get_int(
        self, manager: RedisStructManager
    ) -> None:
        manager.set("counter", 42)
        assert manager.get("counter", int) == 42

    def test_set_get_str(
        self, manager: RedisStructManager
    ) -> None:
        manager.set("name", "richie")
        assert manager.get("name", str) == "richie"

    def test_set_get_typed_via_infra(
        self, manager: RedisStructManager
    ) -> None:
        # Pre-register the type via the infrastructure.
        manager._infra.register_type("typed_key", int)
        manager.set("typed_key", 42)
        result = manager.get_typed("typed_key", int)
        assert result == 42

    def test_set_with_ttl(
        self, manager: RedisStructManager
    ) -> None:
        manager.set_with_ttl("ephemeral", "v", timeout_millis=5_000)
        # Verify the TTL was set (in millis).
        ttl = manager._backend.raw_client().pttl(manager._k("ephemeral"))
        assert 0 < ttl <= 5_000

    def test_get_missing_returns_none(
        self, manager: RedisStructManager
    ) -> None:
        assert manager.get("missing", str) is None


class TestStructOpsRefresh:
    def test_refresh_initial_creation(
        self, manager: RedisStructManager
    ) -> None:
        """`refresh` on a missing key — `func(None)` returns the
        initial value, which is then written atomically."""
        result = manager.refresh("counter", lambda current: 1 if current is None else current + 1)
        assert result == 1
        assert manager.get("counter", int) == 1

    def test_refresh_increment(
        self, manager: RedisStructManager
    ) -> None:
        manager.set("counter", 10)
        for _ in range(3):
            # The round-trip encodes everything as str, so the
            # function receives a str and must cast back to int.
            manager.refresh(
                "counter",
                lambda current: int(current or "0") + 1,
            )
        assert manager.get("counter", int) == 13

    def test_refresh_atomic_under_concurrent_writers(
        self, manager: RedisStructManager
    ) -> None:
        """Multiple concurrent `refresh` calls must not lose updates.

        We simulate contention with a small thread pool; each
        `refresh` reads + increments. The atomic WATCH/MULTI/EXEC
        guarantees no lost updates.
        """
        import threading

        manager.set("counter", 0)
        threads = []
        results = []
        errors = []

        def worker() -> None:
            try:
                for _ in range(10):
                    manager.refresh(
                        "counter",
                        lambda current: int(current or "0") + 1,
                    )
                results.append(True)
            except Exception as exc:
                errors.append(exc)

        for _ in range(8):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"workers errored: {errors}"
        # 8 threads × 10 increments = 80 increments.
        assert manager.get("counter", int) == 80


class TestStructOpsLockNotYetImplemented:
    def test_get_with_lock_raises(
        self, manager: RedisStructManager
    ) -> None:
        with pytest.raises(NotImplementedError):
            manager.get_with_lock("k", str, 1000, lambda: None)

    def test_get_with_lock_typed_raises(
        self, manager: RedisStructManager
    ) -> None:
        with pytest.raises(NotImplementedError):
            manager.get_with_lock_typed("k", str, 1000, lambda: None)


class TestProviderRegistrarWiring:
    def test_struct_ops_returns_struct_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisStructManager

        assert isinstance(registrar.struct_ops(), RedisStructManager)
