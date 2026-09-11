"""GEO 地理位置相关 API 管理器，封装了 Redis 中 GEO 数据结构的常用操作。
----
``GeoOps`` + ``GeoFunction`` 的 Redis 后端实现（M3.B）。

主要用于地理位置的存储、距离计算、范围查询等场景。
支持添加地理位置、计算成员间距离、范围查找等功能。

适用于 LBS、附近的人、地图服务等应用。

镜像 ``cn.richie696.component.cache.redis.manage.RedisGeoManager`` 的结构。
同时实现底层 ``GeoOps`` Protocol 与高层 ``GeoFunction`` Protocol。共 3 + 3 = 6
个方法，无冲突（Java 故意使用了不同名称）。

距离 / 半径单位（依据 Redis 文档）：

- ``GEOADD`` 原样存储经纬度。
- ``GEODIST`` 默认以**米**为单位返回距离。
- ``GEOSEARCH ... FROMLONLAT ... BYRADIUS ... KM`` 以**千米**为单位返回
  半径内的成员。

cache-core 中 ``GeoPointResult.distance`` 字段单位为**米**；``GeoOps.radius``
签名接收 ``radius: float`` 并以米为单位返回。我们将 Redis 基于 km 的
半径查询返回的距离乘以 1000 转换为米。

English
--------
Redis-backed `GeoOps` + `GeoFunction` (M3.B).

Mirrors `cn.richie696.component.cache.redis.manage.RedisGeoManager`
1:1. Implements both the low-level `GeoOps` Protocol and the
high-level `GeoFunction` Protocol. 3 + 3 = 6 methods, no
collisions (Java deliberately uses different names).

Distance / radius units (per Redis docs):

- `GEOADD` stores lon/lat verbatim.
- `GEODIST` returns distance in **meters** by default.
- `GEOSEARCH ... FROMLONLAT ... BYRADIUS ... KM` returns members
  within the radius in **kilometers**.

The cache-core `GeoPointResult.distance` field is in **meters**; the
`GeoOps.radius` signature takes a `radius: float` and returns
meters. We convert Redis's km-based radius queries to meters by
multiplying the returned distance by 1000.
"""

from __future__ import annotations

from typing import List

from atlas_richie.cache_core.commons.geo_point_result import GeoPointResult
from atlas_richie.cache_core.function.geo_function import GeoFunction
from atlas_richie.cache_core.ops.geo_ops import GeoOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache


class RedisGeoManager(GeoOps, GeoFunction):
    """GEO 地理位置相关 API 管理器，封装了 Redis 中 GEO 数据结构的常用操作。
    ----
    Redis 后端的 GEO / 地理位置管理器。

    English
    --------
    Redis-backed GEO / geographic location manager.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    # ── GeoOps (low-level) ─────────────────────────────────────────

    def add(
        self, key: str, longitude: float, latitude: float, member: str
    ) -> None:
        self._backend.raw_client().geoadd(
            self._k(key), (float(longitude), float(latitude), str(member))
        )

    def distance(self, key: str, member1: str, member2: str) -> float:
        """Distance in **meters** between two members.

        Raises `KeyError_` (or returns `float('nan')`) if either
        member is missing — `redis-py` returns `None`. We surface
        that as 0.0 (the caller can pre-check with `exists_in_set`).
        """
        raw = self._backend.raw_client().geodist(
            self._k(key), str(member1), str(member2)
        )
        if raw is None:
            return 0.0
        return float(raw)

    def radius(
        self, key: str, longitude: float, latitude: float, radius: float
    ) -> List[GeoPointResult]:
        """Members within `radius` **kilometers** of (lon, lat).

        Returns a list of `GeoPointResult` with `distance` in
        **meters** (matches the cache-core doc).
        """
        results = self._backend.raw_client().geosearch(
            self._k(key),
            longitude=float(longitude),
            latitude=float(latitude),
            radius=float(radius),
            unit="km",
            withcoord=True,
            withdist=True,
        )
        out: List[GeoPointResult] = []
        for member, dist_km, coord in results or []:
            lon, lat = coord
            out.append(
                GeoPointResult(
                    member=str(member),
                    longitude=float(lon),
                    latitude=float(lat),
                    distance=float(dist_km) * 1000.0,  # km → m
                )
            )
        return out

    # ── GeoFunction (high-level) ───────────────────────────────────

    def add_geo(
        self, key: str, longitude: float, latitude: float, member: str
    ) -> None:
        self.add(key, longitude, latitude, member)

    def geo_dist(
        self, key: str, member1: str, member2: str
    ) -> float | None:
        """Same as `distance` but returns `None` for missing members
        (matches the cache-core `GeoFunction.geo_dist` signature)."""
        raw = self._backend.raw_client().geodist(
            self._k(key), str(member1), str(member2)
        )
        if raw is None:
            return None
        return float(raw)

    def geo_radius(
        self, key: str, longitude: float, latitude: float, radius: float
    ) -> List[GeoPointResult]:
        return self.radius(key, longitude, latitude, radius)


__all__ = ["RedisGeoManager"]
