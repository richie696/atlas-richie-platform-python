"""Real-Redis negative-cache tests for `RedisFieldManager` (M5.7).

Covers the new `negative_cache_ttl_millis` keyword argument on the
six `*_with_lock` methods of `RedisFieldManager`:

- `FieldOps.get_with_lock`
- `FieldOps.get_with_lock_typed`
- `FieldOps.get_many_with_lock`
- `HashFunction.get_object_from_hash_with_lock`
- `HashFunction.get_from_hash_with_lock`
- `HashFunction.get_from_hash_with_lock_typed`

For each method (or group of methods) we exercise:

1. Default behavior (no `negative_cache_ttl_millis`) is unchanged.
2. Timeout with `negative_cache_ttl_millis` → returns `None` /
   empty dict AND writes the negative-cache sentinel.
3. Subsequent call within the TTL window → returns `None` / empty
   dict immediately, no loader call.
4. After TTL expiry → loader is called again on the next miss.
5. `negative_cache_ttl_millis=0` / negative → `ValueError`.
6. Natural `None` / empty dict from the loader is NOT a negative
   cache (no marker written).
7. For the batch `get_many_with_lock`: TIMEOUT writes a marker
   to every missing field, not just one.

The Redis URL is configurable via `ATLAS_RICHIE_CACHE_REDIS_URL`.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, Iterator, List

import pytest

from atlas_richie.cache_redis import RedisProviderRegistrar
from atlas_richie.cache_redis.managers.redis_string_manager import (
    _NEGATIVE_SENTINEL,
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
    return f"neg-cache:field:{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _cleanup(
    registrar: RedisProviderRegistrar, unique_key: str
) -> Iterator[None]:
    """Wipe the hash + stampede-lock keys for `unique_key` before
    and after each test."""
    client = registrar._backend.raw_client()
    full_key = registrar._backend.make_key(unique_key)
    client.delete(full_key)
    for i in range(1, 10):
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
    client.delete(full_key)
    for i in range(1, 10):
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
# 1. get_with_lock (FieldOps) — single field
# ══════════════════════════════════════════════════════════════════


class TestGetWithLockNegativeCache:
    """`FieldOps.get_with_lock` + `negative_cache_ttl_millis` (M5.7)."""

    def test_default_no_marker_when_timeout_fires(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        """M5.7 is opt-in: without `negative_cache_ttl_millis`,
        a timed-out loader writes no entry, exactly as M5.1."""
        manager = registrar.field_ops()
        calls: List[int] = []

        def loader() -> str | None:
            calls.append(1)
            time.sleep(0.2)
            return "v"

        result = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
        )
        assert result is None
        assert calls == [1]
        # No cache entry.
        assert manager.get(unique_key, "f1", str) is None

    def test_timeout_writes_negative_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> str | None:
            time.sleep(0.2)
            return "v"

        result = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        # Raw bytes are the negative sentinel.
        raw = registrar._backend.raw_client().hget(
            registrar._backend.make_key(unique_key), "f1"
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_subsequent_call_within_ttl_uses_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def slow() -> str | None:
            calls.append(1)
            time.sleep(0.2)
            return "v"

        def fast() -> str | None:
            calls.append(1)
            return "fast"

        first = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        second = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second is None
        assert calls == [1], "negative marker must short-circuit loader"

    def test_loader_called_again_after_ttl_expiry(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def slow() -> str | None:
            calls.append(1)
            time.sleep(0.2)
            return "v"

        first = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=200,
        )
        assert first is None
        time.sleep(0.3)

        def fast() -> str | None:
            calls.append(1)
            return "now"

        second = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=fast,
        )
        assert second == "now"
        assert len(calls) == 2

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_with_lock(
                unique_key, "f1", str,
                timeout_millis=10_000, db_loader=lambda: "x",
                negative_cache_ttl_millis=0,
            )

    def test_negative_cache_ttl_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_with_lock(
                unique_key, "f1", str,
                timeout_millis=10_000, db_loader=lambda: "x",
                negative_cache_ttl_millis=-1,
            )

    def test_natural_none_does_not_write_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def returns_none() -> str | None:
            calls.append(1)
            return None

        first = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=returns_none,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        assert calls == [1]
        # No marker — next call re-runs the loader.
        def returns_value() -> str | None:
            calls.append(1)
            return "v"

        second = manager.get_with_lock(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=returns_value,
        )
        assert second == "v"
        assert len(calls) == 2


# ══════════════════════════════════════════════════════════════════
# 2. get_with_lock_typed (FieldOps) — single field, typed read
# ══════════════════════════════════════════════════════════════════


class TestGetWithLockTypedNegativeCache:
    """`FieldOps.get_with_lock_typed` honours the same kwarg."""

    def test_timeout_writes_marker_for_typed(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> str | None:
            time.sleep(0.2)
            return "v"

        result = manager.get_with_lock_typed(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        raw = registrar._backend.raw_client().hget(
            registrar._backend.make_key(unique_key), "f1"
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_subsequent_typed_call_uses_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def slow() -> str | None:
            calls.append(1)
            time.sleep(0.2)
            return "v"

        def fast() -> str | None:
            calls.append(1)
            return "v"

        first = manager.get_with_lock_typed(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        second = manager.get_with_lock_typed(
            unique_key, "f1", str,
            timeout_millis=10_000, db_loader=fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second is None
        assert calls == [1]


# ══════════════════════════════════════════════════════════════════
# 3. get_object_from_hash_with_lock (HashFunction) — whole object
# ══════════════════════════════════════════════════════════════════


class TestGetObjectFromHashWithLockNegativeCache:
    """`HashFunction.get_object_from_hash_with_lock` honours the kwarg."""

    def test_timeout_writes_marker_for_object(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> Any:
            time.sleep(0.2)
            return {"k": "v"}

        result = manager.get_object_from_hash_with_lock(
            unique_key, dict,
            db_loader=loader,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        # _OBJECT_FIELD reserved key holds the sentinel.
        from atlas_richie.cache_redis.managers.redis_field_manager import (
            _OBJECT_FIELD,
        )

        raw = registrar._backend.raw_client().hget(
            registrar._backend.make_key(unique_key), _OBJECT_FIELD
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_subsequent_object_call_uses_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def slow() -> Any:
            calls.append(1)
            time.sleep(0.2)
            return {"k": "v"}

        def fast() -> Any:
            calls.append(1)
            return {"k": "v"}

        first = manager.get_object_from_hash_with_lock(
            unique_key, dict,
            db_loader=slow,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first is None
        second = manager.get_object_from_hash_with_lock(
            unique_key, dict,
            db_loader=fast,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second is None
        assert calls == [1]


# ══════════════════════════════════════════════════════════════════
# 4. get_from_hash_with_lock + get_from_hash_with_lock_typed
# ══════════════════════════════════════════════════════════════════


class TestGetFromHashWithLockNegativeCache:
    """`HashFunction` single-field aliases honour the kwarg."""

    def test_timeout_writes_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> str | None:
            time.sleep(0.2)
            return "v"

        result = manager.get_from_hash_with_lock(
            unique_key, "f1", str,
            db_loader=loader,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        raw = registrar._backend.raw_client().hget(
            registrar._backend.make_key(unique_key), "f1"
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_typed_alias_writes_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> str | None:
            time.sleep(0.2)
            return "v"

        result = manager.get_from_hash_with_lock_typed(
            unique_key, "f1", str,
            db_loader=loader,
            timeout_millis=10_000,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result is None
        raw = registrar._backend.raw_client().hget(
            registrar._backend.make_key(unique_key), "f1"
        )
        assert raw == _NEGATIVE_SENTINEL_STR

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_from_hash_with_lock(
                unique_key, "f1", str,
                db_loader=lambda: "v",
                timeout_millis=10_000,
                negative_cache_ttl_millis=0,
            )


# ══════════════════════════════════════════════════════════════════
# 5. get_many_with_lock (FieldOps) — batch
# ══════════════════════════════════════════════════════════════════


class TestGetManyWithLockNegativeCache:
    """`FieldOps.get_many_with_lock` + `negative_cache_ttl_millis`.

    On TIMEOUT the negative marker must be written to every
    originally-missing field, not just one.
    """

    def test_timeout_writes_marker_to_each_missing_field(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()

        def loader() -> Dict[str, str]:
            time.sleep(0.2)
            return {"f1": "a", "f2": "b", "f3": "c"}

        result = manager.get_many_with_lock(
            unique_key, ["f1", "f2", "f3"], str,
            timeout_millis=10_000, db_loader=loader,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert result == {}
        # Every field now holds the sentinel.
        client = registrar._backend.raw_client()
        for f in ("f1", "f2", "f3"):
            raw = client.hget(
                registrar._backend.make_key(unique_key), f
            )
            assert raw == _NEGATIVE_SENTINEL_STR, f"field {f} missing marker"

    def test_subsequent_call_within_ttl_returns_empty(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def slow() -> Dict[str, str]:
            calls.append(1)
            time.sleep(0.2)
            return {"f1": "a", "f2": "b"}

        def fast() -> Dict[str, str]:
            calls.append(1)
            return {"f1": "a", "f2": "b"}

        first = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=slow,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert first == {}
        second = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=fast,
            loader_timeout_millis=50,
            negative_cache_ttl_millis=5_000,
        )
        assert second == {}
        assert calls == [1]

    def test_natural_empty_dict_does_not_write_marker(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        calls: List[int] = []

        def returns_empty() -> Dict[str, str]:
            calls.append(1)
            return {}

        first = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=returns_empty,
            negative_cache_ttl_millis=5_000,
        )
        assert first == {}
        assert calls == [1]
        # No marker — next call re-runs.
        def returns_real() -> Dict[str, str]:
            calls.append(1)
            return {"f1": "a", "f2": "b"}

        second = manager.get_many_with_lock(
            unique_key, ["f1", "f2"], str,
            timeout_millis=10_000, db_loader=returns_real,
        )
        assert second == {"f1": "a", "f2": "b"}
        assert len(calls) == 2

    def test_negative_cache_ttl_zero_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_many_with_lock(
                unique_key, ["f1"], str,
                timeout_millis=10_000, db_loader=lambda: {},
                negative_cache_ttl_millis=0,
            )

    def test_negative_cache_ttl_negative_raises(
        self, registrar: RedisProviderRegistrar, unique_key: str
    ) -> None:
        manager = registrar.field_ops()
        with pytest.raises(ValueError, match="negative_cache_ttl_millis"):
            manager.get_many_with_lock(
                unique_key, ["f1"], str,
                timeout_millis=10_000, db_loader=lambda: {},
                negative_cache_ttl_millis=-10,
            )
