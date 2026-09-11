"""Real-Redis negative-cache tests for the collection (Set) and
struct (object) managers (M5.7).

Covers the new `negative_cache_ttl_millis` keyword argument on:

- `CollectionOps.get_with_lock` (Set) — uses a SEPARATE Redis
  marker key (`__negative_set__:<key>`) because Sets cannot store
  a bytes sentinel via SADD.
- `SetFunction.get_from_set_with_lock` (Set alias).
- `StructOps.get_with_lock` (object).
- `StructOps.get_with_lock_typed` (object, typed).

For each method we exercise:

1. Default behavior (no `negative_cache_ttl_millis`) is unchanged.
2. Timeout with `negative_cache_ttl_millis` → returns `set()` /
   `None` AND writes the negative-cache marker.
3. Subsequent call within the TTL window → returns `set()` /
   `None` immediately, no loader call.
4. After TTL expiry → loader is called again on the next miss.
5. `negative_cache_ttl_millis=0` / negative → `ValueError`.
6. Natural `None` / `set()` from the loader is NOT a negative
   cache (no marker written).

The Redis URL is configurable via `ATLAS_RICHIE_CACHE_REDIS_URL`.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Iterator, List, Set as _PySet

import pytest

from atlas_richie.cache_redis import RedisProviderRegistrar
from atlas_richie.cache_redis.managers.redis_string_manager import (
    _NEGATIVE_SENTINEL_STR,
)

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
    return f"neg-cache:coll-struct:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(
    registrar: RedisProviderRegistrar, unique_key: str
) -> Iterator[None]:
    """Wipe the user key + the negative-set marker key + stampede
    lock keys for `unique_key` before and after each test."""
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    negative_marker_key = registrar._backend.make_key(
        f"__negative_set__:{unique_key}"
    )
    stampede_lock_key = registrar._backend.make_key(
        f"__stampede_lock__:{unique_key}"
    )
    for k in (full_key, negative_marker_key, stampede_lock_key):
        client.delete(k)
    yield
    for k in (full_key, negative_marker_key, stampede_lock_key):
        client.delete(k)


# ══════════════════════════════════════════════════════════════════
# 1. CollectionOps.get_with_lock (Set)
# ══════════════════════════════════════════════════════════════════


class TestSetGetWithLockNegativeCache:
    """`CollectionOps.get_with_lock` + `negative_cache_ttl_millis`.

    Negative markers are stored in a separate Redis key
    (`__negative_set__:<key>`) because Set members cannot be used
    as markers.
    """

    def test_default_no_marker_when_timeout_fires(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def loader() -> _PySet[str] | None:
            calls.append(1)
            time.sleep(0.2)
            return {"a", "b"}

        result = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result == set()
        assert calls == [1]
        # No marker written (opt-in).
        client = registrar._backend.raw_client()
        marker_key = registrar._backend.make_key(
            f"__negative_set__:{unique_key}"
        )
        assert client.exists(marker_key) == 0

    def test_timeout_writes_negative_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        def loader() -> _PySet[str] | None:
            time.sleep(0.2)
            return {"a"}

        result = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result == set()
        # The separate marker key now exists.
        client = registrar._backend.raw_client()
        marker_key = registrar._backend.make_key(
            f"__negative_set__:{unique_key}"
        )
        assert client.exists(marker_key) == 1

    def test_subsequent_call_within_ttl_uses_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def slow() -> _PySet[str] | None:
            calls.append(1)
            time.sleep(0.2)
            return {"a"}

        def fast() -> _PySet[str] | None:
            calls.append(1)
            return {"a", "b"}

        first = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first == set()
        second = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second == set()
        assert calls == [1], "negative marker must short-circuit loader"

    def test_loader_called_again_after_ttl_expiry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def slow() -> _PySet[str] | None:
            calls.append(1)
            time.sleep(0.2)
            return {"a"}

        first = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=200,
        )
        assert first == set()
        time.sleep(0.3)

        def fast() -> _PySet[str] | None:
            calls.append(1)
            return {"a", "b"}

        second = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=fast,
        )
        assert second == {"a", "b"}
        assert len(calls) == 2

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_with_lock(
                unique_key, str,
                timeout_millis=10_000, db_loader=lambda: set(),
                negative_cache_ttl_millis=0,
            )

    def test_negative_cache_ttl_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_with_lock(
                unique_key, str,
                timeout_millis=10_000, db_loader=lambda: set(),
                negative_cache_ttl_millis=-5,
            )

    def test_natural_empty_set_does_not_write_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def returns_empty() -> _PySet[str] | None:
            calls.append(1)
            return set()

        first = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=returns_empty,
            negative_cache_ttl_millis=5_000,
        )
        assert first == set()
        assert calls == [1]
        # No marker — next call re-runs the loader.
        client = registrar._backend.raw_client()
        marker_key = registrar._backend.make_key(
            f"__negative_set__:{unique_key}"
        )
        assert client.exists(marker_key) == 0

        def returns_value() -> _PySet[str] | None:
            calls.append(1)
            return {"a"}

        second = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=returns_value,
        )
        assert second == {"a"}
        assert len(calls) == 2

    def test_successful_publish_clears_stale_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """If a previous timeout wrote a negative marker but the
        next call (after the marker TTL has expired) loads
        successfully, the marker must be cleared so future
        callers don't see a stale "negative" state."""
        manager = registrar.collection_ops()
        client = registrar._backend.raw_client()
        marker_key = registrar._backend.make_key(
            f"__negative_set__:{unique_key}"
        )
        calls: List[int] = []

        def slow() -> _PySet[str] | None:
            calls.append(1)
            time.sleep(0.2)
            return {"a"}

        # First call writes a marker with a 200ms TTL.
        first = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=200,
        )
        assert first == set()
        assert client.exists(marker_key) == 1

        # Let the marker TTL expire.
        time.sleep(0.3)
        assert client.exists(marker_key) == 0

        def fast() -> _PySet[str] | None:
            calls.append(1)
            return {"a", "b"}

        second = manager.get_with_lock(
            unique_key, str,
            timeout_millis=10_000, db_loader=fast,
        )
        assert second == {"a", "b"}
        # Successful publish: marker was DEL'd proactively.
        assert client.exists(marker_key) == 0
        assert len(calls) == 2


