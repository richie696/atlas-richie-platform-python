# atlas-richie-cache-core

Framework-neutral distributed cache platform: polymorphism contracts
(ops / function / contracts), static facades (`GlobalCache`,
`LocalCache`), Holders (`GlobalCacheManager`, `LocalCacheManager`),
shared utilities, and a process-local cache manager backed by
`cachetools`.

Backend-agnostic: concrete backend packages
(`atlas-richie-cache-redis`, future `atlas-richie-cache-dragonfly`,
in-memory test doubles, ...) implement the `ProviderRegistrar` SPI
and register themselves with the framework's mutex-guarded
`CacheRegistry`. The static facade `GlobalCache` then delegates to
the active provider.

Zero backend dependency: `redis-py` is NOT installed by this package.
`cachetools`, `pydantic`, and `pydantic-settings` are the only
runtime dependencies.

## Public API

```python
from atlas_richie.cache_core import (
    GlobalCache,
    GlobalCacheManager,
    LocalCache,
    LocalCacheManager,
    ProviderRegistrar,
    CacheRegistry,
    StateError,
)
```

## Backend contract

A backend must implement `ProviderRegistrar` (16 ops + 1
infrastructure + 11 functions + 2 meta accessors) and call
`CacheRegistry.register(...)` at startup. The second register raises
`StateError`; call `unregister()` first to swap backends.

## Anti-avalanche jitter

`CacheFunction.get_random_extra_millis()` is the platform's single
anti-avalanche jitter implementation: it returns a **discrete**
whole-minute offset in `[60_000, 600_000]` ms (10 equally likely
values), mirroring Java's
`ThreadLocalRandom.current().nextInt(1, 11) * 60_000L`.

Backends that write cache TTLs must call it rather than shipping their
own copy with a different distribution — see `atlas-richie-cache-redis`
for the reference wiring (including the two paths that deliberately keep
an exact TTL: the raw low-level ops and the negative-cache marker).

## Layout

```
atlas_richie/cache_core/
├── ops/           # 16 low-level ops Protocols
├── function/      # 11 high-level function Protocols
├── contracts/     # 5 cross-cutting contracts (lock, pubsub, ...)
├── commons/       # cache_key_utils, geo_point_result
├── enums/         # CacheProvider, KeyTypeEnum, L2CachingRegion
├── config/        # BloomFilterConfig
├── operations/    # BoundedQueue, BoundedStack, capacity limits
├── local/         # in-process cache (cachetools, NOT JSR-107)
├── registry/      # ProviderRegistrar SPI + CacheRegistry mutex
├── facade/        # GlobalCache static facade
└── holder/        # GlobalCacheManager per-instance Holder
```
