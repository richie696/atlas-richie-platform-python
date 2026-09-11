"""地理位置操作接口。

中文
----
地理位置操作接口。
对应底层 Geo 数据结构，支持地理位置存储、距离计算及半径查询。

English
--------
Geographic location ops interface.

Mirrors `cn.richie696.component.cache.ops.GeoOps`. Stores `(lon, lat, member)`,
computes distances, and runs radius queries.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import List, Protocol

from ..commons.geo_point_result import GeoPointResult


class GeoOps(Protocol):
    """中文
    ----
    地理位置操作接口。对应底层 Geo 数据结构，支持地理位置存储、距离计算
    及半径查询。

    English
    --------
    Geographic location ops. Maps to the underlying Geo data structure;
    supports geo point storage, distance computation, and radius
    queries.
    """

    @abstractmethod
    def add(self, key: str, longitude: float, latitude: float, member: str) -> None:
        """中文
        ----
        添加一个地理位置点 `(longitude, latitude)`，关联到 `member`。

        English
        --------
        Add a geo point `(longitude, latitude)` associated with
        `member`.
        """
        ...

    @abstractmethod
    def distance(self, key: str, member1: str, member2: str) -> float:
        """中文
        ----
        计算两个 member 之间的距离（单位：米）。

        English
        --------
        Returns distance in meters.
        """
        ...

    @abstractmethod
    def radius(
        self, key: str, longitude: float, latitude: float, radius: float
    ) -> List[GeoPointResult]:
        """中文
        ----
        以 `(longitude, latitude)` 为中心，搜索半径 `radius`（米）内的
        所有位置点。

        English
        --------
        Search for all geo points within `radius` (meters) of
        `(longitude, latitude)`.
        """
        ...


__all__ = ["GeoOps"]
