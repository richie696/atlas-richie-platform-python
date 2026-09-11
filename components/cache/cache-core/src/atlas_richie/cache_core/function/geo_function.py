"""GEO 地理位置缓存操作函数。
----
GEO 地理位置相关 API 管理器接口，封装了 Redis 中 GEO 数据结构的常用操作。
主要用于地理位置的存储、距离计算、范围查询等场景。
支持添加地理位置、计算成员间距离、范围查找等功能。
适用于 LBS、附近的人、地图服务等应用。

English
--------
Geographic location cache function (high-level, built on `GeoOps`).

Mirrors `cn.richie696.component.cache.function.GeoFunction`. Java's
`org.springframework.data.geo.Distance` collapses to a plain `float`
(distance in meters) plus a `float | None` for missing members — the
unit is always meters at this layer, so the type is just numeric.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import List, Protocol

from ..commons.geo_point_result import GeoPointResult


class GeoFunction(Protocol):
    """GEO 地理位置相关 API。

    封装了 Redis 中 GEO 数据结构的常用操作。主要用于地理位置的存储、
    距离计算、范围查询等场景。支持添加地理位置、计算成员间距离、
    范围查找等功能。适用于 LBS、附近的人、地图服务等应用。

    English
    --------
    Maps to the underlying Geo data structure.
    """

    @abstractmethod
    def add_geo(
        self, key: str, longitude: float, latitude: float, member: str
    ) -> None:
        """添加地理位置数据到 Redis GEO 集合。

        Args:
            key: GEO 集合的键
            longitude: 经度
            latitude: 纬度
            member: 成员名称

        English
        --------
        Add a geo point to the GEO set.
        """
        ...

    @abstractmethod
    def geo_dist(
        self, key: str, member1: str, member2: str
    ) -> float | None:
        """计算两个成员之间的地理距离。

        Args:
            key: GEO 集合的键
            member1: 成员 1 名称
            member2: 成员 2 名称

        Returns:
            两成员之间的距离（单位：米），任一成员不存在时返回 `None`。

        English
        --------
        Compute the distance between two members of the GEO set.

        Returns:
            The distance between the two members in meters, or `None`
            when either member is missing.
        """
        ...

    @abstractmethod
    def geo_radius(
        self,
        key: str,
        longitude: float,
        latitude: float,
        radius: float,
    ) -> List[GeoPointResult]:
        """查询指定经纬度为圆心、指定半径范围内的所有成员。

        返回业务无关的 `GeoPointResult` 列表。

        Args:
            key: GEO 集合的键
            longitude: 圆心经度
            latitude: 圆心纬度
            radius: 查询半径（单位：公里）

        Returns:
            范围内的成员及其地理信息列表（业务无关 Bean）。

        English
        --------
        Query the GEO set for members within `radius` km of
        (longitude, latitude). Returns a list of business-agnostic
        `GeoPointResult` entries.
        """
        ...


__all__ = ["GeoFunction"]
