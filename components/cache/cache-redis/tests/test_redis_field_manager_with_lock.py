"""Real-Redis stampede-prevention tests for `RedisFieldManager` (M4).

Covers the six M4 entry points:

- `FieldOps.get_with_lock(key, field, clazz, timeout_millis, db_loader)`
- `FieldOps.get_with_lock_typed(key, field, reference, timeout_millis, db_loader)`
- `FieldOps.get_many_with_lock(key, fields, clazz, timeout_millis, db_loader)`
- `HashFunction.get_object_from_hash_with_lock(key, clazz, db_loader, timeout_millis)`
- `HashFunction.get_from_hash_with_lock(key, hash_key, clazz, db_loader, timeout_millis)`
- `HashFunction.get_from_hash_with_lock_typed(key, hash_key, reference, db_loader, timeout_millis)`

The four single-field variants share `RedisFieldManager._stampede_load_field`
internally; the object variant has its own `_stampede_load_object`; the
batch variant has `_stampede_load_many`. The tests exercise the
public surface (so the shared internals are validated transitively).

What's verified for each method (where the shape makes sense):

1. **Cache hit short-circuits** — db_loader is NOT called.
2. **Cache miss + lock acquired** — db_loader is called exactly
   once, result is written to the cache, returned to the caller.
3. **Cache miss + lock NOT acquired** — caller polls; if the
   winner publishes, the cached value is returned; if the winner
   doesn't publish within the wait budget, returns `None`.
4. **`db_loader()` returns `None`** — nothing is written to the
   cache, returns `None`.
5. **Concurrent callers** — the db_loader is called at most a
   small constant number of times (the stampede lock funnels
   concurrent misses).
6. **Stampede lock cleanup** — the per-method lock key is gone
   after a successful call (compare-and-delete works).
7. **Stale-lock compare-and-delete** — manually overwrite the
   lock key's value to simulate "another process took our lock
   after our TTL expired" and confirm we don't accidentally
   delete the new holder's lock.
8. **TTL is applied to the cache entry** — the value expires
   within the expected window.
9. **Argument validation** — `timeout_millis > 0`, `db_loader`
   is not `None`.

For `_typed` variants, additionally verify the typed read uses
the registered type from `CacheInfrastructure` (or the caller-
supplied `reference` as fallback).

For `get_many_with_lock`, additionally verify:

- **Partial hit**: some keys cached, others loaded via db_loader.
- **All miss**: db_loader called once for the whole batch.
- **Empty keys list** returns `{}` without calling db_loader.

The Redis URL is configurable via `ATLAS_RICHIE_CACHE_REDIS_URL`
so the suite can be pointed at any reachable Redis (8.x preferred
for `HTTL` / `HEXPIRE` / `HGETALL` semantics).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import RedisProviderRegistrar

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    """One registrar per test module — every test uses a unique key
    so concurrent tests can't collide on the underlying Redis
    namespace."""
    return RedisProviderRegistrar.from_url(REDIS_URL, namespace="atlas-richie-test")


@pytest.fixture
def unique_key() -> str:
    return f"stampede:field:{uuid.uuid4().hex[:12]}"


@pytest.fixture
def unique_fields() -> List[str]:
    return [f"f{i}" for i in range(1, 6)]


@pytest.fixture(autouse=True)
def _cleanup(registrar: RedisProviderRegistrar, unique_key: str) -> Iterator[None]:
    """Wipe hash + all stampede-lock shapes for `unique_key` before
    AND after each test. The lock shapes we use:

    - `__stampede_lock__:{key}`         (object variant)
    - `__stampede_lock__:{key}:{field}` (per-field variant, all 5)
    - `__stampede_lock__:{key}:batch:*` (batch variant; we glob)
    """
    client = registrar._backend.raw_client()
    # Wipe any pre-existing hash at the user key.
    client.delete(registrar._backend.make_key(unique_key))
    # Wipe per-field stampede locks for the field set we use.
    for i in range(1, 6):
        client.delete(
            registrar._backend.make_key(f"__stampede_lock__:{unique_key}:f{i}")
        )
    # Wipe the per-key object stampede lock.
    client.delete(registrar._backend.make_key(f"__stampede_lock__:{unique_key}"))
    # Wipe any batch stampede locks under this key.
    for lock_key in client.scan_iter(
        match=registrar._backend.make_key(f"__stampede_lock__:{unique_key}:batch:*"),
        count=100,
    ):
        client.delete(lock_key)
    yield
    # Post-test cleanup.
    client.delete(registrar._backend.make_key(unique_key))
    for i in range(1, 6):
        client.delete(
            registrar._backend.make_key(f"__stampede_lock__:{unique_key}:f{i}")
        )
    client.delete(registrar._backend.make_key(f"__stampede_lock__:{unique_key}"))
    for lock_key in client.scan_iter(
        match=registrar._backend.make_key(f"__stampede_lock__:{unique_key}:batch:*"),
        count=100,
    ):
        client.delete(lock_key)


# ══════════════════════════════════════════════════════════════════
# 1. get_with_lock (FieldOps)
# ══════════════════════════════════════════════════════════════════


class TestGetWithLock:
    """`FieldOps.get_with_lock(key, field, clazz, timeout_millis, db_loader)`.

    Single-field HGET + per-(key, field) Lua stampede lock. Mirrors
    `HashFunction.getFromHashWithLock(key, hashKey, clazz, dbLoader, timeout)`
    in Java.
    """

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Pre-populated field → db_loader MUST NOT be called."""
        manager = registrar.field_ops()
        manager.set(unique_key, "f1", "preset-value")
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "fresh-value"

        result = manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=60_000, db_loader=loader
        )

        assert result == "preset-value"
        assert calls == [], f"db_loader was called on cache hit: {calls!r}"

    def test_cache_miss_acquires_lock_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """First miss → db_loader called once → cache populated → returned."""
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "loaded-value"

        result = manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=10_000, db_loader=loader
        )

        assert result == "loaded-value"
        assert calls == [1]
        assert manager.get(unique_key, "f1", str) == "loaded-value"

    def test_lock_loser_polls_and_returns_published_value(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """If the stampede lock is held externally, the caller polls
        and returns whatever the holder publishes."""
        manager = registrar.field_ops()
        client = registrar._backend.raw_client()
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:f1"
        )
        other_request_id = "another-process"
        client.set(lock_key, other_request_id, px=5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.set(unique_key, "f1", "winner-published-value")

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> str | None:
            return "should-not-be-called"

        result = manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=3_000, db_loader=loader
        )

        publisher.join(timeout=2.0)
        assert result == "winner-published-value", (
            f"expected 'winner-published-value', got {result!r}"
        )

    def test_db_loader_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """`db_loader()` returning `None` must NOT pollute the cache."""
        manager = registrar.field_ops()

        def loader() -> str | None:
            return None

        result = manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=10_000, db_loader=loader
        )

        assert result is None
        raw = manager._backend.raw_client().hget(
            registrar._backend.make_key(unique_key), "f1"
        )
        assert raw is None

    def test_concurrent_callers_funnel_to_one_load(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """10 threads racing on the same cold field → at most 2-3
        db_loader invocations (stampede lock funnels)."""
        manager = registrar.field_ops()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> str | None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return "concurrent-loaded-value"

        results: List[str | None] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_with_lock(
                unique_key, "f1", str, timeout_millis=3_000, db_loader=loader
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert all(r == "concurrent-loaded-value" for r in results), (
            f"some threads got wrong result: {results!r}"
        )
        assert 1 <= call_count <= 3, (
            f"expected 1-3 db_loader calls, got {call_count} "
            f"(stampede lock should funnel concurrent misses)"
        )

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """After a successful get_with_lock, the per-(key, field)
        stampede lock key must be gone."""
        manager = registrar.field_ops()

        def loader() -> str | None:
            return "value-x"

        manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=10_000, db_loader=loader
        )

        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:f1"
        )
        assert registrar._backend.raw_client().get(lock_key) is None, (
            "stampede lock key leaked after successful call"
        )

    def test_stale_lock_compare_and_delete(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Simulate "our TTL expired while we were loading, another
        process took the lock, then we finished" — our
        compare-and-delete MUST NOT delete the new holder's lock."""
        client = registrar._backend.raw_client()
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:f1"
        )
        our_request_id = "stale-ours"
        client.set(lock_key, our_request_id, px=100)
        time.sleep(0.15)
        other_request_id = "new-holder"
        client.set(lock_key, other_request_id, px=10_000)

        from atlas_richie.cache_redis.managers.redis_string_manager import (
            _stampede_release,
        )
        released = _stampede_release(client, lock_key, our_request_id)
        assert released is False, "compare-and-delete should refuse to release"

        holder = client.get(lock_key)
        if isinstance(holder, bytes):
            holder = holder.decode("utf-8")
        assert holder == other_request_id, (
            f"stale release clobbered the new holder's lock: {holder!r}"
        )

    def test_ttl_applied_to_cache_entry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """The published value must expire within roughly the
        `timeout_millis` window (allow 200ms slop for clock skew)."""
        manager = registrar.field_ops()
        ttl_millis = 1_000

        def loader() -> str | None:
            return "ttl-test"

        manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=ttl_millis, db_loader=loader
        )

        # HPTTL returns a list (one TTL per field); only one field set.
        ptls = registrar._backend.raw_client().hpttl(
            registrar._backend.make_key(unique_key), "f1"
        )
        assert ptls and 0 < ptls[0] <= ttl_millis + 200, (
            f"expected 0 < HPTTL <= {ttl_millis + 200}, got {ptls!r}"
        )

    def test_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock(
                unique_key, "f1", str, timeout_millis=0, db_loader=lambda: "x"
            )

    def test_negative_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock(
                unique_key, "f1", str, timeout_millis=-100, db_loader=lambda: "x"
            )

    def test_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_with_lock(
                unique_key, "f1", str, timeout_millis=10_000, db_loader=None  # type: ignore[arg-type]
            )


