"""atlas-richie-cache-core: framework-neutral distributed cache contracts.

This package contains ONLY:

- Polymorphism contracts (Protocol) for the 16 ops, 11 functions, and 5
  other cross-cutting contracts (lock / pubsub / keyspace / snowflake /
  bloom). Concrete implementations live in backend packages
  (`atlas-richie-cache-redis`, future `atlas-richie-cache-dragonfly`).
- Core entry points (`GlobalCache`, `GlobalCacheManager`) and the
  process-local cache entry points (`LocalCache`, `LocalCacheManager`).
- Shared utilities (enums, error types, capacity limits, bounded-
  structure protocols, L2 / perf-guard contracts).
- Local (in-process) cache manager backed by `cachetools` (Pythonic,
  NOT JSR-107 compatible).
- Provider-registration SPI (`ProviderRegistrar`) and the mutex-guarded
  singleton registry (`CacheRegistry`).

Zero backend dependency. `redis-py` is NOT installed by this package.
"""

from __future__ import annotations

from .global_cache import GlobalCache
from .global_cache_manager import GlobalCacheManager
from .local import LocalCache, LocalCacheManager
from .registry import CacheRegistry, ProviderRegistrar, StateError

__version__ = "0.1.0"

__all__ = [
    "CacheRegistry",
    "GlobalCache",
    "GlobalCacheManager",
    "LocalCache",
    "LocalCacheManager",
    "ProviderRegistrar",
    "StateError",
    "__version__",
]
