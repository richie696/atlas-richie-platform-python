"""Real-Redis loader-timeout tests for `RedisFieldManager` (M5.1).

Covers the new `loader_timeout_millis` keyword argument on the six
`*_with_lock` methods of `RedisFieldManager`:

- `FieldOps.get_with_lock(key, field, clazz, timeout_millis, db_loader)`
- `FieldOps.get_with_lock_typed(key, field, reference, timeout_millis, db_loader)`
- `FieldOps.get_many_with_lock(key, fields, clazz, timeout_millis, db_loader)`
- `HashFunction.get_object_from_hash_with_lock(key, clazz, db_loader, timeout_millis)`
- `HashFunction.get_from_hash_with_lock(key, hash_key, clazz, db_loader, timeout_millis)`
- `HashFunction.get_from_hash_with_lock_typed(key, hash_key, reference, db_loader, timeout_millis)`

For each method we exercise the same standard cases that the String
sample uses (see `test_redis_string_manager_loader_timeout.py`):

1. `loader_timeout_millis=None` preserves the legacy (unbounded) behavior.
2. Loader finishes within the timeout → return value, cache populated.
3. Loader exceeds the timeout → return `None` (or `{}` for batch),
   no cache write, no exception.
4. Loader raises → exception propagates, lock released.
5. `loader_timeout_millis=0` → `ValueError`.
6. `loader_timeout_millis<0` → `ValueError`.
7. Cache-hit path unaffected by `loader_timeout_millis`.
8. After a timed-out loader call, the next call (with a new
   `db_loader`) is NOT affected — the stampede lock was released.

The Function / `HashFunction` aliases (cases 9–10 in the String sample)
are exercised for the 4 single-field methods (each has both a
`FieldOps` and a `HashFunction` alias) and for the batch method.
The shared `_stampede_load_field` / `_stampede_load_object` /
`_stampede_load_many` internals are validated transitively.

For `get_many_with_lock` (batch) the timeout applies to the SINGLE
`db_loader()` call (returning a dict for all missing keys) — NOT
per-key loops. Two extra batch-specific cases verify partial-hit
unions + no-cache-write on timeout.

The Redis URL is configurable via `ATLAS_RICHIE_CACHE_REDIS_URL`.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List

import pytest

from atlas_richie.cache_redis import RedisProviderRegistrar

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registrar() -> RedisProviderRegistrar:
    return RedisProviderRegistrar.from_url(
        REDIS_URL, namespace="atlas-richie-test"
    )


@pytest.fixture
def unique_key() -> str:
    return f"timeout:field:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(
    registrar: RedisProviderRegistrar, unique_key: str
) -> Iterator[None]:
    """Wipe the hash + all stampede-lock shapes (per-field, per-key,
    batch) for `unique_key` before AND after each test."""
    client = registrar._backend.raw_client()
    client.delete(registrar._backend.make_key(unique_key))
    for i in range(1, 6):
        client.delete(
            registrar._backend.make_key(
                f"__stampede_lock__:{unique_key}:f{i}"
            )
        )
    client.delete(
        registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    )
    for lock_key in client.scan_iter(
        match=registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:batch:*"
        ),
        count=100,
    ):
        client.delete(lock_key)
    yield
    client.delete(registrar._backend.make_key(unique_key))
    for i in range(1, 6):
        client.delete(
            registrar._backend.make_key(
                f"__stampede_lock__:{unique_key}:f{i}"
            )
        )
    client.delete(
        registrar._backend.make_key(f"__stampede_lock__:{unique_key}")
    )
    for lock_key in client.scan_iter(
        match=registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:batch:*"
        ),
        count=100,
    ):
        client.delete(lock_key)


# ══════════════════════════════════════════════════════════════════
# 1. get_with_lock (FieldOps)
# ══════════════════════════════════════════════════════════════════


class TestGetWithLockLoaderTimeout:
    """`FieldOps.get_with_lock(key, field, clazz, timeout_millis, db_loader)`
    + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Default behavior — no loader timeout, return value as-is."""
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "value"

        result = manager.get_with_lock(
            unique_key, "f1", str, timeout_millis=10_000, db_loader=loader
        )
        assert result == "value"
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> str | None:
            time.sleep(0.05)
            return "fast-value"

        result = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == "fast-value"
        assert manager.get(unique_key, "f1", str) == "fast-value"

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            time.sleep(0.3)
            return "slow-value"

        result = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]
        assert manager.get(unique_key, "f1", str) is None

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        class LoaderError(RuntimeError):
            pass

        def loader() -> str | None:
            raise LoaderError("simulated loader failure")

        with pytest.raises(LoaderError, match="simulated loader failure"):
            manager.get_with_lock(
                unique_key, "f1", str,
                timeout_millis=10_000, db_loader=loader,
                loader_timeout_millis=1_000,
            )
        assert manager.get(unique_key, "f1", str) is None
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}:f1"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock(
                unique_key, "f1", str,
                timeout_millis=10_000, db_loader=lambda: "x",
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock(
                unique_key, "f1", str,
                timeout_millis=10_000, db_loader=lambda: "x",
                loader_timeout_millis=-100,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        manager.set(unique_key, "f1", "preset")
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            time.sleep(5.0)
            return "would-block-forever"

        result = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=100,
        )
        assert result == "preset"
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def slow_loader() -> str | None:
            time.sleep(0.2)
            return "slow"

        r1 = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> str | None:
            return "fast"

        r2 = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=5_000, db_loader=fast_loader,
        )
        assert r2 == "fast"

    def test_hash_function_alias_accepts_kwarg(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """The `HashFunction.get_from_hash_with_lock` alias (different
        argument order: key, hash_key, clazz, db_loader, timeout_millis)
        also accepts the new `loader_timeout_millis` kwarg."""
        manager = registrar.hash_function()

        def slow_loader() -> str | None:
            time.sleep(0.2)
            return "slow"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, slow_loader, 5_000,
            loader_timeout_millis=20,
        )
        assert result is None

    def test_concurrent_callers_with_timeouts_funnel(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
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
            return "would-be-result"

        results: List[str | None] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_with_lock(
                unique_key, "f1", str,
                timeout_millis=5_000, db_loader=loader,
                loader_timeout_millis=50,
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert all(r is None for r in results), (
            f"some threads got non-None results: {results!r}"
        )
        assert call_count == 1, (
            f"expected exactly 1 loader call (winner), got {call_count}"
        )


# ══════════════════════════════════════════════════════════════════
# 2. get_with_lock_typed (FieldOps)
# ══════════════════════════════════════════════════════════════════


class TestGetWithLockTypedLoaderTimeout:
    """`FieldOps.get_with_lock_typed` + `loader_timeout_millis` (M5.1).

    The timeout governs only the `db_loader()` call; the typed read
    (after the loader returns) is in-process and bounded.
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            return 42

        result = manager.get_with_lock_typed(
            unique_key, "f1", int, timeout_millis=10_000, db_loader=loader
        )
        assert result == 42
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> int | None:
            time.sleep(0.05)
            return 7

        result = manager.get_with_lock_typed(
            unique_key, "f1", int,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == 7

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            time.sleep(0.3)
            return 99

        result = manager.get_with_lock_typed(
            unique_key, "f1", int,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        class LoaderError(RuntimeError):
            pass

        def loader() -> int | None:
            raise LoaderError("typed-load-fail")

        with pytest.raises(LoaderError, match="typed-load-fail"):
            manager.get_with_lock_typed(
                unique_key, "f1", int,
                timeout_millis=10_000, db_loader=loader,
                loader_timeout_millis=1_000,
            )

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, "f1", int,
                timeout_millis=10_000, db_loader=lambda: 0,
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, "f1", int,
                timeout_millis=10_000, db_loader=lambda: 0,
                loader_timeout_millis=-1,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        manager.set(unique_key, "f1", 7)
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            time.sleep(5.0)
            return 99

        result = manager.get_with_lock_typed(
            unique_key, "f1", int,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=100,
        )
        assert result == 7
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def slow_loader() -> int | None:
            time.sleep(0.2)
            return 1

        r1 = manager.get_with_lock_typed(
            unique_key, "f1", int,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> int | None:
            return 2

        r2 = manager.get_with_lock_typed(
            unique_key, "f1", int,
            timeout_millis=5_000, db_loader=fast_loader,
        )
        assert r2 == 2


# ══════════════════════════════════════════════════════════════════
# 3. get_object_from_hash_with_lock (HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetObjectFromHashWithLockLoaderTimeout:
    """`HashFunction.get_object_from_hash_with_lock(key, clazz, db_loader,
    timeout_millis)` + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> dict | None:
            calls.append(1)
            return {"name": "alice", "age": 30}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 10_000
        )
        assert result == {"name": "alice", "age": 30}
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def loader() -> dict | None:
            time.sleep(0.05)
            return {"k": "v"}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 10_000,
            loader_timeout_millis=500,
        )
        assert result == {"k": "v"}

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> dict | None:
            calls.append(1)
            time.sleep(0.3)
            return {"k": "v"}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 10_000,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        class LoaderError(RuntimeError):
            pass

        def loader() -> dict | None:
            raise LoaderError("obj-fail")

        with pytest.raises(LoaderError, match="obj-fail"):
            manager.get_object_from_hash_with_lock(
                unique_key, dict, loader, 10_000,
                loader_timeout_millis=1_000,
            )

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_object_from_hash_with_lock(
                unique_key, dict, lambda: {}, 10_000,
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_object_from_hash_with_lock(
                unique_key, dict, lambda: {}, 10_000,
                loader_timeout_millis=-50,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        manager.set(unique_key, "__obj__", {"preset": True})
        calls: List[int] = []

        def loader() -> dict | None:
            calls.append(1)
            time.sleep(5.0)
            return {"fresh": True}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict, loader, 10_000,
            loader_timeout_millis=100,
        )
        assert result == {"preset": True}
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def slow_loader() -> dict | None:
            time.sleep(0.2)
            return {"x": 1}

        r1 = manager.get_object_from_hash_with_lock(
            unique_key, dict, slow_loader, 5_000,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> dict | None:
            return {"y": 2}

        r2 = manager.get_object_from_hash_with_lock(
            unique_key, dict, fast_loader, 5_000,
        )
        assert r2 == {"y": 2}

    def test_concurrent_callers_with_timeouts_funnel(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        call_count_lock = threading.Lock()
        call_count = 0
        loader_delay_seconds = 0.3

        def loader() -> dict | None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            time.sleep(loader_delay_seconds)
            return {"winner": True}

        results: List[Any] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_object_from_hash_with_lock(
                unique_key, dict, loader, 5_000,
                loader_timeout_millis=50,
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert all(r is None for r in results), (
            f"some threads got non-None results: {results!r}"
        )
        assert call_count == 1, (
            f"expected exactly 1 loader call (winner), got {call_count}"
        )


# ══════════════════════════════════════════════════════════════════
# 4. get_from_hash_with_lock (HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetFromHashWithLockLoaderTimeout:
    """`HashFunction.get_from_hash_with_lock(key, hash_key, clazz,
    db_loader, timeout_millis)` + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            return "value"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 10_000
        )
        assert result == "value"
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def loader() -> str | None:
            time.sleep(0.05)
            return "fast-value"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 10_000,
            loader_timeout_millis=500,
        )
        assert result == "fast-value"
        assert manager.get(unique_key, "f1", str) == "fast-value"

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            time.sleep(0.3)
            return "slow-value"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 10_000,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        class LoaderError(RuntimeError):
            pass

        def loader() -> str | None:
            raise LoaderError("hash-fail")

        with pytest.raises(LoaderError, match="hash-fail"):
            manager.get_from_hash_with_lock(
                unique_key, "f1", str, loader, 10_000,
                loader_timeout_millis=1_000,
            )

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_from_hash_with_lock(
                unique_key, "f1", str, lambda: "x", 10_000,
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_from_hash_with_lock(
                unique_key, "f1", str, lambda: "x", 10_000,
                loader_timeout_millis=-100,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        manager.set(unique_key, "f1", "preset")
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            time.sleep(5.0)
            return "would-block-forever"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str, loader, 10_000,
            loader_timeout_millis=100,
        )
        assert result == "preset"
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def slow_loader() -> str | None:
            time.sleep(0.2)
            return "slow"

        r1 = manager.get_from_hash_with_lock(
            unique_key, "f1", str, slow_loader, 5_000,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> str | None:
            return "fast"

        r2 = manager.get_from_hash_with_lock(
            unique_key, "f1", str, fast_loader, 5_000,
        )
        assert r2 == "fast"

    def test_field_ops_alias_accepts_kwarg(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """The `FieldOps.get_with_lock` alias (different argument
        order: key, field, clazz, timeout_millis, db_loader) also
        accepts the new `loader_timeout_millis` kwarg."""
        manager = registrar.field_ops()

        def slow_loader() -> str | None:
            time.sleep(0.2)
            return "slow"

        result = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert result is None

    def test_concurrent_callers_with_timeouts_funnel(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
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
            return "would-be-result"

        results: List[str | None] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_from_hash_with_lock(
                unique_key, "f1", str, loader, 5_000,
                loader_timeout_millis=50,
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert all(r is None for r in results), (
            f"some threads got non-None results: {results!r}"
        )
        assert call_count == 1, (
            f"expected exactly 1 loader call (winner), got {call_count}"
        )


# ══════════════════════════════════════════════════════════════════
# 5. get_from_hash_with_lock_typed (HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetFromHashWithLockTypedLoaderTimeout:
    """`HashFunction.get_from_hash_with_lock_typed` +
    `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            return 42

        result = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, loader, 10_000
        )
        assert result == 42
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def loader() -> int | None:
            time.sleep(0.05)
            return 99

        result = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, loader, 10_000,
            loader_timeout_millis=500,
        )
        assert result == 99

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            time.sleep(0.3)
            return 1

        result = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, loader, 10_000,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        class LoaderError(RuntimeError):
            pass

        def loader() -> int | None:
            raise LoaderError("typed-hash-fail")

        with pytest.raises(LoaderError, match="typed-hash-fail"):
            manager.get_from_hash_with_lock_typed(
                unique_key, "f1", int, loader, 10_000,
                loader_timeout_millis=1_000,
            )

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_from_hash_with_lock_typed(
                unique_key, "f1", int, lambda: 0, 10_000,
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_from_hash_with_lock_typed(
                unique_key, "f1", int, lambda: 0, 10_000,
                loader_timeout_millis=-1,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()
        manager.set(unique_key, "f1", 7)
        calls: List[int] = []

        def loader() -> int | None:
            calls.append(1)
            time.sleep(5.0)
            return 99

        result = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, loader, 10_000,
            loader_timeout_millis=100,
        )
        assert result == 7
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.hash_function()

        def slow_loader() -> int | None:
            time.sleep(0.2)
            return 1

        r1 = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, slow_loader, 5_000,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> int | None:
            return 2

        r2 = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", int, fast_loader, 5_000,
        )
        assert r2 == 2


# ══════════════════════════════════════════════════════════════════
# 6. get_many_with_lock (FieldOps / HashFunction)
# ══════════════════════════════════════════════════════════════════


class TestGetManyWithLockLoaderTimeout:
    """`get_many_with_lock` + `loader_timeout_millis` (M5.1).

    The timeout applies to the SINGLE `db_loader()` call (returning
    a dict for all missing keys) — NOT per-key loops. The whole
    batch is one loader invocation. A timed-out loader is treated
    the same as a "loader returned None / empty" miss: no cache
    write; return whatever was already cached (or `{}`).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> Dict[str, str] | None:
            calls.append(1)
            return {"f1": "v1", "f2": "v2"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=loader,
        )
        assert result == {"f1": "v1", "f2": "v2"}
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> Dict[str, str] | None:
            time.sleep(0.05)
            return {"f1": "v1", "f2": "v2"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == {"f1": "v1", "f2": "v2"}

    def test_loader_exceeds_timeout_returns_empty(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Batch-special: loader exceeds timeout → return `{}` (no
        partial hit because the cache was empty), no cache write."""
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> Dict[str, str] | None:
            calls.append(1)
            time.sleep(0.3)
            return {"f1": "v1", "f2": "v2"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result == {}
        assert calls == [1]
        # No cache write.
        assert manager.get(unique_key, "f1", str) is None

    def test_loader_within_timeout_partial_hit_writes_back(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """Batch-special: partial hit + loader returns the rest →
        both halves end up in the cache."""
        manager = registrar.field_ops()
        # Pre-cache f1.
        manager.set(unique_key, "f1", "cached-v1")

        def loader() -> Dict[str, str] | None:
            return {"f2": "loaded-v2"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == {"f1": "cached-v1", "f2": "loaded-v2"}
        # The loader's value was written back.
        assert manager.get(unique_key, "f2", str) == "loaded-v2"

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        class LoaderError(RuntimeError):
            pass

        def loader() -> Dict[str, str] | None:
            raise LoaderError("batch-fail")

        with pytest.raises(LoaderError, match="batch-fail"):
            manager.get_many_with_lock(
                unique_key, ["f1", "f2"], str,
                timeout_millis=10_000, db_loader=loader,
                loader_timeout_millis=1_000,
            )

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_many_with_lock(
                unique_key, ["f1", "f2"], str,
                timeout_millis=10_000, db_loader=lambda: {},
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_many_with_lock(
                unique_key, ["f1", "f2"], str,
                timeout_millis=10_000, db_loader=lambda: {},
                loader_timeout_millis=-50,
            )

    def test_cache_full_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        manager.set(unique_key, "f1", "v1")
        manager.set(unique_key, "f2", "v2")
        calls: List[int] = []

        def loader() -> Dict[str, str] | None:
            calls.append(1)
            time.sleep(5.0)
            return {"f1": "would-block", "f2": "would-block"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=100,
        )
        assert result == {"f1": "v1", "f2": "v2"}
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def slow_loader() -> Dict[str, str] | None:
            time.sleep(0.2)
            return {"f1": "v1"}

        r1 = manager.get_many_with_lock(
            unique_key, ["f1"], str,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert r1 == {}

        def fast_loader() -> Dict[str, str] | None:
            return {"f1": "fast"}

        r2 = manager.get_many_with_lock(
            unique_key, ["f1"], str,
            timeout_millis=5_000, db_loader=fast_loader,
        )
        assert r2 == {"f1": "fast"}

    def test_hash_function_alias_accepts_kwarg(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """The `HashFunction.get_many_with_lock` alias is the same
        method (FieldOps + HashFunction both expose it) and accepts
        the new kwarg as expected."""
        manager = registrar.hash_function()

        def slow_loader() -> Dict[str, str] | None:
            time.sleep(0.2)
            return {"f1": "v1"}

        result = manager.get_many_with_lock(
            unique_key, ["f1"], str,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert result == {}

    def test_concurrent_callers_with_timeouts_funnel(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
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
            return {"f1": "v1"}

        results: List[Dict[str, str]] = []
        results_lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            r = manager.get_many_with_lock(
                unique_key, ["f1"], str,
                timeout_millis=5_000, db_loader=loader,
                loader_timeout_millis=50,
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        # All callers see {} (timeout) — the losers never run a loader.
        assert all(r == {} for r in results), (
            f"some threads got non-empty results: {results!r}"
        )
        assert call_count == 1, (
            f"expected exactly 1 loader call (winner), got {call_count}"
        )
