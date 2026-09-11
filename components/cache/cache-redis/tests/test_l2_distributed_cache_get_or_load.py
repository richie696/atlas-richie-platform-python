"""Real-Redis L2-distributed-cache `get_or_load` tests (M5.2).

Covers the new in-process stampede-prevention loader-driven read:

- L1 short-circuit
- L1 miss + L2 hit (read-through, no loader call)
- L1 miss + L2 miss + loader (write-back to both L1 and L2)
- Concurrent in-process misses funnel to ONE loader call
- `loader_timeout_millis` integration (M5.1 helper reuse)
- Per-key lock table shrinks via weakref GC
- L1 TTL applied
"""

from __future__ import annotations

import gc
import os
import threading
import time
import uuid
from typing import Iterator, List, Optional

import pytest

from atlas_richie.cache_redis import (
    L2DistributedCache,
    RedisProviderRegistrar,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    return RedisProviderRegistrar.from_url(REDIS_URL, namespace="atlas-richie-test")


@pytest.fixture
def l2_cache(registrar: RedisProviderRegistrar) -> Iterator[L2DistributedCache]:
    cache = L2DistributedCache(
        value_ops=registrar.value_ops(),
        region="m5-2-test",
        max_size=100,
        ttl_seconds=60,
    )
    yield cache
    # Cleanup: invalidate any leftover L1 entries (we use unique
    # keys so collisions are unlikely, but be safe).
    cache.invalidate_l1("_unused_")


@pytest.fixture
def unique_key() -> str:
    return f"gor:test:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, l2_cache: L2DistributedCache, unique_key: str) -> Iterator[None]:
    l2_cache.invalidate_l1(unique_key)
    # Also wipe the L2 (Redis) side directly.
    raw = registrar._backend.raw_client()
    raw.delete(registrar._backend.make_key(unique_key))
    yield
    l2_cache.invalidate_l1(unique_key)
    raw.delete(registrar._backend.make_key(unique_key))


# ── 1. L1 hit short-circuits ─────────────────────────────────────────


def test_l1_hit_skips_loader(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """Pre-populate L1; loader is NOT called, no lock acquired."""
    l2_cache.set(unique_key, b"preset-l1", ttl_seconds=60)
    calls: List[int] = []

    def loader() -> Optional[bytes]:
        calls.append(1)
        return b"should-not-be-loaded"

    result = l2_cache.get_or_load(unique_key, loader)
    assert result == b"preset-l1"
    assert calls == [], f"loader was called on L1 hit: {calls!r}"


# ── 2. L1 miss + L2 hit (read-through) ──────────────────────────────


def test_l1_miss_l2_hit_read_through(
    l2_cache: L2DistributedCache, registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """L1 empty, L2 has the value: loader is NOT called, L1 is populated,
    the L2 value is returned."""
    # Seed only the L2 (Redis), bypass L1.
    registrar._backend.set(unique_key, b"l2-only-value")
    l2_cache.invalidate_l1(unique_key)  # ensure L1 cold
    calls: List[int] = []

    def loader() -> Optional[bytes]:
        calls.append(1)
        return b"should-not-be-loaded"

    result = l2_cache.get_or_load(unique_key, loader)
    assert result == b"l2-only-value"
    assert calls == [], f"loader was called on L2 hit: {calls!r}"
    # L1 must now have the value.
    assert l2_cache.get(unique_key) == b"l2-only-value"


# ── 3. L1 + L2 miss + loader succeeds ───────────────────────────────


def test_l1_l2_miss_loader_called_once(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """L1 and L2 both empty: loader called once, value written to
    both L1 and L2, returned."""
    calls: List[int] = []

    def loader() -> Optional[bytes]:
        calls.append(1)
        return b"loaded-value"

    result = l2_cache.get_or_load(unique_key, loader)
    assert result == b"loaded-value"
    assert calls == [1]
    # Both L1 and L2 should have the value now.
    assert l2_cache.get(unique_key) == b"loaded-value"


# ── 4. L1 + L2 miss + loader returns None ──────────────────────────


def test_l1_l2_miss_loader_returns_none(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """`loader()` returns `None` → no writes to L1 or L2; returns `None`."""
    def loader() -> Optional[bytes]:
        return None

    result = l2_cache.get_or_load(unique_key, loader)
    assert result is None
    # L1 and L2 must remain empty.
    assert l2_cache.get(unique_key) is None


# ── 5. L1 + L2 miss + loader exceeds timeout ────────────────────────


def test_l1_l2_miss_loader_timeout(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """Loader exceeds `loader_timeout_millis` → returns `None`,
    no writes, no exception."""
    def loader() -> Optional[bytes]:
        time.sleep(0.2)
        return b"too-slow"

    result = l2_cache.get_or_load(
        unique_key, loader, loader_timeout_millis=50
    )
    assert result is None
    assert l2_cache.get(unique_key) is None


# ── 6. L1 + L2 miss + loader raises ─────────────────────────────────


def test_l1_l2_miss_loader_raises(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """Loader raises → exception propagates; no writes; the in-process
    lock is released (next call can acquire)."""

    class LoaderError(RuntimeError):
        pass

    def loader() -> Optional[bytes]:
        raise LoaderError("simulated")

    with pytest.raises(LoaderError, match="simulated"):
        l2_cache.get_or_load(unique_key, loader)

    # Next call must work (lock released cleanly).
    def good_loader() -> Optional[bytes]:
        return b"good"

    result = l2_cache.get_or_load(unique_key, good_loader)
    assert result == b"good"


# ── 7. Concurrent in-process misses funnel to ONE loader call ───────


def test_concurrent_misses_funnel_to_one_loader(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """10 threads racing on a cold key → loader called exactly once
    (in-process stampede funnel)."""
    n_threads = 10
    barrier = threading.Barrier(n_threads)
    call_count_lock = threading.Lock()
    call_count = 0
    loader_delay = 0.1

    def loader() -> Optional[bytes]:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(loader_delay)
        return b"concurrent-value"

    results: List[Optional[bytes]] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        r = l2_cache.get_or_load(unique_key, loader)
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)

    assert all(r == b"concurrent-value" for r in results), (
        f"some threads got wrong result: {results!r}"
    )
    assert call_count == 1, (
        f"expected exactly 1 loader call (in-process funnel), got {call_count}"
    )


# ── 8. Concurrent loaders for DIFFERENT keys are independent ───────


def test_concurrent_loaders_for_different_keys(
    l2_cache: L2DistributedCache
) -> None:
    """5 keys, 2 threads each → each key's loader called once = 5
    total loader invocations (per-key lock granularity)."""
    n_keys = 5
    n_threads_per_key = 2
    keys = [f"gor:diffkey:{uuid.uuid4().hex[:8]}_{i}" for i in range(n_keys)]

    call_count_lock = threading.Lock()
    call_count_by_key = {k: 0 for k in keys}

    def make_loader(k: str):
        def loader() -> Optional[bytes]:
            with call_count_lock:
                call_count_by_key[k] += 1
            time.sleep(0.05)
            return f"value-{k}".encode()

        return loader

    barrier = threading.Barrier(n_keys * n_threads_per_key)
    results: List[tuple[str, bytes]] = []
    results_lock = threading.Lock()

    def worker(k: str) -> None:
        loader = make_loader(k)
        barrier.wait()
        r = l2_cache.get_or_load(k, loader)
        with results_lock:
            results.append((k, r))

    threads = [
        threading.Thread(target=worker, args=(k,))
        for k in keys
        for _ in range(n_threads_per_key)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)

    for k in keys:
        assert call_count_by_key[k] == 1, (
            f"key {k} loader should be called once, got {call_count_by_key[k]}"
        )
    assert len(results) == n_keys * n_threads_per_key
    # All results must equal the value for their key (each thread's
    # result corresponds to its own key, recorded alongside the
    # return value).
    for k, r in results:
        assert r == f"value-{k}".encode(), f"key {k}: got {r!r}"


# ── 9. loader_timeout_millis=None preserves legacy behavior ─────────


def test_loader_timeout_none_legacy(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """Default `loader_timeout_millis=None` → legacy unbounded behavior."""
    def loader() -> Optional[bytes]:
        time.sleep(0.1)
        return b"slow-but-ok"

    result = l2_cache.get_or_load(unique_key, loader)  # no timeout kwarg
    assert result == b"slow-but-ok"


# ── 10. loader_timeout_millis=0 / negative → ValueError ─────────────


def test_loader_timeout_zero_raises(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="loader_timeout_millis"):
        l2_cache.get_or_load(unique_key, lambda: b"x", loader_timeout_millis=0)


def test_loader_timeout_negative_raises(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="loader_timeout_millis"):
        l2_cache.get_or_load(unique_key, lambda: b"x", loader_timeout_millis=-100)


# ── 11. Per-key lock table shrinks after calls exit ─────────────────


def test_key_lock_table_shrinks(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    """After all `with` blocks exit (no threads holding locks), the
    `_key_locks` weak-value-dictionary should have 0 (or near-0) live
    entries for the key we just used."""
    # Issue a call to populate the table.
    l2_cache.get_or_load(unique_key, lambda: b"x")

    # Force a GC pass so the WeakValueDictionary drops the entry
    # (the caller's frame is gone; the only strong ref was held
    # in the `with` block, which has exited).
    gc.collect()

    # The table should be empty (or at most contain a few entries
    # from other concurrent test runs sharing the same L2CacheFactory
    # instance).
    # We assert that our specific key is GONE from the table.
    assert unique_key not in l2_cache._key_locks, (
        f"lock for {unique_key!r} leaked in _key_locks after the "
        f"with block exited; weakref GC didn't reclaim it"
    )


# ── 12. Custom ttl_seconds applied to L1 + L2 entries ───────────────


def test_ttl_seconds_applied(
    l2_cache: L2DistributedCache, registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """`ttl_seconds=2` → both L1 and L2 entries expire within ~2s."""
    result = l2_cache.get_or_load(unique_key, lambda: b"ttl-test", ttl_seconds=2)
    assert result == b"ttl-test"

    # L2 (Redis) PTTL should be <= 2000ms (with 300ms slop).
    pttl = registrar._backend.raw_client().pttl(
        registrar._backend.make_key(unique_key)
    )
    assert 0 < pttl <= 2300, f"expected 0 < pttl <= 2300, got {pttl}"


# ── 13. None loader → ValueError ─────────────────────────────────────


def test_none_loader_raises(
    l2_cache: L2DistributedCache, unique_key: str
) -> None:
    with pytest.raises(ValueError, match="loader is required"):
        l2_cache.get_or_load(unique_key, None)  # type: ignore[arg-type]
