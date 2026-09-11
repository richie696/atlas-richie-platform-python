# R-220 M1 Handoff: `atlas-richie-cache-redis` package skeleton

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** M1 **DONE** — 49/49 real-Redis smoke tests green, 2/30
`ProviderRegistrar` methods real, 28 stubbed with clear
"NotImplementedError → R-220 M2-M4" messages.

## Goal

Stand up the new `atlas-richie-cache-redis` package that:

1. Satisfies the full `ProviderRegistrar` Protocol from
   `atlas-richie-cache-core` (30 abstract methods: 16 ops + 1
   `CacheInfrastructure` + 11 functions + 2 meta).
2. Implements M1: 2/30 real (`value_ops`, `string_function`).
3. Stubs the other 28 with `NotImplementedError` carrying the
   planned `R-###` reference, so the registrar type-checks and
   unimplemented methods fail loudly at call time.
4. Real-Redis smoke (49 tests) end-to-end.

## What was built

```
components/cache-redis/
├── pyproject.toml                              # name=atlas-richie-cache-redis, v0.1.0
├── README.md
├── src/atlas_richie/cache_redis/
│   ├── __init__.py                             # public API
│   ├── errors.py                               # CacheError + 7 subclasses (PlatformError-rooted)
│   ├── serialization.py                        # encode_value/decode_value (JSON + bytes)
│   ├── redis_distributed_cache.py              # redis-py wrapper (namespace, make_key, get/set/scan, ...)
│   ├── redis_cache_infrastructure.py           # CacheInfrastructure impl (per-key type registry)
│   ├── redis_provider_registrar.py             # ProviderRegistrar impl (2/30 real, 28 stub)
│   └── managers/
│       ├── __init__.py
│       ├── _stubs.py                           # 14 NotImplementedError stub classes (M2-M4)
│       └── redis_string_manager.py             # M1: ValueOps (13 methods) + StringFunction (12 methods)
└── tests/
    └── test_redis_provider_registrar_smoke.py  # 49 real-Redis tests
```

### Workspace integration

- `pyproject.toml`: added `components/cache-redis` to workspace
  members and `[tool.uv.sources]`.
- `foundation/platform/pyproject.toml`: added
  `atlas-richie-cache-redis>=0.1.0,<0.2.0` to the aggregate deps.
- `tools/release/verify_isolated_wheels.py`: added
  `("atlas-richie-cache-redis==0.1.0", "atlas_richie.cache_redis")`
  to `PACKAGES`.

## Architecture decisions

