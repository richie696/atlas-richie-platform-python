"""全局缓存的二级缓存区域名称枚举类。
----
全局缓存的二级缓存区域名称枚举类。
枚举值对应 JSR-107 Cache 名称。

English
--------
L2 caching region enum.

Mirrors `cn.richie696.component.cache.enums.L2CachingRegion`. The Java
side has this enum implement the `CacheName` interface; in Python we
can't `class L2CachingRegion(StrEnum, CacheName)` directly because
`Protocol`'s `ABCMeta` and `EnumMeta` clash. Instead we just define
`get_cache()` on the enum — `CacheName` is a `Protocol`, so any
caller that takes `CacheName` accepts `L2CachingRegion` via duck
typing (structural subtyping). This is the documented Python idiom
for "enum implements Protocol".
"""

from __future__ import annotations

from enum import StrEnum


class L2CachingRegion(StrEnum):
    """全局缓存的二级缓存区域名称枚举类。

    Implements the `CacheName` Protocol structurally via the
    `get_cache()` method below.

    English
    --------
    L2 caching region name enum.
    """

    #: 全局缓存区域（通用 KV 等）
    GLOBAL_CACHE = "global_cache"

    #: 访问日志专用缓存区域
    ACCESS_LOG = "access_log"

    def get_cache(self) -> str:
        """返回区域名称（对应 JSR-107 Cache 名称）。

        English
        --------
        Return the region name (corresponds to a JSR-107 Cache name).
        """
        return self.value


__all__ = ["L2CachingRegion"]
