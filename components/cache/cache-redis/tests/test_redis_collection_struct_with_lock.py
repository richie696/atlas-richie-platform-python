"""Real-Redis stampede-prevention tests for ``*_with_lock`` on
``RedisCollectionManager`` and ``RedisStructManager`` (R-220 M4).

Covers the four M4 entry points:

- ``CollectionOps.get_with_lock(key, clazz, timeout_millis, db_loader)``
- ``SetFunction.get_from_set_with_lock(key, reference, db_loader, timeout_millis)``
- ``StructOps.get_with_lock(key, clazz, timeout_millis, db_loader)``
- ``StructOps.get_with_lock_typed(key, reference, timeout_millis, db_loader)``

For each of the 4 methods we exercise the 8 standard behaviours:

1. **Cache hit short-circuits** — db_loader MUST NOT be called.
2. **Cache miss + lock acquired** — db_loader is called once,
   result is written to the cache, returned to the caller.
3. **Cache miss + lock NOT acquired** — caller polls; if the
   winner publishes, the cached value is returned.
4. **``db_loader()`` returns ``None`` / empty** — nothing is
   written to the cache; the appropriate empty value is returned.
5. **Concurrent callers (10 threads)** — the db_loader is called
   at most a small constant number of times (the stampede lock
   funnels concurrent misses to a single load).
6. **Stampede lock cleanup** — the ``__stampede_lock__:key`` Redis
   key is gone after a successful call.
7. **TTL applied to the cache entry** — the value expires within
   the expected window.
8. **Argument validation** — zero / negative ``timeout_millis`` and
   ``None`` ``db_loader`` are rejected with ``ValueError``.

The shared ``_stampede_release`` helper's compare-and-delete
correctness is verified once in a dedicated test (it's the same
Lua release path used by every ``*_with_lock`` method on every
manager — see ``test_redis_string_manager_with_lock.py`` for the
String version of the same check).

Notes
----
- The Set path uses ``EXISTS`` (not ``SCARD`` / ``SMEMBERS``) as
  the hit detector so that a *cached* empty Set is honoured as a
  valid value, distinct from a missing key.
- The cache-write path on the Set variant uses ``DEL + SADD +
  PEXPIRE`` directly (no anti-avalanche offset) because the
  ``*_with_lock`` path is the canonical write path and the caller
  is responsible for any TTL jitter policy.
- The Struct variant uses ``set_with_ttl`` which passes the
  caller-supplied TTL through verbatim (no anti-avalanche offset).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Callable, Iterator, List

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import RedisProviderRegistrar
from atlas_richie.cache_redis.managers.redis_string_manager import (
    _stampede_release,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    return RedisProviderRegistrar.from_url(
        REDIS_URL, namespace="atlas-richie-test"
    )


@pytest.fixture
def unique_key() -> str:
    return f"stampede:test:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(
    registrar: RedisProviderRegistrar, unique_key: str
) -> Iterator[None]:
    """Wipe cache + stampede lock before AND after each test."""
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    lock_key = registrar._backend.make_key(
        f"__stampede_lock__:{unique_key}"
    )
    client.delete(full_key, lock_key)
    yield
    client.delete(full_key, lock_key)


def _pre_acquire_lock(
    registrar: RedisProviderRegistrar, unique_key: str, owner: str, ttl_ms: int
) -> str:
    """Pre-acquire the stampede lock as ``owner`` with ``ttl_ms`` TTL.

    Returns the full lock key for later inspection.
    """
    client = registrar._backend.raw_client()
    lock_key = registrar._backend.make_key(
        f"__stampede_lock__:{unique_key}"
    )
    client.set(lock_key, owner, px=ttl_ms)
    return lock_key


# ════════════════════════════════════════════════════════════════════
# 1. CollectionOps.get_with_lock  (key, clazz, timeout_millis, db_loader)
# ════════════════════════════════════════════════════════════════════


class TestCollectionOpsGetWithLock:
    """``CollectionOps.get_with_lock`` — Redis Set stampede prevention."""

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        manager.add_set(unique_key, {"preset-a", "preset-b"})
        calls: List[int] = []

        def loader() -> set | None:
            calls.append(1)
            return {"fresh"}

        result = manager.get_with_lock(
            unique_key, str, timeout_millis=60_000, db_loader=loader
        )

        assert result == {"preset-a", "preset-b"}
        assert calls == [], f"db_loader was called on cache hit: {calls!r}"

    def test_cache_miss_acquires_lock_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def loader() -> set | None:
            calls.append(1)
            return {"loaded-a", "loaded-b"}

        result = manager.get_with_lock(
            unique_key, str, timeout_millis=10_000, db_loader=loader
        )

        assert result == {"loaded-a", "loaded-b"}
        assert calls == [1]
        cached = manager.get(unique_key, str)
        assert cached == {"loaded-a", "loaded-b"}

    def test_lock_loser_polls_and_returns_published_value(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        # Pre-acquire the stampede lock so we lose the race.
        _pre_acquire_lock(registrar, unique_key, "other-process", 5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.add_set(unique_key, {"winner-a", "winner-b"})

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> set | None:
            return {"should-not-be-called"}

        result = manager.get_with_lock(
            unique_key, str, timeout_millis=3_000, db_loader=loader
        )
        publisher.join(timeout=2.0)

        assert result == {"winner-a", "winner-b"}, (
            f"expected published set, got {result!r}"
        )

    def test_db_loader_returns_none_no_cache_write(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        def loader() -> set | None:
            return None

        result = manager.get_with_lock(
            unique_key, str, timeout_millis=10_000, db_loader=loader
        )

        assert result == set()
        # Cache must remain absent.
        raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert raw is None
        # Lock must be released.
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_concurrent_callers_funnel_to_one_load(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> set | None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return {"concurrent-a", "concurrent-b"}

        results: List[set | None] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_with_lock(
                unique_key, str, timeout_millis=3_000, db_loader=loader
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        expected = {"concurrent-a", "concurrent-b"}
        assert all(r == expected for r in results), (
            f"some threads got wrong result: {results!r}"
        )
        # Allow up to 3 loader calls (1 winner + up to 2 stragglers).
        assert 1 <= call_count <= 3, (
            f"expected 1-3 db_loader calls, got {call_count}"
        )

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        def loader() -> set | None:
            return {"x"}

        manager.get_with_lock(
            unique_key, str, timeout_millis=10_000, db_loader=loader
        )

        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None, (
            "stampede lock key leaked after successful call"
        )

    def test_ttl_applied_to_cache_entry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        ttl_millis = 1_000

        def loader() -> set | None:
            return {"ttl-test"}

        manager.get_with_lock(
            unique_key, str, timeout_millis=ttl_millis, db_loader=loader
        )

        full_key = registrar._backend.make_key(unique_key)
        pttl = registrar._backend.raw_client().pttl(full_key)
        assert 0 < pttl <= ttl_millis + 200, (
            f"expected 0 < pttl <= {ttl_millis + 200}, got {pttl}"
        )

    def test_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock(
                unique_key, str, timeout_millis=0, db_loader=lambda: set()
            )

    def test_negative_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock(
                unique_key, str, timeout_millis=-100, db_loader=lambda: set()
            )

    def test_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_with_lock(
                unique_key, str, timeout_millis=10_000, db_loader=None  # type: ignore[arg-type]
            )


# ════════════════════════════════════════════════════════════════════
# 2. SetFunction.get_from_set_with_lock
#    (key, reference, db_loader, timeout_millis)
# ════════════════════════════════════════════════════════════════════


class TestSetFunctionGetFromSetWithLock:
    """``SetFunction.get_from_set_with_lock`` — business-facing Set
    stampede prevention."""

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        manager.add_set(unique_key, {"preset-a", "preset-b"})
        calls: List[int] = []

        def loader() -> set | None:
            calls.append(1)
            return {"fresh"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 60_000
        )

        assert result == {"preset-a", "preset-b"}
        assert calls == [], f"db_loader was called on cache hit: {calls!r}"

    def test_cache_miss_acquires_lock_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        calls: List[int] = []

        def loader() -> set | None:
            calls.append(1)
            return {"loaded-a", "loaded-b"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 10_000
        )

        assert result == {"loaded-a", "loaded-b"}
        assert calls == [1]
        cached = manager.get_from_set(unique_key, str)
        assert cached == {"loaded-a", "loaded-b"}

    def test_lock_loser_polls_and_returns_published_value(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        _pre_acquire_lock(registrar, unique_key, "other-process", 5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.add_set(unique_key, {"winner-a", "winner-b"})

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> set | None:
            return {"should-not-be-called"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 3_000
        )
        publisher.join(timeout=2.0)

        assert result == {"winner-a", "winner-b"}, (
            f"expected published set, got {result!r}"
        )

    def test_db_loader_returns_none_no_cache_write(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()

        def loader() -> set | None:
            return None

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 10_000
        )

        assert result == set()
        # Lock must be released.
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_concurrent_callers_funnel_to_one_load(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> set | None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return {"concurrent-a", "concurrent-b"}

        results: List[set | None] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_from_set_with_lock(
                unique_key, str, loader, 3_000
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        expected = {"concurrent-a", "concurrent-b"}
        assert all(r == expected for r in results), (
            f"some threads got wrong result: {results!r}"
        )
        assert 1 <= call_count <= 3, (
            f"expected 1-3 db_loader calls, got {call_count}"
        )

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()

        def loader() -> set | None:
            return {"x"}

        manager.get_from_set_with_lock(unique_key, str, loader, 10_000)

        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None, (
            "stampede lock key leaked after successful call"
        )

    def test_ttl_applied_to_cache_entry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        ttl_millis = 1_000

        def loader() -> set | None:
            return {"ttl-test"}

        manager.get_from_set_with_lock(unique_key, str, loader, ttl_millis)

        full_key = registrar._backend.make_key(unique_key)
        pttl = registrar._backend.raw_client().pttl(full_key)
        assert 0 < pttl <= ttl_millis + 200, (
            f"expected 0 < pttl <= {ttl_millis + 200}, got {pttl}"
        )

    def test_argument_validation(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_from_set_with_lock(
                unique_key, str, lambda: set(), 0
            )
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_from_set_with_lock(
                unique_key, str, lambda: set(), -100
            )
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_from_set_with_lock(
                unique_key, str, None, 10_000  # type: ignore[arg-type]
            )


# ════════════════════════════════════════════════════════════════════
# 3. StructOps.get_with_lock  (key, clazz, timeout_millis, db_loader)
# ════════════════════════════════════════════════════════════════════


class TestStructOpsGetWithLock:
    """``StructOps.get_with_lock`` — whole-object stampede prevention."""

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        manager.set(unique_key, {"preset": "value"})
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            return {"fresh": "value"}

        result = manager.get_with_lock(
            unique_key, dict, timeout_millis=60_000, db_loader=loader
        )

        assert result == {"preset": "value"}
        assert calls == [], f"db_loader was called on cache hit: {calls!r}"

    def test_cache_miss_acquires_lock_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            return {"loaded": "value", "n": 42}

        result = manager.get_with_lock(
            unique_key, dict, timeout_millis=10_000, db_loader=loader
        )

        assert result == {"loaded": "value", "n": 42}
        assert calls == [1]
        assert manager.get(unique_key, dict) == {"loaded": "value", "n": 42}

    def test_lock_loser_polls_and_returns_published_value(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        _pre_acquire_lock(registrar, unique_key, "other-process", 5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.set(unique_key, {"winner": True})

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> Any:
            return {"should-not-be-called": True}

        result = manager.get_with_lock(
            unique_key, dict, timeout_millis=3_000, db_loader=loader
        )
        publisher.join(timeout=2.0)

        assert result == {"winner": True}, (
            f"expected published dict, got {result!r}"
        )

    def test_db_loader_returns_none_no_cache_write(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def loader() -> Any:
            return None

        result = manager.get_with_lock(
            unique_key, dict, timeout_millis=10_000, db_loader=loader
        )

        assert result is None
        # Cache must remain absent.
        raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert raw is None

    def test_concurrent_callers_funnel_to_one_load(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> Any:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return {"concurrent": "value"}

        results: List[Any] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_with_lock(
                unique_key, dict, timeout_millis=3_000, db_loader=loader
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert all(r == {"concurrent": "value"} for r in results), (
            f"some threads got wrong result: {results!r}"
        )
        assert 1 <= call_count <= 3, (
            f"expected 1-3 db_loader calls, got {call_count}"
        )

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def loader() -> Any:
            return {"x": 1}

        manager.get_with_lock(
            unique_key, dict, timeout_millis=10_000, db_loader=loader
        )

        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None, (
            "stampede lock key leaked after successful call"
        )

    def test_ttl_applied_to_cache_entry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        ttl_millis = 1_000

        def loader() -> Any:
            return {"ttl": "test"}

        manager.get_with_lock(
            unique_key, dict, timeout_millis=ttl_millis, db_loader=loader
        )

        full_key = registrar._backend.make_key(unique_key)
        pttl = registrar._backend.raw_client().pttl(full_key)
        assert 0 < pttl <= ttl_millis + 200, (
            f"expected 0 < pttl <= {ttl_millis + 200}, got {pttl}"
        )

    def test_argument_validation(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock(
                unique_key, dict, timeout_millis=0, db_loader=lambda: {}
            )
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock(
                unique_key, dict, timeout_millis=-100, db_loader=lambda: {}
            )
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_with_lock(
                unique_key, dict, timeout_millis=10_000, db_loader=None  # type: ignore[arg-type]
            )


# ════════════════════════════════════════════════════════════════════
# 4. StructOps.get_with_lock_typed  (key, reference, timeout_millis, db_loader)
# ════════════════════════════════════════════════════════════════════


class TestStructOpsGetWithLockTyped:
    """``StructOps.get_with_lock_typed`` — runtime-type variant."""

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        manager.set(unique_key, "preset-string")
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            return "fresh-string"

        result = manager.get_with_lock_typed(
            unique_key, str, timeout_millis=60_000, db_loader=loader
        )

        assert result == "preset-string"
        assert calls == [], f"db_loader was called on cache hit: {calls!r}"

    def test_cache_miss_acquires_lock_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            return "loaded-string"

        result = manager.get_with_lock_typed(
            unique_key, str, timeout_millis=10_000, db_loader=loader
        )

        assert result == "loaded-string"
        assert calls == [1]
        assert manager.get_typed(unique_key, str) == "loaded-string"

    def test_lock_loser_polls_and_returns_published_value(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        _pre_acquire_lock(registrar, unique_key, "other-process", 5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.set(unique_key, "winner-string")

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> Any:
            return "should-not-be-called"

        result = manager.get_with_lock_typed(
            unique_key, str, timeout_millis=3_000, db_loader=loader
        )
        publisher.join(timeout=2.0)

        assert result == "winner-string", (
            f"expected published value, got {result!r}"
        )

    def test_db_loader_returns_none_no_cache_write(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def loader() -> Any:
            return None

        result = manager.get_with_lock_typed(
            unique_key, dict, timeout_millis=10_000, db_loader=loader
        )

        assert result is None
        raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert raw is None

    def test_concurrent_callers_funnel_to_one_load(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> Any:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return "concurrent-string"

        results: List[Any] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_with_lock_typed(
                unique_key, str, timeout_millis=3_000, db_loader=loader
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert all(r == "concurrent-string" for r in results), (
            f"some threads got wrong result: {results!r}"
        )
        assert 1 <= call_count <= 3, (
            f"expected 1-3 db_loader calls, got {call_count}"
        )

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def loader() -> Any:
            return "x"

        manager.get_with_lock_typed(
            unique_key, str, timeout_millis=10_000, db_loader=loader
        )

        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None, (
            "stampede lock key leaked after successful call"
        )

    def test_ttl_applied_to_cache_entry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        ttl_millis = 1_000

        def loader() -> Any:
            return "ttl-test"

        manager.get_with_lock_typed(
            unique_key, str, timeout_millis=ttl_millis, db_loader=loader
        )

        full_key = registrar._backend.make_key(unique_key)
        pttl = registrar._backend.raw_client().pttl(full_key)
        assert 0 < pttl <= ttl_millis + 200, (
            f"expected 0 < pttl <= {ttl_millis + 200}, got {pttl}"
        )

    def test_argument_validation(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, str, timeout_millis=0, db_loader=lambda: "x"
            )
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, str, timeout_millis=-100, db_loader=lambda: "x"
            )
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_with_lock_typed(
                unique_key, str, timeout_millis=10_000, db_loader=None  # type: ignore[arg-type]
            )


# ════════════════════════════════════════════════════════════════════
# 5. Shared: stale-lock compare-and-delete
# ════════════════════════════════════════════════════════════════════


def test_stale_lock_compare_and_delete(
    registrar: RedisProviderRegistrar, unique_key: str
) -> None:
    """The ``_stampede_release`` helper used by every ``*_with_lock``
    method on every manager must refuse to delete a lock re-acquired
    by a different holder after our TTL expired.

    This is a shared atomicity test — the same Lua release path is
    used by String / Set / Struct stampede prevention.
    """
    client = registrar._backend.raw_client()
    lock_key = _pre_acquire_lock(registrar, unique_key, "stale-ours", 100)
    # Wait for our TTL to expire.
    time.sleep(0.15)
    # Another process takes the lock with a different request_id.
    client.set(lock_key, "new-holder", px=10_000)
    # Trigger release with OUR (stale) request_id.
    released = _stampede_release(client, lock_key, "stale-ours")
    assert released is False, "compare-and-delete should refuse to release"

    # The new holder's lock must still be intact.
    holder = client.get(lock_key)
    if isinstance(holder, bytes):
        holder = holder.decode("utf-8")
    assert holder == "new-holder", (
        f"stale release clobbered the new holder's lock: {holder!r}"
    )
