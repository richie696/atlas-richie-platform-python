"""Real-Redis smoke tests for the three smaller M3.B managers:

- `RedisGeoManager` — GEO / geographic location.
- `RedisHyperLogManager` — HyperLogLog cardinality estimation.
- `RedisBitmapManager` — bit-level read/write.

All three are small (2-3 methods each) so they share a test file.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisBitmapManager,
    RedisGeoManager,
    RedisHyperLogManager,
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
    namespace = f"R-220-M3B-Data:{uuid.uuid4().hex[:8]}"
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


# ── GeoManager ───────────────────────────────────────────────────────


class TestGeoManager:
    def test_add_and_distance(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisGeoManager = registrar.geo_ops()
        # Shenzhen HQ
        mgr.add("cities", 114.0579, 22.5431, "shenzhen")
        # Beijing
        mgr.add("cities", 116.4074, 39.9042, "beijing")
        # Distance Shenzhen–Beijing is ~1900 km = 1_900_000 m.
        d = mgr.distance("cities", "shenzhen", "beijing")
        # Allow ±50 km tolerance.
        assert 1_850_000 < d < 1_950_000, f"expected ~1.9M m, got {d}"

    def test_radius_returns_geo_point_results(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisGeoManager = registrar.geo_ops()
        mgr.add("cities", 114.0579, 22.5431, "shenzhen")
        mgr.add("cities", 113.9, 22.5, "nearby_city")
        mgr.add("cities", 116.4074, 39.9042, "beijing")  # far away

        # 50 km radius around Shenzhen.
        results = mgr.radius("cities", 114.0579, 22.5431, radius=50.0)
        members = {r.member for r in results}
        assert "shenzhen" in members
        assert "nearby_city" in members
        assert "beijing" not in members
        # All results have valid (lon, lat) and a non-None distance.
        for r in results:
            assert r.longitude != 0.0 or r.latitude != 0.0
            assert r.distance is not None
            assert r.distance > 0

    def test_geo_dist_returns_none_for_missing(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisGeoManager = registrar.geo_ops()
        mgr.add("cities", 114.0579, 22.5431, "shenzhen")
        assert mgr.geo_dist("cities", "shenzhen", "missing") is None

    def test_add_geo_alias(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisGeoManager = registrar.geo_ops()
        mgr.add_geo("cities", 114.0579, 22.5431, "shenzhen")
        assert mgr.geo_dist("cities", "shenzhen", "shenzhen") == 0.0

    def test_geo_radius_alias(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisGeoManager = registrar.geo_ops()
        mgr.add("cities", 114.0579, 22.5431, "shenzhen")
        results = mgr.geo_radius("cities", 114.0579, 22.5431, radius=10.0)
        assert any(r.member == "shenzhen" for r in results)


# ── HyperLogManager ──────────────────────────────────────────────────


class TestHyperLogManager:
    def test_add_and_count(self, registrar: RedisProviderRegistrar) -> None:
        mgr: RedisHyperLogManager = registrar.hyper_log_ops()
        mgr.add("uv", "user:1", "user:2", "user:3")
        assert mgr.count("uv") == 3

    def test_count_uniques(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisHyperLogManager = registrar.hyper_log_ops()
        mgr.add("uv", "user:1", "user:2", "user:1")  # duplicate
        # HLL is approximate but with only 2 distinct values, the
        # result should be exactly 2.
        assert mgr.count("uv") == 2

    def test_count_empty(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisHyperLogManager = registrar.hyper_log_ops()
        assert mgr.count("uv:never:added") == 0

    def test_pf_add_alias(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisHyperLogManager = registrar.hyper_log_ops()
        mgr.pf_add("uv", "a", "b", "c")
        assert mgr.pf_count("uv") == 3

    def test_hyper_log_function_aliases(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.hyper_log_function()
        assert isinstance(mgr, RedisHyperLogManager)
        assert mgr is registrar.hyper_log_ops()


# ── BitmapManager ─────────────────────────────────────────────────────


class TestBitmapManager:
    def test_set_and_get(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisBitmapManager = registrar.bitmap_ops()
        mgr.set("flags", 0, True)
        mgr.set("flags", 5, True)
        mgr.set("flags", 10, True)
        assert mgr.get("flags", 0) is True
        assert mgr.get("flags", 5) is True
        assert mgr.get("flags", 10) is True
        # Unset positions default to False.
        assert mgr.get("flags", 1) is False
        assert mgr.get("flags", 7) is False

    def test_set_false_toggles_off(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisBitmapManager = registrar.bitmap_ops()
        mgr.set("flags", 3, True)
        assert mgr.get("flags", 3) is True
        mgr.set("flags", 3, False)
        assert mgr.get("flags", 3) is False

    def test_set_bit_and_get_bit_aliases(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisBitmapManager = registrar.bitmap_ops()
        mgr.set_bit("flags", 100, True)
        assert mgr.get_bit("flags", 100) is True

    def test_bitmap_function_aliases(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.bitmap_function()
        assert isinstance(mgr, RedisBitmapManager)
        assert mgr is registrar.bitmap_ops()

    def test_many_offsets(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Verify that a wide range of offsets works (byte-aligned and
        byte-spanning)."""
        mgr: RedisBitmapManager = registrar.bitmap_ops()
        for offset in [0, 1, 7, 8, 9, 15, 16, 100, 1000]:
            mgr.set("flags", offset, True)
        for offset in [0, 1, 7, 8, 9, 15, 16, 100, 1000]:
            assert mgr.get("flags", offset) is True
