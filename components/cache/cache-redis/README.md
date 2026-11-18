# atlas-richie-cache-redis

Redis backend for `atlas-richie-cache-core`. Implements the
`ProviderRegistrar` SPI (30 abstract methods: 16 ops + 1
infrastructure + 11 functions + 2 meta) over `redis-py`. Mirrors the
Java reference library's `redis/manage/*` 1:1.

## Public API

```python
from atlas_richie.cache_redis import RedisProviderRegistrar
from atlas_richie.cache_core import GlobalCache, CacheRegistry

registrar = RedisProviderRegistrar(
    redis_url="redis://127.0.0.1:16379/0",
    namespace="atlas-richie",
)
CacheRegistry.register(GlobalCacheManager(registrar))

GlobalCache.value_ops().set("user:42", {"name": "richie"})
value = GlobalCache.value_ops().get("user:42", dict)
```

## Layout

```
atlas_richie/cache_redis/
├── __init__.py                          # public API
├── errors.py                            # CacheError + subclasses
├── serialization.py                     # JSON + bytes helpers
├── redis_distributed_cache.py           # redis-py wrapper
├── redis_cache_infrastructure.py        # CacheInfrastructure impl
├── redis_provider_registrar.py          # ProviderRegistrar impl (M1: 2/30 real, 28 stub)
└── managers/
    ├── __init__.py
    └── redis_string_manager.py          # M1: ValueOps + StringFunction
```

## Status (R-220 M1)

- 2/30 `ProviderRegistrar` methods real: `value_ops()`,
  `string_function()`.
- 28 stubbed with `NotImplementedError` (M2-M4 will fill in).
- Real-Redis smoke test: 1 round-trip.

## Running the integration tests

Credentials are never hardcoded. The suites default to a passwordless
`redis://127.0.0.1:16379/0` and skip cleanly when that server is unreachable
**or** requires a password they do not have (the gate PINGs, not just TCP-probes).

Point them at your own instance with the environment:

```bash
export ATLAS_RICHIE_CACHE_REDIS_URL='redis://:YOUR_PASSWORD@127.0.0.1:16379/1'
uv run python -m pytest components/cache -q
```

The same pattern applies to `ATLAS_RICHIE_STREAMMQ_REDIS_URL`,
`ATLAS_RICHIE_STATEMACHINE_REDIS_URL`, `ATLAS_RICHIE_COORDINATION_REDIS_URL`
and `ATLAS_RICHIE_SECRET_REDIS_TEST_URL`.