| Decision | Choice | Why |
|---|---|---|
| Class layout | 1 manager class per data structure, implementing **both** the Ops Protocol AND the Function Protocol | Java 1:1 mirror: `RedisStringManager implements StringFunction` AND uses `StringRedisTemplate` (the equivalent of `ValueOps`). The `ProviderRegistrar.value_ops()` and `.string_function()` return the same instance. |
| Method collision resolution | Single signature with `timeout_millis=0` default | Java overloads (`increment(key)` vs `increment(key, timeout)`) merge into one Python method. `timeout_millis=0` matches the ValueOps shape (no TTL refresh) and `timeout_millis>0` matches the StringFunction shape. |
| Anti-avalanche TTL offset | **Only on the StringFunction high-level helpers** (`add_value`, `add_value_if_absent`, `batch_add_to_string_with_ttl`, `batch_update_if_absent`) | Matches Java: `addValue(key, value, timeout)` adds `getRandomExtraMillis()`, but the low-level `opsForValue().set(key, value, timeout)` (the ValueOps equivalent) does not. Anti-avalanche is a **user-facing policy**, not a low-level invariant. |
| KEYS command | Replaced with SCAN-iter in `RedisDistributedCache.keys()` | The target Redis instance has `rename-command KEYS ""`. Also: KEYS is O(N) and blocks the server; SCAN is the correct production choice. |
| Connection-string credential masking | `_mask_redis_url` replaces password with `***` in the stored `connection_string` | The connection string is exposed via `CacheInfrastructure.get_connection_string()` and may end up in logs. Passwords must never be echoed. |
| Stub failures | `_NotImplementedOps.__getattr__` raises `StateError` with the planned R-### reference | Calling a stubbed method surfaces a clear error pointing at the right follow-up milestone, rather than a generic "AttributeError" or silent `None` return. |
| Type registry | `RedisCacheInfrastructure` keeps a `dict[str, type]` behind an RLock | For `ValueOps.get_typed` / `FieldOps.get_typed`: callers can register a key → type mapping and then read with a runtime-resolved type (Java's `TypeReference<T>`). |
| JSON ser/de for complex values | `encode_value` (str/bytes/int/float/bool pass-through; else `json.dumps`); `decode_value` (mirror) | Java's `JsonUtils.getInstance().deserialize(...)`. No third-party JSON dep — stdlib `json` is enough for the use case. |

## Test coverage (49/49 passing in 1.06s)

- **`TestProviderRegistrarShape`** (5): provider enum,
  value_ops/string_function identity, connection-string password
  masking, namespace isolation, manager Protocol satisfaction.
- **`TestUnimplementedStubs`** (24, parametrized): the 14 stubbed
  ops + the 9 stubbed functions each raise a clear error on
  method call.
- **`TestValueOpsEndToEnd`** (11): real Redis round-trip for
  `get`/`set`/`set_with_ttl`/`set_if_absent`/`increment`/`increment_by`/
  `decrement`/`decrement_by`/`increment_double`/`batch_set`/
  `batch_set_with_ttl`/`get_map`/`get_list`, with str/int/dict
  payloads.
- **`TestStringFunctionEndToEnd`** (7): `add_value` /
  `add_value_if_absent` / `increment` / `get_value_map` /
  `get_objects` / `batch_add_to_string` / `batch_add_to_string_with_ttl`.
- **`TestGlobalCacheFacadeDispatch`** (2): `GlobalCache.value_ops()`
  and `GlobalCache.string_function()` both route to the registered
  manager; `GlobalCache.active_provider() == CacheProvider.REDIS`.

Test namespace is unique per run (`R-220-M1:<uuid_hex>`) so parallel
runs cannot collide; teardown SCAN-iterates and `DEL`s the test
namespace.

## Issues fixed during M1

1. **No `atlas_richie.cache_core.errors` module** — the stubs
   file initially imported from there, but `StateError` lives in
   `cache_core/registry/cache_registry.py`. Fixed by using the
   local `cache_redis.errors.StateError` instead.
2. **Redis `KEYS` disabled** — the cleanup fixture used
   `client.keys(...)`; replaced with `client.scan_iter(...)` and
   the `RedisDistributedCache.keys()` method was rewritten to use
   SCAN-iter too (correctness + production safety).
3. **Method-name collisions** between `ValueOps` and
   `StringFunction` (`increment`, `decrement`, `increment_by`,
   `decrement_by`, `increment_double`): the two Protocols have
   different signatures, which Python can't merge. Resolved by
   merging into one method per name with `timeout_millis=0`
   default. The `*_with_ttl` variants in `ValueOps` now delegate
   to the merged method.
4. **High-level TTL test waits too short** — `batch_add_to_string_with_ttl`
   applies the anti-avalanche offset (60-600s), so the 200ms TTL
   + 300ms wait assertion can never pass. Replaced with a "TTL
   is set and exceeds the offset" assertion that uses Redis's raw
   `PTTL`.

## Known limitations (will be addressed in M2-M4)

- `*_with_lock` methods raise `NotImplementedError` (M4: needs
  `RedisLockManager` + Bloom + L2 wiring).
- `RedisStringManager.scan` uses SCAN-iter (M1-correct but not the
  shared cursor that M3's `RedisKeyManager` will provide).
- Bloom filter `put` integration on cache writes is not yet
  wired (M4: `RedisSharedBloomFilter`).
- Perf guard wrapping (`RedisPerfGuard.checkStringWritePayload`,
  `checkBatchRead`) is deferred.
- 28/30 `ProviderRegistrar` methods raise `NotImplementedError` —
  this is the whole point of M2-M4 (incremental fill-in).

## Verification commands

```bash
# Build
uv sync

# Run M1 smoke (49/49 should pass)
uv run --package atlas-richie-cache-redis pytest \
  components/cache-redis/tests/ -v

# Real Redis env override
ATLAS_RICHIE_CACHE_REDIS_URL=redis://:Redis2025!Local@127.0.0.1:16379/0 \
  uv run --package atlas-richie-cache-redis pytest \
  components/cache-redis/tests/ -v
```

## Next: M2 (RedisFieldManager + RedisCollectionManager)

The next chunk (3 manager pairs) is planned as:
- `RedisFieldManager` implements `FieldOps` (16 methods) +
  `HashFunction` (15 methods) — Hash data structure.
- `RedisCollectionManager` implements `CollectionOps` (10 methods)
  + `SetFunction` (12 methods) — Set data structure.
- `RedisStringManager` is already done in M1, so the "String" pair
  is complete; M2 = Field + Collection = **2 more pairs** (M1
  says "3 pairs" but String is already done; net new is 2).

Estimated scope: ~1500-2000 lines of new code + ~25-30 new tests
covering Hash and Set semantics. The pattern is identical to M1's
`RedisStringManager` (manager = ops + function, with `timeout_millis`
defaults merged for collision resolution, anti-avalanche on
high-level helpers only).

Ready to proceed on user direction.