# ══════════════════════════════════════════════════════════════════
# 2. SetFunction.get_from_set_with_lock (Set alias)
# ══════════════════════════════════════════════════════════════════


class TestGetFromSetWithLockNegativeCache:
    """`SetFunction.get_from_set_with_lock` honours the kwarg."""

    def test_timeout_writes_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()

        def loader() -> _PySet[str] | None:
            time.sleep(0.2)
            return {"a"}

        result = manager.get_from_set_with_lock(
            unique_key, str,
            db_loader=loader,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result == set()
        marker_key = registrar._backend.make_key(
            f"__negative_set__:{unique_key}"
        )
        assert (
            registrar._backend.raw_client().exists(marker_key) == 1
        )

    def test_subsequent_call_uses_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        calls: List[int] = []

        def slow() -> _PySet[str] | None:
            calls.append(1)
            time.sleep(0.2)
            return {"a"}

        def fast() -> _PySet[str] | None:
            calls.append(1)
            return {"a"}

        first = manager.get_from_set_with_lock(
            unique_key, str,
            db_loader=slow,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first == set()
        second = manager.get_from_set_with_lock(
            unique_key, str,
            db_loader=fast,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second == set()
        assert calls == [1]

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.collection_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_from_set_with_lock(
                unique_key, str,
                db_loader=lambda: set(),
                timeout_millis=10_000,
                negative_cache_ttl_millis=0,
            )


# ══════════════════════════════════════════════════════════════════
# 3. StructOps.get_with_lock + get_with_lock_typed (object)
# ══════════════════════════════════════════════════════════════════


class TestStructGetWithLockNegativeCache:
    """`StructOps.get_with_lock` + `get_with_lock_typed` honour
    the kwarg with the standard bytes-sentinel encoding."""

    def test_timeout_writes_marker_for_struct(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        from atlas_richie.cache_redis.managers.redis_string_manager import (
            _NEGATIVE_SENTINEL_STR,
        )

        def loader() -> Any:
            time.sleep(0.2)
            return {"k": "v"}

        result = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_subsequent_struct_call_uses_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def slow() -> Any:
            calls.append(1)
            time.sleep(0.2)
            return {"k": "v"}

        def fast() -> Any:
            calls.append(1)
            return {"k": "v"}

        first = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        second = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second is None
        assert calls == [1]

    def test_timeout_writes_marker_for_typed(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        from atlas_richie.cache_redis.managers.redis_string_manager import (
            _NEGATIVE_SENTINEL_STR,
        )

        def loader() -> Any:
            time.sleep(0.2)
            return {"k": "v"}

        result = manager.get_with_lock_typed(
            unique_key, dict,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_with_lock(
                unique_key, dict,
                timeout_millis=10_000, db_loader=lambda: {"k": "v"},
                negative_cache_ttl_millis=0,
            )

    def test_negative_cache_ttl_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_with_lock(
                unique_key, dict,
                timeout_millis=10_000, db_loader=lambda: {"k": "v"},
                negative_cache_ttl_millis=-7,
            )

    def test_natural_none_does_not_write_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        from atlas_richie.cache_redis.managers.redis_string_manager import (
            _NEGATIVE_SENTINEL_STR,
        )

        calls: List[int] = []

        def returns_none() -> Any:
            calls.append(1)
            return None

        first = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=returns_none,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        assert calls == [1]
        # No marker.
        raw = registrar._backend.raw_client().get(
            registrar._backend.make_key(unique_key)
        )
        assert raw != _NEGATIVE_SENTINEL_STR
        assert raw is None

        def returns_real() -> Any:
            calls.append(1)
            return {"k": "v"}

        second = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=returns_real,
        )
        assert second == {"k": "v"}
        assert len(calls) == 2

    def test_loader_called_again_after_ttl_expiry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.struct_ops()
        calls: List[int] = []

        def slow() -> Any:
            calls.append(1)
            time.sleep(0.2)
            return {"k": "v"}

        first = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=200,
        )
        assert first is None
        time.sleep(0.3)

        def fast() -> Any:
            calls.append(1)
            return {"k": "v"}

        second = manager.get_with_lock(
            unique_key, dict,
            timeout_millis=10_000, db_loader=fast,
        )
        assert second == {"k": "v"}
        assert len(calls) == 2
