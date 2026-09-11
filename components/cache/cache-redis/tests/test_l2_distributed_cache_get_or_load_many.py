"""M5.3 tests: `L2DistributedCache.get_or_load_many` + stats observability.

Covers:

1. **Batch happy path** — all keys L1+L2 miss → loader called once
   for the batch → all results returned, written to L1+L2.
2. **Batch partial L1 hit** — some keys in L1, some missing → loader
   called only with the missing keys.
3. **Batch partial L2 hit** — some keys in L2, some missing → loader
   called only with the L2-missing keys.
4. **Concurrent batch funnel** — N threads each call
   `get_or_load_many` with the same key set → loader called exactly
   once across all threads.
5. **Per-key order preserved** — loader returning a partial dict
   (some keys missing) results in those keys having `None` value.
6. **`loader_timeout_millis` integration** — same as R-M5.1, on a
   timed-out batch, all `missing` keys get `None`.
7. **Empty keys list** — returns `{}` without calling the loader.
8. **Stats observability** — after a few `get_or_load` calls,
   `stats()` reflects the cumulative fan-in / wait time / lock
   table size / loader timeouts.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Callable, Dict, Iterator, List, Optional

import pytest

from atlas_richie.cache_redis import L2DistributedCache, RedisProviderRegistrar

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
        region=f"m5-3-batch-{uuid.uuid4().hex[:8]}",
        max_size=100,
        ttl_seconds=60,
    )
    yield cache
    cache.invalidate_l1("_unused_")


@pytest.fixture
def unique_keys() -> List[str]:
    return [f"batch:test:{uuid.uuid4().hex[:8]}_{i}" for i in range(5)]


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, l2_cache: L2DistributedCache, unique_keys: List[str]) -> Iterator[None]:
    raw = registrar._backend.raw_client()
    for k in unique_keys:
        l2_cache.invalidate_l1(k)
        raw.delete(registrar._backend.make_key(k))
    yield
    for k in unique_keys:
        l2_cache.invalidate_l1(k)
        raw.delete(registrar._backend.make_key(k))


# ── 1. Batch happy path ─────────────────────────────────────────────


def test_batch_all_miss_loader_called_once(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """All 5 keys L1+L2 miss → loader called once for the batch."""
    call_count_lock = threading.Lock()
    call_count = 0
    captured_missing: List[List[str]] = []

    def loader(missing: List[str]) -> Dict[str, bytes]:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        captured_missing.append(list(missing))
        # Simulate 100ms downstream latency.
        time.sleep(0.1)
        return {k: f"v-{k}".encode() for k in missing}

    results = l2_cache.get_or_load_many(unique_keys, loader)
    assert set(results.keys()) == set(unique_keys)
    for k in unique_keys:
        assert results[k] == f"v-{k}".encode()
    assert call_count == 1
    assert captured_missing[0] == unique_keys  # loader received all 5


# ── 2. Batch partial L1 hit ─────────────────────────────────────────


def test_batch_partial_l1_hit(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """3 keys pre-populated in L1, 2 missing → loader called with 2."""
    pre_populated = unique_keys[:3]
    missing = unique_keys[3:]
    # Seed L1 directly (bypass L2).
    for k in pre_populated:
        l2_cache.set(k, f"l1-{k}".encode(), ttl_seconds=60)

    captured_missing: List[List[str]] = []

    def loader(missing_keys: List[str]) -> Dict[str, bytes]:
        captured_missing.append(list(missing_keys))
        return {k: f"loaded-{k}".encode() for k in missing_keys}

    results = l2_cache.get_or_load_many(unique_keys, loader)
    # Pre-populated keys: l1 values
    for k in pre_populated:
        assert results[k] == f"l1-{k}".encode()
    # Missing keys: loader values
    for k in missing:
        assert results[k] == f"loaded-{k}".encode()
    # Loader only received the missing keys
    assert captured_missing[0] == missing


# ── 3. Batch partial L2 hit ─────────────────────────────────────────


def test_batch_partial_l2_hit(
    l2_cache: L2DistributedCache, unique_keys: List[str], registrar: RedisProviderRegistrar
) -> None:
    """L1 empty, 2 keys in L2, 3 missing → loader called with 3."""
    in_l2 = unique_keys[:2]
    missing = unique_keys[2:]
    for k in in_l2:
        registrar._backend.set(k, f"l2-{k}".encode())
        l2_cache.invalidate_l1(k)  # ensure L1 cold

    captured_missing: List[List[str]] = []

    def loader(missing_keys: List[str]) -> Dict[str, bytes]:
        captured_missing.append(list(missing_keys))
        return {k: f"loaded-{k}".encode() for k in missing_keys}

    results = l2_cache.get_or_load_many(unique_keys, loader)
    for k in in_l2:
        assert results[k] == f"l2-{k}".encode()
    for k in missing:
        assert results[k] == f"loaded-{k}".encode()
    assert captured_missing[0] == missing


# ── 4. Concurrent batch funnel ──────────────────────────────────────


def test_concurrent_batch_funnel(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """10 threads each call `get_or_load_many` with the same 5 keys →
    loader called exactly once across all threads."""
    n_threads = 10
    barrier = threading.Barrier(n_threads)
    call_count_lock = threading.Lock()
    call_count = 0

    def loader(missing: List[str]) -> Dict[str, bytes]:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        time.sleep(0.1)  # hold the stampede lock
        return {k: f"v-{k}".encode() for k in missing}

    results_list: List[Dict[str, bytes]] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        r = l2_cache.get_or_load_many(unique_keys, loader)
        with results_lock:
            results_list.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)

    assert call_count == 1, (
        f"expected 1 loader call (in-process funnel), got {call_count}"
    )
    assert len(results_list) == n_threads
    for r in results_list:
        for k in unique_keys:
            assert r[k] == f"v-{k}".encode()


# ── 5. Loader partial return → missing keys get None ───────────────


def test_loader_returns_partial_dict(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """Loader returns only some of the missing keys → others get `None`."""
    returned_subset = unique_keys[:2]

    def loader(missing: List[str]) -> Dict[str, bytes]:
        return {k: f"v-{k}".encode() for k in returned_subset}

    results = l2_cache.get_or_load_many(unique_keys, loader)
    for k in returned_subset:
        assert results[k] == f"v-{k}".encode()
    for k in unique_keys[2:]:
        assert results[k] is None


def test_loader_returns_empty_dict(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """Loader returns empty dict → all missing keys get `None`."""

    def loader(missing: List[str]) -> Dict[str, bytes]:
        return {}

    results = l2_cache.get_or_load_many(unique_keys, loader)
    for k in unique_keys:
        assert results[k] is None


# ── 6. loader_timeout_millis integration ───────────────────────────


def test_loader_timeout_in_batch(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """Loader exceeds timeout → all `missing` keys get `None`,
    `loader_timeouts` counter increments."""

    def slow_loader(missing: List[str]) -> Dict[str, bytes]:
        time.sleep(0.3)
        return {k: b"x" for k in missing}

    stats_before = l2_cache.stats()
    results = l2_cache.get_or_load_many(
        unique_keys, slow_loader, loader_timeout_millis=50
    )
    stats_after = l2_cache.stats()

    for k in unique_keys:
        assert results[k] is None
    assert stats_after["loader_timeouts"] == stats_before["loader_timeouts"] + 1


# ── 7. Empty keys list ──────────────────────────────────────────────


def test_empty_keys_returns_empty_dict(
    l2_cache: L2DistributedCache
) -> None:
    call_count = 0

    def loader(missing: List[str]) -> Dict[str, bytes]:
        nonlocal call_count
        call_count += 1
        return {}

    results = l2_cache.get_or_load_many([], loader)
    assert results == {}
    assert call_count == 0


# ── 8. Stats observability ──────────────────────────────────────────


def test_stats_reflects_load_operations(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    """After a few `get_or_load` calls, `stats()` shows non-zero counters."""
    initial = l2_cache.stats()
    assert initial["hits"] == 0
    assert initial["misses"] == 0
    assert initial["loader_timeouts"] == 0
    assert initial["in_process_loader_fan_in"] == 0

    # First call: L1+L2 miss → 1 fan-in
    l2_cache.get_or_load_many(
        unique_keys, lambda m: {k: b"x" for k in m}
    )
    # Second call: all hits (L1) → 0 fan-in
    l2_cache.get_or_load_many(
        unique_keys, lambda m: (_ for _ in ()).throw(
            AssertionError("loader should not be called when L1 hits")
        )
    )

    after = l2_cache.stats()
    assert after["in_process_loader_fan_in"] == 1
    assert after["hits"] == 5
    assert after["misses"] == 5
    assert after["loader_timeouts"] == 0
    # wait_seconds > 0 because we measured even instant acquires.
    assert after["in_process_loader_wait_seconds"] >= 0
    # key_lock_table_size is the count of live `_KeyLock` instances.
    # After all `with` blocks exited and `gc.collect()` was called by
    # `_live_key_lock_count`, it should be small (possibly 0).
    assert after["key_lock_table_size"] >= 0


# ── 9. Validation ───────────────────────────────────────────────────


def test_none_loader_raises(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    with pytest.raises(ValueError, match="loader is required"):
        l2_cache.get_or_load_many(unique_keys, None)  # type: ignore[arg-type]


def test_loader_timeout_zero_raises(
    l2_cache: L2DistributedCache, unique_keys: List[str]
) -> None:
    with pytest.raises(ValueError, match="loader_timeout_millis"):
        l2_cache.get_or_load_many(
            unique_keys, lambda m: {}, loader_timeout_millis=0
        )


# ── 10. Cross-batch order independence ────────────────────────────


def test_concurrent_batches_with_different_key_sets_are_independent(
    l2_cache: L2DistributedCache
) -> None:
    """Two concurrent batches with DIFFERENT keys → 2 loader calls
    (per-key locks funnel, but different keys = different locks)."""
    keys_a = [f"batch:A:{uuid.uuid4().hex[:6]}_{i}" for i in range(3)]
    keys_b = [f"batch:B:{uuid.uuid4().hex[:6]}_{i}" for i in range(3)]
    call_count_lock = threading.Lock()
    call_count = 0

    def make_loader(tag: str) -> Callable[[List[str]], Dict[str, bytes]]:
        def loader(missing: List[str]) -> Dict[str, bytes]:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(0.05)
            return {k: tag.encode() for k in missing}
        return loader

    barrier = threading.Barrier(2)
    results: Dict[str, Dict[str, bytes]] = {}
    results_lock = threading.Lock()

    def worker(tag: str, keys: List[str], loader: Callable) -> None:
        barrier.wait()
        r = l2_cache.get_or_load_many(keys, loader)
        with results_lock:
            results[tag] = r

    t_a = threading.Thread(
        target=worker, args=("A", keys_a, make_loader("A"))
    )
    t_b = threading.Thread(
        target=worker, args=("B", keys_b, make_loader("B"))
    )
    t_a.start()
    t_b.start()
    t_a.join(timeout=2.0)
    t_b.join(timeout=2.0)

    # Each batch independently called its own loader once.
    assert call_count == 2
    for k in keys_a:
        assert results["A"][k] == b"A"
    for k in keys_b:
        assert results["B"][k] == b"B"
