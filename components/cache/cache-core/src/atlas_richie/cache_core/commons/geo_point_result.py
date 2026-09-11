"""地理位置结果类。
----
地理位置结果类。封装 GEO 查询返回的成员名称、经度、纬度与距离。

English
--------
Geo query result (member + distance).

Mirrors `cn.richie696.component.cache.commons.GeoPointResult`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeoPointResult:
    """地理位置结果类。

    Attributes:
        member: 成员名称
        longitude: 经度
        latitude: 纬度
        distance: 距离，单位：米，可为 `None`

    English
    --------
    Geographic point query result.
    """

    #: 成员名称
    member: str
    #: 经度
    longitude: float
    #: 纬度
    latitude: float
    #: 距离（单位：米，可为 `None`）
    distance: float | None = None


__all__ = ["GeoPointResult"]
