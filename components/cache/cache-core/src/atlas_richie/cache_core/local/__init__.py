"""Process-local in-memory cache layer (Pythonic, not JSR-107).

Mirrors `cn.richie696.component.cache.local` from the reference Java
implementation **without** the JSR-107 contract. The static facade
`LocalCache` and the per-instance `LocalCacheManager` are the only
two entry points a caller should need.
"""

from __future__ import annotations

from .config import CacheDefinition, LocalCacheProperties
from .enums import CacheProvider, ExpiryPolicy
from .manage import (
    CacheLoader,
    CacheName,
    CacheStatistics,
    CacheWriter,
    CallableCacheLoader,
    CallableCacheWriter,
    ExpiryWrapper,
    LocalCache,
    LocalCacheManager,
    as_cache_loader,
    as_cache_writer,
)
from .util import DefensiveCopyUtils

__all__ = [
    "CacheDefinition",
    "CacheLoader",
    "CacheName",
    "CacheProvider",
    "CacheStatistics",
    "CacheWriter",
    "CallableCacheLoader",
    "CallableCacheWriter",
    "DefensiveCopyUtils",
    "ExpiryPolicy",
    "ExpiryWrapper",
    "LocalCache",
    "LocalCacheManager",
    "LocalCacheProperties",
    "as_cache_loader",
    "as_cache_writer",
]
