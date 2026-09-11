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
    CacheName,
    ExpiryWrapper,
    LocalCache,
    LocalCacheManager,
)
from .util import DefensiveCopyUtils

__all__ = [
    "CacheDefinition",
    "CacheName",
    "CacheProvider",
    "DefensiveCopyUtils",
    "ExpiryPolicy",
    "ExpiryWrapper",
    "LocalCache",
    "LocalCacheManager",
    "LocalCacheProperties",
]
