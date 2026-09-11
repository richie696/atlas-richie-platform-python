"""Real-Redis loader-timeout tests for `RedisCollectionManager` and
`RedisStructManager` (M5.1).

Covers the new `loader_timeout_millis` keyword argument on the four
`*_with_lock` methods:

- `CollectionOps.get_with_lock(key, clazz, timeout_millis, db_loader)`
- `SetFunction.get_from_set_with_lock(key, reference, db_loader, timeout_millis)`
- `StructOps.get_with_lock(key, clazz, timeout_millis, db_loader)`
- `StructOps.get_with_lock_typed(key, reference, timeout_millis, db_loader)`

For each method we exercise the same 8 standard cases that the
String sample uses (see `test_redis_string_manager_loader_timeout.py`):

1. `loader_timeout_millis=None` preserves the legacy (unbounded) behavior.
2. Loader finishes within the timeout → return value, cache populated.
3. Loader exceeds the timeout → return `None` (or empty Set), no
   cache write, no exception.
4. Loader raises → exception propagates, lock released.
5. `loader_timeout_millis=0` → `ValueError`.
6. `loader_timeout_millis<0` → `ValueError`.
7. Cache-hit path unaffected by `loader_timeout_millis`.
8. After a timed-out loader call, the next call (with a new
   `db_loader`) is NOT affected — the stampede lock was released.

The 4 methods each have 8 standard cases (32 total) — matching the
spec for `test_redis_collection_struct_loader_timeout.py`.

The Redis URL is configurable via `ATLAS_RICHIE_CACHE_REDIS_URL`.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Iterator, List, Set

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
    return f"timeout:cs:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(
    registrar: RedisProviderRegistrar, unique_key: str
) -> Iterator[None]:
    """Wipe cache + per-key stampede lock before AND after each test."""
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    lock_key = registrar._backend.make_key(
        f"__stampede_lock__:{unique_key}"
    )
    client.delete(full_key, lock_key)
    yield
    client.delete(full_key, lock_key)


# ══════════════════════════════════════════════════════════════════
# 1. CollectionOps.get_with_lock  (Set, low-level)
# ══════════════════════════════════════════════════════════════════


class TestCollectionOpsGetWithLockLoaderTimeout:
    """`CollectionOps.get_with_lock(key, clazz, timeout_millis, db_loader)`
    + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def loader() -> Set[str] | None:
            calls.append(1)
            return {"a", "b"}

        result = manager.get_with_lock(
            unique_key, str, timeout_millis=10_000, db_loader=loader
        )
        assert result == {"a", "b"}
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        def loader() -> Set[str] | None:
            time.sleep(0.05)
            return {"a", "b"}

        result = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == {"a", "b"}
        assert manager.get(unique_key, str) == {"a", "b"}

    def test_loader_exceeds_timeout_returns_empty(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def loader() -> Set[str] | None:
            calls.append(1)
            time.sleep(0.3)
            return {"a", "b"}

        result = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result == set()
        assert calls == [1]
        # No cache write.
        assert manager.get(unique_key, str) == set()

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        class LoaderError(RuntimeError):
            pass

        def loader() -> Set[str] | None:
            raise LoaderError("set-fail")

        with pytest.raises(LoaderError, match="set-fail"):
            manager.get_with_lock(
                unique_key, str,
                timeout_millis=10_000, db_loader=loader,
                loader_timeout_millis=1_000,
            )
        # Lock must be released.
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock(
                unique_key, str,
                timeout_millis=10_000, db_loader=lambda: set(),
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock(
                unique_key, str,
                timeout_millis=10_000, db_loader=lambda: set(),
                loader_timeout_millis=-100,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        manager.add_set(unique_key, {"preset"})
        calls: List[int] = []

        def loader() -> Set[str] | None:
            calls.append(1)
            time.sleep(5.0)
            return {"fresh"}

        result = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=100,
        )
        assert result == {"preset"}
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        def slow_loader() -> Set[str] | None:
            time.sleep(0.2)
            return {"slow"}

        r1 = manager.get_with_lock(
            unique_key, str,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert r1 == set()

        def fast_loader() -> Set[str] | None:
            return {"fast"}

        r2 = manager.get_with_lock(
            unique_key, str,
            timeout_millis=5_000, db_loader=fast_loader,
        )
        assert r2 == {"fast"}


# ══════════════════════════════════════════════════════════════════
# 2. SetFunction.get_from_set_with_lock  (Set, business-facing)
# ══════════════════════════════════════════════════════════════════


class TestGetFromSetWithLockLoaderTimeout:
    """`SetFunction.get_from_set_with_lock(key, reference, db_loader,
    timeout_millis)` + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        calls: List[int] = []

        def loader() -> Set[str] | None:
            calls.append(1)
            return {"x", "y"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 10_000
        )
        assert result == {"x", "y"}
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()

        def loader() -> Set[str] | None:
            time.sleep(0.05)
            return {"x", "y"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 10_000,
            loader_timeout_millis=500,
        )
        assert result == {"x", "y"}
        assert manager.get(unique_key, str) == {"x", "y"}

    def test_loader_exceeds_timeout_returns_empty(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        calls: List[int] = []

        def loader() -> Set[str] | None:
            calls.append(1)
            time.sleep(0.3)
            return {"x"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 10_000,
            loader_timeout_millis=50,
        )
        assert result == set()
        assert calls == [1]
        # No cache write.
        assert manager.get(unique_key, str) == set()

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()

        class LoaderError(RuntimeError):
            pass

        def loader() -> Set[str] | None:
            raise LoaderError("from-set-fail")

        with pytest.raises(LoaderError, match="from-set-fail"):
            manager.get_from_set_with_lock(
                unique_key, str, loader, 10_000,
                loader_timeout_millis=1_000,
            )
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_from_set_with_lock(
                unique_key, str, lambda: set(), 10_000,
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_from_set_with_lock(
                unique_key, str, lambda: set(), 10_000,
                loader_timeout_millis=-50,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()
        manager.add_set(unique_key, {"preset"})
        calls: List[int] = []

        def loader() -> Set[str] | None:
            calls.append(1)
            time.sleep(5.0)
            return {"fresh"}

        result = manager.get_from_set_with_lock(
            unique_key, str, loader, 10_000,
            loader_timeout_millis=100,
        )
        assert result == {"preset"}
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.set_function()

        def slow_loader() -> Set[str] | None:
            time.sleep(0.2)
            return {"slow"}

        r1 = manager.get_from_set_with_lock(
            unique_key, str, slow_loader, 5_000,
            loader_timeout_millis=20,
        )
        assert r1 == set()

        def fast_loader() -> Set[str] | None:
            return {"fast"}

        r2 = manager.get_from_set_with_lock(
            unique_key, str, fast_loader, 5_000,
        )
        assert r2 == {"fast"}


# ══════════════════════════════════════════════════════════════════
# 3. StructOps.get_with_lock  (struct / object, low-level)
# ══════════════════════════════════════════════════════════════════


class TestStructGetWithLockLoaderTimeout:
    """`StructOps.get_with_lock(key, clazz, timeout_millis, db_loader)`
    + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            return {"k": "v"}

        result = manager.get_with_lock(
            unique_key, dict, timeout_millis=10_000, db_loader=loader
        )
        assert result == {"k": "v"}
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def loader() -> Any:
            time.sleep(0.05)
            return {"k": "v"}

        result = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == {"k": "v"}
        assert manager.get(unique_key, dict) == {"k": "v"}

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            time.sleep(0.3)
            return {"k": "v"}

        result = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]
        # No cache write.
        assert manager.get(unique_key, dict) is None

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        class LoaderError(RuntimeError):
            pass

        def loader() -> Any:
            raise LoaderError("struct-fail")

        with pytest.raises(LoaderError, match="struct-fail"):
            manager.get_with_lock(
                unique_key, dict,
                timeout_millis=10_000, db_loader=loader,
                loader_timeout_millis=1_000,
            )
        lock_key = registrar._backend.make_key(
            f"__stampede_lock__:{unique_key}"
        )
        assert registrar._backend.raw_client().get(lock_key) is None

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock(
                unique_key, dict,
                timeout_millis=10_000, db_loader=lambda: {},
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock(
                unique_key, dict,
                timeout_millis=10_000, db_loader=lambda: {},
                loader_timeout_millis=-100,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        manager.set(unique_key, {"preset": True})
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            time.sleep(5.0)
            return {"fresh": True}

        result = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=100,
        )
        assert result == {"preset": True}
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def slow_loader() -> Any:
            time.sleep(0.2)
            return {"x": 1}

        r1 = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> Any:
            return {"y": 2}

        r2 = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=5_000, db_loader=fast_loader,
        )
        assert r2 == {"y": 2}


# ══════════════════════════════════════════════════════════════════
# 4. StructOps.get_with_lock_typed  (struct / object, typed)
# ══════════════════════════════════════════════════════════════════


class TestStructGetWithLockTypedLoaderTimeout:
    """`StructOps.get_with_lock_typed(key, reference, timeout_millis,
    db_loader)` + `loader_timeout_millis` (M5.1).
    """

    def test_loader_timeout_none_unbounded(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            return {"a": 1}

        result = manager.get_with_lock_typed(
            unique_key, dict, timeout_millis=10_000, db_loader=loader
        )
        assert result == {"a": 1}
        assert calls == [1]

    def test_loader_within_timeout_succeeds(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def loader() -> Any:
            time.sleep(0.05)
            return {"a": 1}

        result = manager.get_with_lock_typed(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=500,
        )
        assert result == {"a": 1}

    def test_loader_exceeds_timeout_returns_none(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            time.sleep(0.3)
            return {"a": 1}

        result = manager.get_with_lock_typed(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]
        assert manager.get(unique_key, dict) is None

    def test_loader_exception_propagates(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        class LoaderError(RuntimeError):
            pass

        def loader() -> Any:
            raise LoaderError("typed-struct-fail")

        with pytest.raises(LoaderError, match="typed-struct-fail"):
            manager.get_with_lock_typed(
                unique_key, dict,
                timeout_millis=10_000, db_loader=loader,
                loader_timeout_millis=1_000,
            )

    def test_loader_timeout_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, dict,
                timeout_millis=10_000, db_loader=lambda: {},
                loader_timeout_millis=0,
            )

    def test_loader_timeout_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="loader_timeout_millis"):
            manager.get_with_lock_typed(
                unique_key, dict,
                timeout_millis=10_000, db_loader=lambda: {},
                loader_timeout_millis=-1,
            )

    def test_cache_hit_skips_loader_even_with_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        manager.set(unique_key, {"preset": 1})
        calls: List[int] = []

        def loader() -> Any:
            calls.append(1)
            time.sleep(5.0)
            return {"fresh": 1}

        result = manager.get_with_lock_typed(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=100,
        )
        assert result == {"preset": 1}
        assert calls == []

    def test_lock_released_after_timeout(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()

        def slow_loader() -> Any:
            time.sleep(0.2)
            return {"x": 1}

        r1 = manager.get_with_lock_typed(
            unique_key, dict,
            timeout_millis=5_000, db_loader=slow_loader,
            loader_timeout_millis=20,
        )
        assert r1 is None

        def fast_loader() -> Any:
            return {"y": 2}

        r2 = manager.get_with_lock_typed(
            unique_key, dict,
            timeout_millis=5_000, db_loader=fast_loader,
        )
        assert r2 == {"y": 2}
