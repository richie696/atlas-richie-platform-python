"""Tests for the R-223 `L2DistributedCache` (L1 + L2 cache-aside).

Coverage:
  - basic set / get round-trip
  - L1 hit does not touch L2
  - L1 miss falls through to L2 and read-throughs to L1
  - delete removes from both L1 and L2
  - invalidate_l1 keeps L2 intact
  - stats: hits / misses / l1_size counters
  - same config returns same instance (factory caching)
  - different config returns different instance
  - LRU eviction respects max_size
  - TTL on set propagates to L2 (L1 manual expiry tracking)
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    L2CacheFactory,
    L2DistributedCache,
    RedisProviderRegistrar,
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
    namespace = f"R-223-E2E:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    # Each test gets a fresh namespace → L1 region → no L1 cross-test
    # contamination. L2 keys are also namespaced, so no Redis cross-test
    # contamination. No factory clear needed.
    try:
        yield reg
    finally:
        reg.close()


class TestL2DistributedCache:
    def test_set_get_round_trip(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1: L2DistributedCache = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("k1", b"v1")
        assert l1.get("k1") == b"v1"
        print("  ✅ set/get round-trip")

    def test_l1_hit_does_not_touch_l2(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("k", b"v")
        # Drop L2 by deleting the Redis key directly.
        registrar.key_ops().remove_cache("k")
        # The L1 cache still has it.
        assert l1.get("k") == b"v"
        s = l1.stats()
        assert s["hits"] == 1
        assert s["misses"] == 0
        print("  ✅ L1 hit without L2")

    def test_l1_miss_falls_through_to_l2(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        # Write directly to L2 (bypassing L1).
        registrar.value_ops().set_with_ttl("k", b"from-l2", 60_000)
        # First get: L1 miss → L2 hit → read-through to L1.
        assert l1.get("k") == b"from-l2"
        s1 = l1.stats()
        assert s1["misses"] == 1
        # Second get: L1 hit (read-through promoted it).
        assert l1.get("k") == b"from-l2"
        s2 = l1.stats()
        assert s2["hits"] == 1
        print("  ✅ L1 miss → L2 → read-through to L1")

    def test_get_missing_returns_none(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        assert l1.get("never-set") is None
        print("  ✅ get(missing) → None")

    def test_delete_removes_both(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("k", b"v")
        l1.delete("k")
        assert l1.get("k") is None
        # L2 also gone.
        assert registrar.value_ops().get("k", bytes) is None
        print("  ✅ delete() removes from both L1 and L2")

    def test_invalidate_l1_keeps_l2(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("k", b"v")
        # L2 has the value too.
        assert registrar.value_ops().get("k", bytes) == b"v"
        # Drop L1 only.
        l1.invalidate_l1("k")
        # L2 still has the value.
        assert registrar.value_ops().get("k", bytes) == b"v"
        # Get: L1 miss → L2 hit → read-through to L1 (still 1 miss,
        # 0 hits — the same get is the miss).
        assert l1.get("k") == b"v"
        s = l1.stats()
        assert s["misses"] == 1
        assert s["hits"] == 0
        # Second get: L1 hit (now warmed up).
        assert l1.get("k") == b"v"
        s2 = l1.stats()
        assert s2["hits"] == 1
        print("  ✅ invalidate_l1() keeps L2 intact")

    def test_stats_initial(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        s = l1.stats()
        assert s["hits"] == 0
        assert s["misses"] == 0
        assert s["l1_size"] == 0
        assert s["max_size"] == 10
        print("  ✅ stats() initial state")

    def test_stats_accumulate(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("a", b"1")
        l1.set("b", b"2")
        l1.get("a")  # hit
        l1.get("a")  # hit
        l1.get("c")  # miss
        s = l1.stats()
        assert s["hits"] == 2
        assert s["misses"] == 1
        assert s["l1_size"] == 2
        print("  ✅ stats() accumulate across ops")

    def test_lru_eviction(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=2, ttl_seconds=60)
        l1.set("a", b"1")
        l1.set("b", b"2")
        l1.set("c", b"3")  # should evict "a"
        s = l1.stats()
        assert s["l1_size"] == 2
        # "a" is now in L2 only (still in L2 because set writes to both).
        # But L1 lost it. So `get("a")` is L1-miss → L2-hit → read-through.
        assert l1.get("a") == b"1"
        print("  ✅ LRU eviction at max_size")

    def test_set_with_explicit_ttl(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        l1 = registrar.l1(max_size=10, ttl_seconds=60)
        l1.set("k", b"v", ttl_seconds=10)
        # L2 receives the exact TTL (no anti-avalanche jitter —
        # `set_with_ttl` is the low-level `ValueOps` API; the
        # jitter is only applied by the high-level `StringFunction`
        # path).
        ttl_ms = registrar.key_ops().get_expire("k")
        assert 9_500 <= ttl_ms <= 10_000, f"unexpected TTL: {ttl_ms}"
        print("  ✅ set(ttl_seconds=10) propagates to L2")

    def test_factory_same_config_returns_same_instance(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        a = registrar.l1(max_size=10, ttl_seconds=60)
        b = registrar.l1(max_size=10, ttl_seconds=60)
        assert a is b
        print("  ✅ factory: same config → same instance")

    def test_factory_different_config_returns_different_instance(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        a = registrar.l1(max_size=10, ttl_seconds=60)
        b = registrar.l1(max_size=2, ttl_seconds=30)
        assert a is not b
        # Stats are independent.
        a.set("k", b"1")
        assert a.stats()["l1_size"] == 1
        assert b.stats()["l1_size"] == 0
        print("  ✅ factory: different config → different instance")

    def test_constructor_rejects_invalid_config(self) -> None:
        with pytest.raises(ValueError):
            L2DistributedCache(
                value_ops=None,  # type: ignore[arg-type]
                region="x",
                max_size=0,
                ttl_seconds=60,
            )
        with pytest.raises(ValueError):
            L2DistributedCache(
                value_ops=None,  # type: ignore[arg-type]
                region="x",
                max_size=10,
                ttl_seconds=0,
            )
        print("  ✅ constructor rejects invalid config")


class TestL2CacheFactory:
    def test_factory_clear_drops_instances(self) -> None:
        f: L2CacheFactory = L2CacheFactory(default_region="test")
        a = f.get_or_create(
            value_ops=None,  # type: ignore[arg-type]
            max_size=10,
            ttl_seconds=60,
        )
        b = f.get_or_create(
            value_ops=None,  # type: ignore[arg-type]
            max_size=10,
            ttl_seconds=60,
        )
        assert a is b
        f.clear()
        c = f.get_or_create(
            value_ops=None,  # type: ignore[arg-type]
            max_size=10,
            ttl_seconds=60,
        )
        assert c is not a  # cleared
        print("  ✅ L2CacheFactory.clear() drops instances")