# ══════════════════════════════════════════════════════════════════
# 2. get_with_lock_typed (FieldOps)
# ══════════════════════════════════════════════════════════════════


class TestGetWithLockTyped:
    """`FieldOps.get_with_lock_typed`.

    Same shape as `get_with_lock` but the cache-hit read uses
    `CacheInfrastructure.get_value_type` to resolve the type, falling
    back to the caller-supplied `reference`. The lock + writeback are
    identical.
    """

    def test_typed_cache_hit_uses_registered_type(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """When the caller pre-registers a type via
        `CacheInfrastructure.register_type`, the typed read must use
        that type (not the `reference` argument)."""
        manager = registrar.field_ops()
        # Register `int` for this key.
        registrar._infra.register_type(unique_key, int)
        try:
            # Cache stores an integer; passing `str` as reference must
            # NOT be used because the registry has a binding.
            manager.set(unique_key, "f1", 42)
            calls: List[int] = []

            def loader() -> int | None:
                calls.append(1)
                return 99

            result = manager.get_with_lock_typed(
                unique_key, "f1", str,  # reference is ignored
                timeout_millis=10_000, db_loader=loader,
            )
            assert result == 42
            assert isinstance(result, int)
            assert calls == []
        finally:
            # Wipe the binding so other tests aren't affected.
            registrar._infra._value_types.pop(
                registrar._backend.make_key(unique_key), None,
            )

    def test_typed_cache_hit_falls_back_to_reference(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Without a registered type, the typed read uses the
        caller-supplied `reference`."""
        manager = registrar.field_ops()
        # The string "42" stored; int(reference=int) would fail to
        # parse it, so this case must be deserialised as `str` (the
        # reference) — meaning the result stays `"42"`.
        manager.set(unique_key, "f1", "42")
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "should-not-load"

        result = manager.get_with_lock_typed(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
        )
        assert result == "42"
        assert calls == []

    def test_typed_cache_miss_loads(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Cache miss on a typed read still invokes the loader."""
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            return 7

        result = manager.get_with_lock_typed(
            unique_key, "f1", int,
            timeout_millis=10_000, db_loader=loader,
        )
        assert result == 7
        assert calls == [1]
        assert manager.get(unique_key, "f1", int) == 7

    def test_typed_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, "f1", str, timeout_millis=0, db_loader=lambda: "x"
            )

    def test_typed_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_with_lock_typed(
                unique_key, "f1", str, timeout_millis=10_000,
                db_loader=None,  # type: ignore[arg-type]
            )


# ══════════════════════════════════════════════════════════════════
# 3. get_object_from_hash_with_lock (HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetObjectFromHashWithLock:
    """`HashFunction.get_object_from_hash_with_lock(key, clazz, db_loader, timeout_millis)`.

    The object is stored under a reserved hash field
    (`_OBJECT_FIELD = "__obj__"`). The lock granularity is the
    whole key (not per-field). Mirrors
    `HashFunction.getObjectFromHashWithLock(key, clazz, dbLoader, timeout)` in Java.
    """

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        # Pre-populate the object slot.
        manager.set(unique_key, "__obj__", {"name": "richie", "age": 42})
        calls: List[int] = []

        def loader() -> dict[str, Any] | None:
            calls.append(1)
            return {"name": "fresh"}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 60_000
        )
        assert result == {"name": "richie", "age": 42}
        assert calls == []

    def test_cache_miss_acquires_lock_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> dict[str, Any] | None:
            calls.append(1)
            return {"k": "v"}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 10_000
        )
        assert result == {"k": "v"}
        assert calls == [1]
        # Verify it was cached under the reserved field.
        assert manager.get(unique_key, "__obj__", dict) == {"k": "v"}

    def test_db_loader_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def loader() -> dict[str, Any] | None:
            return None

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 10_000
        )
        assert result is None
        # The reserved field must remain empty.
        assert manager.get(unique_key, "__obj__", dict) is None

    def test_lock_loser_polls(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        client = registrar._backend.raw_client()
        # Per-key object lock shape: `__stampede_lock__:{key}`.
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        client.set(lock_key, "external-holder", px=5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.set(unique_key, "__obj__", {"winner": True})

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> dict[str, Any] | None:
            return {"should": "not-load"}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 3_000
        )
        publisher.join(timeout=2.0)
        assert result == {"winner": True}

    def test_concurrent_callers_funnel(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> dict[str, Any] | None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return {"x": 1}

        results: List[dict[str, Any] | None] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_object_from_hash_with_lock(
                unique_key, dict, loader, 3_000
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert all(r == {"x": 1} for r in results), f"results={results!r}"
        assert 1 <= call_count <= 3, f"expected 1-3, got {call_count}"

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        manager.get_object_from_hash_with_lock(
            unique_key, dict, lambda: {"a": 1}, 10_000
        )
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_ttl_applied(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        ttl_millis = 1_000
        manager.get_object_from_hash_with_lock(
            unique_key, dict, lambda: {"k": "v"}, ttl_millis
        )
        ptls = registrar._backend.raw_client().hpttl(
            registrar._backend.make_key(unique_key), "__obj__"
        )
        assert ptls and 0 < ptls[0] <= ttl_millis + 200, (
            f"expected 0 < HPTTL <= {ttl_millis + 200}, got {ptls!r}"
        )

    def test_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_object_from_hash_with_lock(
                unique_key, dict, lambda: {"a": 1}, 0
            )

    def test_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_object_from_hash_with_lock(
                unique_key, dict, None, 10_000  # type: ignore[arg-type]
            )


# ══════════════════════════════════════════════════════════════════
# 4. get_from_hash_with_lock (HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetFromHashWithLock:
    """`HashFunction.get_from_hash_with_lock(key, hash_key, clazz, db_loader, timeout_millis)`.

    Functionally identical to `get_with_lock`; exists separately to
    match the `HashFunction` Protocol surface. Argument order
    differs: `(key, hash_key, clazz, db_loader, timeout_millis)` vs
    the FieldOps shape.
    """

    def test_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        manager.set(unique_key, "f1", "preset")
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "fresh"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 60_000
        )
        assert result == "preset"
        assert calls == []

    def test_cache_miss_loads_and_writes(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "loaded"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 10_000
        )
        assert result == "loaded"
        assert calls == [1]
        assert manager.get(unique_key, "f1", str) == "loaded"

    def test_argument_order_only(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """`get_from_hash_with_lock` and `get_with_lock` must be
        interchangeable — only the argument order differs."""
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "from-hash"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 10_000
        )
        assert result == "from-hash"
        assert calls == [1]
        assert manager.get(unique_key, "f1", str) == "from-hash"

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        manager.get_from_hash_with_lock(
            unique_key, "f1", str, lambda: "x", 10_000
        )
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:f1"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_from_hash_with_lock(
                unique_key, "f1", str, lambda: "x", 0
            )

    def test_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_from_hash_with_lock(
                unique_key, "f1", str, None, 10_000  # type: ignore[arg-type]
            )


# ══════════════════════════════════════════════════════════════════
# 5. get_from_hash_with_lock_typed (HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetFromHashWithLockTyped:
    """`HashFunction.get_from_hash_with_lock_typed`.

    Same shape as `get_from_hash_with_lock` but cache-hit read uses
    `CacheInfrastructure.get_value_type` (falls back to `reference`).
    """

    def test_typed_cache_hit_uses_registered_type(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        registrar._infra.register_type(unique_key, int)
        try:
            manager.set(unique_key, "f1", 99)
            calls: List[int] = []

            def loader() -> int | None:
                calls.append(1)
                return 0

            result = manager.get_from_hash_with_lock_typed(
                unique_key, "f1", str,  # reference is ignored
                loader, 10_000,
            )
            assert result == 99
            assert isinstance(result, int)
            assert calls == []
        finally:
            registrar._infra._value_types.pop(
                registrar._backend.make_key(unique_key), None,
            )

    def test_typed_cache_miss_loads(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            return 1234

        result = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, loader, 10_000,
        )
        assert result == 1234
        assert calls == [1]
        assert manager.get(unique_key, "f1", int) == 1234

    def test_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_from_hash_with_lock_typed(
                unique_key, "f1", str, lambda: "x", 0
            )

    def test_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_from_hash_with_lock_typed(
                unique_key, "f1", str, None, 10_000  # type: ignore[arg-type]
            )


# ══════════════════════════════════════════════════════════════════
# 6. get_many_with_lock (FieldOps)
# ══════════════════════════════════════════════════════════════════


class TestGetManyWithLock:
    """`FieldOps.get_many_with_lock(key, fields, clazz, timeout_millis, db_loader)`.

    One HMGET reads all fields; a single per-(key, sorted-fields)
    stampede lock guards the load; the loader is called ONCE for
    the whole batch. Batches with the same set of fields funnel to
    one db_loader; different sets do not contend.
    """

    def test_empty_keys_returns_empty_without_calling_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> Dict[str, Any] | None:
            calls.append(1)
            return {"f1": "v1"}

        result = manager.get_many_with_lock(
            unique_key, [], str, timeout_millis=10_000, db_loader=loader,
        )
        assert result == {}
        assert calls == [], "db_loader must not be called for empty input"

    def test_full_cache_hit_skips_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        manager.set(unique_key, "f1", "a")
        manager.set(unique_key, "f2", "b")
        calls: List[int] = []

        def loader() -> Dict[str, str] | None:
            calls.append(1)
            return {"f3": "c"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str, timeout_millis=10_000,
            db_loader=loader,
        )
        assert result == {"f1": "a", "f2": "b"}
        assert calls == [], "full cache hit must not call db_loader"

    def test_partial_hit_loads_missing_via_db_loader(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Some keys cached, others loaded via the db_loader."""
        manager = registrar.field_ops()
        manager.set(unique_key, "f1", "cached-1")
        # f2 missing → must be loaded.
        calls: List[int] = []

        def loader() -> Dict[str, str] | None:
            calls.append(1)
            return {"f2": "loaded-2"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str, timeout_millis=10_000,
            db_loader=loader,
        )
        assert result == {"f1": "cached-1", "f2": "loaded-2"}
        assert calls == [1]
        # Loaded value must now be cached.
        assert manager.get(unique_key, "f2", str) == "loaded-2"

    def test_all_miss_calls_loader_once(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> Dict[str, str] | None:
            calls.append(1)
            return {"f1": "v1", "f2": "v2", "f3": "v3"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2", "f3"], str, timeout_millis=10_000,
            db_loader=loader,
        )
        assert result == {"f1": "v1", "f2": "v2", "f3": "v3"}
        assert calls == [1], (
            "all-miss batch must invoke db_loader exactly once"
        )

    def test_loader_returns_none_no_cache_write(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> Dict[str, str] | None:
            return None

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str, timeout_millis=10_000,
            db_loader=loader,
        )
        assert result == {}
        # Cache must remain empty.
        raw = manager._backend.raw_client().hgetall(
            registrar._backend.make_key(unique_key)
        )
        assert raw == {} or raw is None or raw == b""

    def test_loader_returns_empty_dict(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """An empty dict is treated the same as `None` — nothing
        is written and the method returns whatever was cached
        (which is also empty in this case)."""
        manager = registrar.field_ops()

        def loader() -> Dict[str, str] | None:
            return {}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str, timeout_millis=10_000,
            db_loader=loader,
        )
        assert result == {}

    def test_concurrent_callers_funnel_to_one_load(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """10 threads on the same field set → at most 2-3 db_loader
        calls (per-batch lock funnels concurrent batches)."""
        manager = registrar.field_ops()
        fields = ["f1", "f2", "f3"]
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> Dict[str, str] | None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return {"f1": "v1", "f2": "v2", "f3": "v3"}

        results: List[Dict[str, str]] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_many_with_lock(
                unique_key, fields, str, timeout_millis=3_000,
                db_loader=loader,
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert all(r == {"f1": "v1", "f2": "v2", "f3": "v3"} for r in results), (
            f"some threads got wrong result: {results!r}"
        )
        assert 1 <= call_count <= 3, (
            f"expected 1-3 db_loader calls, got {call_count}"
        )

    def test_lock_loser_polls(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """If a per-batch lock is held externally, the caller polls
        and returns the published batch when it appears."""
        manager = registrar.field_ops()
        fields = ["f1", "f2"]
        # Compute the same batch lock key the manager would use.
        from atlas_richie.cache_redis.managers.redis_field_manager import (
            _make_batch_lock_key,
        )
        lock_key = _make_batch_lock_key(registrar._backend, unique_key, fields)
        registrar._backend.raw_client().set(lock_key, "external", px=5_000)

        def publish_after_delay() -> None:
            time.sleep(0.2)
            manager.set(unique_key, "f1", "winner-1")
            manager.set(unique_key, "f2", "winner-2")

        publisher = threading.Thread(target=publish_after_delay)
        publisher.start()

        def loader() -> Dict[str, str] | None:
            return {"f1": "should-not-load", "f2": "should-not-load"}

        result = manager.get_many_with_lock(
            unique_key, fields, str, timeout_millis=3_000, db_loader=loader,
        )
        publisher.join(timeout=2.0)
        assert result == {"f1": "winner-1", "f2": "winner-2"}, (
            f"expected published batch, got {result!r}"
        )

    def test_stampede_lock_removed_after_success(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        from atlas_richie.cache_redis.managers.redis_field_manager import (
            _make_batch_lock_key,
        )
        fields = ["f1", "f2"]
        lock_key = _make_batch_lock_key(registrar._backend, unique_key, fields)

        manager.get_many_with_lock(
            unique_key, fields, str, timeout_millis=10_000,
            db_loader=lambda: {"f1": "a", "f2": "b"},
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_ttl_applied_to_all_loaded_fields(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Every field written by the loader must carry the
        caller-supplied TTL (no anti-avalanche offset)."""
        manager = registrar.field_ops()
        ttl_millis = 1_500

        manager.get_many_with_lock(
            unique_key, ["f1", "f2", "f3"], str, timeout_millis=ttl_millis,
            db_loader=lambda: {"f1": "a", "f2": "b", "f3": "c"},
        )
        ptls = registrar._backend.raw_client().hpttl(
            registrar._backend.make_key(unique_key), "f1", "f2", "f3"
        )
        # Each field should have a TTL in the (0, ttl_millis+slop] window.
        assert len(ptls) == 3, f"expected 3 TTLs, got {ptls!r}"
        for pttl in ptls:
            assert 0 < pttl <= ttl_millis + 200, (
                f"expected 0 < HPTTL <= {ttl_millis + 200}, got {ptl} for one of {ptls!r}"
            )

    def test_zero_timeout_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="timeout_millis"):
            manager.get_many_with_lock(
                unique_key, ["f1"], str, timeout_millis=0,
                db_loader=lambda: {"f1": "x"},
            )

    def test_none_loader_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="db_loader"):
            manager.get_many_with_lock(
                unique_key, ["f1"], str, timeout_millis=10_000,
                db_loader=None,  # type: ignore[arg-type]
            )

    def test_different_field_sets_do_not_contend(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Two concurrent batches with DIFFERENT field sets should
        both proceed (they have different batch lock keys)."""
        manager = registrar.field_ops()
        calls: Dict[str, int] = {"a": 0, "b": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def loader_a() -> Dict[str, str] | None:
            with lock:
                calls["a"] += 1
            time.sleep(0.2)
            return {"f1": "from-a"}

        def loader_b() -> Dict[str, str] | None:
            with lock:
                calls["b"] += 1
            time.sleep(0.2)
            return {"f2": "from-b"}

        results: Dict[str, Dict[str, str]] = {}
        results_lock = threading.Lock()

        def worker(name: str, fields: List[str], loader: Callable[[], Dict[str, str] | None]) -> None:
            barrier.wait()
            r = manager.get_many_with_lock(
                unique_key, fields, str, timeout_millis=5_000,
                db_loader=loader,
            )
            with results_lock:
                results[name] = r

        t1 = threading.Thread(target=worker, args=("a", ["f1"], loader_a))
        t2 = threading.Thread(target=worker, args=("b", ["f2"], loader_b))
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        assert results == {"a": {"f1": "from-a"}, "b": {"f2": "from-b"}}
        # Both loaders should have been called exactly once (their
        # batch lock keys are different).
        assert calls == {"a": 1, "b": 1}
