"""Real-Redis smoke test for `RedisFieldManager` (R-220 M2 + M4).

Validates that the new `RedisFieldManager` correctly implements both
`FieldOps` and `HashFunction` end-to-end against a real Redis 8.x
instance, including:

- Single-field set / get / get_typed / exists.
- Atomic Hash counters (HINCRBY / HINCRBYFLOAT).
- Multi-field set_all / get_all / get_many_typed / get_many.
- Meta: get_fields, size, remove.
- Batch set across many Hashes.
- Anti-avalanche TTL on the high-level `set(key, field, value, timeout_millis)`.

The M4 stampede-prevention suite lives in
`test_redis_field_manager_with_lock.py`.

Test namespace is unique per run so parallel runs cannot collide;
teardown SCAN-iterates and `DEL`s the test namespace.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    ConfigurationError,
    RedisFieldManager,
    RedisProviderRegistrar,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    """Build a registrar with a unique test namespace."""
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-220-M2-Field:{uuid.uuid4().hex[:8]}"
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
def manager(registrar: RedisProviderRegistrar) -> RedisFieldManager:
    return registrar.field_ops()


# ── FieldOps (low-level) ─────────────────────────────────────────────


class TestFieldOpsSingleField:
    def test_set_get_round_trip_string(self, manager: RedisFieldManager) -> None:
        manager.set("user:42", "name", "richie")
        assert manager.get("user:42", "name", str) == "richie"

    def test_set_get_round_trip_int(self, manager: RedisFieldManager) -> None:
        manager.set("user:42", "age", 42)
        assert manager.get("user:42", "age", int) == 42

    def test_set_get_round_trip_dict(self, manager: RedisFieldManager) -> None:
        payload = {"city": "shenzhen", "tags": ["a", "b"]}
        manager.set("user:42", "profile", payload)
        assert manager.get("user:42", "profile", dict) == payload

    def test_get_missing_returns_none(self, manager: RedisFieldManager) -> None:
        assert manager.get("user:42", "missing", str) is None

    def test_exists(self, manager: RedisFieldManager) -> None:
        manager.set("h", "f1", "v")
        assert manager.exists("h", "f1") is True
        assert manager.exists("h", "f2") is False


class TestFieldOpsAtomicCounters:
    def test_increment_default_delta(self, manager: RedisFieldManager) -> None:
        assert manager.increment("ctr", "x") == 1
        assert manager.increment("ctr", "x") == 2

    def test_increment_with_delta(self, manager: RedisFieldManager) -> None:
        assert manager.increment("ctr", "x", 5) == 5
        assert manager.increment("ctr", "x", 3) == 8

    def test_increment_by(self, manager: RedisFieldManager) -> None:
        manager.set("ctr", "x", 10)
        assert manager.increment_by("ctr", "x", 7) == 17

    def test_increment_double(self, manager: RedisFieldManager) -> None:
        manager.set("flt", "x", 1.5)
        new = manager.increment_double("flt", "x", 0.5)
        assert new == pytest.approx(2.0)

    def test_decrement_default_delta(self, manager: RedisFieldManager) -> None:
        manager.set("ctr", "x", 10)
        assert manager.decrement("ctr", "x") == 9
        assert manager.decrement("ctr", "x") == 8

    def test_decrement_by(self, manager: RedisFieldManager) -> None:
        manager.set("ctr", "x", 10)
        assert manager.decrement_by("ctr", "x", 3) == 7


class TestFieldOpsMultiField:
    def test_set_all(self, manager: RedisFieldManager) -> None:
        manager.set_all(
            "user:1",
            {"name": "alice", "age": 30, "city": "nyc"},
            timeout_millis=0,
        )
        assert manager.get("user:1", "name", str) == "alice"
        assert manager.get("user:1", "age", int) == 30
        assert manager.get("user:1", "city", str) == "nyc"

    def test_get_all(self, manager: RedisFieldManager) -> None:
        manager.set_all(
            "h",
            {"a": 1, "b": 2, "c": 3},
            timeout_millis=0,
        )
        result = manager.get_all("h", int)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_get_many_typed(self, manager: RedisFieldManager) -> None:
        manager.set_all(
            "h",
            {"a": 1, "b": 2, "c": 3},
            timeout_millis=0,
        )
        result = manager.get_many_typed("h", ["a", "b", "missing"], int)
        assert sorted(result) == [1, 2]

    def test_get_many(self, manager: RedisFieldManager) -> None:
        manager.set_all(
            "h",
            {"a": 1, "b": 2, "c": 3},
            timeout_millis=0,
        )
        result = manager.get_many("h", ["a", "b", "missing"], int)
        assert result == {"a": 1, "b": 2}

    def test_get_fields(self, manager: RedisFieldManager) -> None:
        manager.set_all("h", {"a": 1, "b": 2, "c": 3}, timeout_millis=0)
        assert manager.get_fields("h") == {"a", "b", "c"}

    def test_size(self, manager: RedisFieldManager) -> None:
        manager.set_all("h", {"a": 1, "b": 2}, timeout_millis=0)
        assert manager.size("h") == 2

    def test_remove(self, manager: RedisFieldManager) -> None:
        manager.set_all(
            "h", {"a": 1, "b": 2, "c": 3}, timeout_millis=0
        )
        manager.remove("h", "a", "c")
        assert manager.get_fields("h") == {"b"}

    def test_batch_set(self, manager: RedisFieldManager) -> None:
        manager.batch_set(
            {
                "h1": {"a": 1, "b": 2},
                "h2": {"c": 3, "d": 4},
            }
        )
        assert manager.get_all("h1", int) == {"a": 1, "b": 2}
        assert manager.get_all("h2", int) == {"c": 3, "d": 4}


# ── HashFunction (high-level) ────────────────────────────────────────


class TestHashFunctionHighLevel:
    def test_set_with_anti_avalanche_ttl(
        self, manager: RedisFieldManager
    ) -> None:
        """High-level `set(key, field, value, timeout_millis)` adds
        the anti-avalanche offset; verify the TTL exceeds the
        caller-supplied value by ≥ 60s.
        """
        manager.set("h", "f", "v", timeout_millis=500)
        raw = manager._backend.raw_client()
        # `HTTL` returns a list (one TTL per field requested).
        ptls = raw.hpttl(manager._k("h"), "f")
        # Anti-avalanche adds 60_000..600_000 ms on top of 500 ms.
        assert ptls[0] > 60_000, f"expected HPTTL > 60s, got {ptls[0]} ms"

    def test_set_without_timeout_does_not_set_ttl(
        self, manager: RedisFieldManager
    ) -> None:
        """Low-level `set(key, field, value)` (no TTL) leaves the
        Hash field without an expiry.
        """
        manager.set("h", "f", "v")
        raw = manager._backend.raw_client()
        # `HTTL` returns a list; element is -1 for "no expiry".
        httl = raw.hpttl(manager._k("h"), "f")
        assert httl[0] == -1, f"expected no expiry (-1), got {httl[0]} ms"

    def test_increment_with_delta_via_high_level(
        self, manager: RedisFieldManager
    ) -> None:
        # HashFunction.increment(key, field, delta) — merged with
        # FieldOps.increment(key, field) via default delta=1.
        manager.set("h", "x", 10)
        assert manager.increment("h", "x", 5) == 15

    def test_decrement_with_delta_via_high_level(
        self, manager: RedisFieldManager
    ) -> None:
        manager.set("h", "x", 10)
        assert manager.decrement("h", "x", 3) == 7


class TestProviderRegistrarWiring:
    def test_field_ops_returns_field_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisFieldManager

        assert isinstance(registrar.field_ops(), RedisFieldManager)

    def test_hash_function_is_field_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """`hash_function()` must return the SAME instance as
        `field_ops()` (per Java 1:1 mirror: the manager implements
        both Protocols)."""
        assert registrar.hash_function() is registrar.field_ops()
