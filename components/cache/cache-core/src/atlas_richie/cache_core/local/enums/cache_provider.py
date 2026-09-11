"""本地缓存类型枚举。
----
本地缓存类型枚举。列出 JSR-107 兼容的本地缓存提供者。

English
--------
Local-cache provider enum.

Mirrors `cn.richie696.component.cache.local.enums.CacheProvider`. This
is the local-cache scoped enum (in-process L1 + optional dual-tier
Redis-coordination), distinct from the top-level
`cache_core.enums.CacheProvider` which lists only distributed
backends (Redis / Dragonfly).

The Python translation supports `CACHETOOLS` as the primary local
backend; the other Java-compatible names are kept for API surface
parity and raise `NotImplementedError` if a backend tries to use them.
"""

from __future__ import annotations

from enum import StrEnum


class CacheProvider(StrEnum):
    """本地缓存提供者枚举类。

    English
    --------
    Local cache provider enum.
    """

    #: In-process cache backed by `cachetools` (Pythonic, NOT JSR-107).
    CACHETOOLS = "cachetools"

    #: Java Ehcache backend (compatibility stub; not implemented in Python).
    EHCACHE = "ehcache"

    #: Java Caffeine backend (compatibility stub; not implemented in Python).
    CAFFEINE = "caffeine"

    #: Java cache2k backend (compatibility stub; not implemented in Python).
    CACHE2K = "cache2k"

    #: Dual-tier (in-process + Redis coordination); only `CACHETOOLS` is
    #: actually wired up in the Python translation; `REDIS` falls back to
    #: the distributed `GlobalCache` for coordination.
    REDIS = "redis"


__all__ = ["CacheProvider"]
