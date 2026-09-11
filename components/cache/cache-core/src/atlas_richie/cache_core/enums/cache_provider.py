"""缓存提供者枚举类。
----
缓存提供者枚举类。列出可作为后端的缓存系统类型。

English
--------
Cache backend provider enum.

Mirrors `cn.richie696.component.cache.enums.CacheProvider`.
"""

from __future__ import annotations

from enum import StrEnum


class CacheProvider(StrEnum):
    """缓存提供者枚举类。

    English
    --------
    Cache backend provider.
    """

    #: redis
    REDIS = "redis"

    #: dragonfly db
    DRAGONFLY_DB = "dragonfly_db"


__all__ = ["CacheProvider"]
