"""Local cache region name + Holder + static facade + value wrapper.

Also exports the L1 capability contracts: `CacheStatistics` (hit/miss
counters), `CacheLoader` (read-through) and `CacheWriter`
(write-through).
"""

from __future__ import annotations

from .cache_loader import (
    CacheLoader,
    CallableCacheLoader,
    as_cache_loader,
)
from .cache_name import CacheName
from .cache_statistics import CacheStatistics
from .cache_writer import (
    CacheWriter,
    CallableCacheWriter,
    as_cache_writer,
)
from .expiry_wrapper import ExpiryWrapper
from .local_cache import LocalCache
from .local_cache_manager import LocalCacheManager

__all__ = [
    "CacheLoader",
    "CacheName",
    "CacheStatistics",
    "CacheWriter",
    "CallableCacheLoader",
    "CallableCacheWriter",
    "ExpiryWrapper",
    "LocalCache",
    "LocalCacheManager",
    "as_cache_loader",
    "as_cache_writer",
]
