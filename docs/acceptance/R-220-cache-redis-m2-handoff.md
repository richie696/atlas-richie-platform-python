# R-220 M2 Handoff: `RedisFieldManager` + `RedisCollectionManager`

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** M2 **DONE** — 104/104 real-Redis tests green (49 M1 + 55 M2 net new),
**6/30** `ProviderRegistrar` methods real, **24 stubbed** with clear
`R-220 M3-M4` pointers.

## Goal

Implement the next two `ProviderRegistrar` accessor pairs, mirroring
Java's `redis/manage/RedisHashManager` and `redis/manage/RedisSetManager`
1:1 in Python:

- **`RedisFieldManager`** — `FieldOps` (16 methods, low-level Hash
  field access) + `HashFunction` (15 methods, high-level stampede
  prevention + bulk helpers).
- **`RedisCollectionManager`** — `CollectionOps` (10 methods, low-
  level Set access) + `SetFunction` (12 methods, high-level pop /
  difference / batch).

## What was built

### New files

- `components/cache-redis/src/atlas_richie/cache_redis/managers/redis_field_manager.py`
  (~12 KB, 31 merged methods).
- `components/cache-redis/src/atlas_richie/cache_redis/managers/redis_collection_manager.py`
  (~10 KB, 22 unmerged methods).
- `components/cache-redis/tests/test_redis_field_manager.py`
  (~10 KB, 30 tests).
- `components/cache-redis/tests/test_redis_collection_manager.py`
  (~10 KB, 25 tests).

### Updated files

- `managers/_stubs.py` — removed `RedisFieldManager`,
  `RedisCollectionManager`, `HashFunction_Stub`, `SetFunction_Stub`
  (now real). The 7 remaining `Redis*Manager` stubs + 7 remaining
  function stubs target M3-M4.
- `redis_provider_registrar.py` — eager-construct
  `RedisFieldManager` + `RedisCollectionManager`; wire
  `field_ops()` / `hash_function()` / `collection_ops()` /
  `set_function()` to the real instances.
- `managers/__init__.py` — re-export the two new managers.
- `__init__.py` (package root) — re-export the two new managers.
- `test_redis_provider_registrar_smoke.py` — remove the
  `field_ops` / `collection_ops` / `hash_function` /
  `set_function` entries from the parametrize lists (they are real
  now, not stubs).

## Architecture decisions

| Decision | Choice | Why |
|---|---|---|
| Method-name collision strategy | **Field**: 3 merges with defaults (`set` → `timeout_millis=0`; `increment` / `decrement` → `delta=1`). **Collection**: 0 merges (Java already uses distinct method names). | Mirrors the M1 pattern. Field/Hash are 1-arg (no TTL) vs 2-arg (TTL) — defaults collapse the difference. Set/Collection were designed distinct in Java; we preserve that. |
| Anti-avalanche policy | Field: high-level `set(key, field, value, timeout_millis)` adds offset when `timeout_millis > 0`; low-level `set(key, field, value)` does not. Collection: `set(key, values, timeout_millis)` adds offset when `timeout_millis > 0`; `add_set` and `add_set_item` are TTL-less. | Matches Java `addValue` vs `opsForValue().set()` split. Anti-avalanche is a high-level policy. |
| Pipeline vs single command | `set_all` uses `HSET` with mapping (one round-trip). `batch_set` uses a non-transactional pipeline. `set` (Collection) uses DEL + SADD + EXPIRE in a pipeline. | Single round-trip when possible; pipeline (non-transactional) for batch. NEVER a transaction (per Java doc). |
| `pop` for Set | `SPOP` returns `None` for empty key, or one element. We unwrap the list/bytes shape redis-py gives back. | redis-py's `SPOP` shape changed across versions; we normalise to `T \| None`. |
| `get_all` missing key | Returns `{}`, not `None`. | Java's `HGETALL` returns an empty map for missing keys; mirrors the same. |
| `decode_set` helper | `_decode_set(raws, clazz)` returns a Python `set` of decoded values, skipping `None`. | Centralises the SADD/SMEMBERS decode logic; mirrors `_decode_value` for the single-value case. |

## Test coverage (104/104 passing in 1.33s)

### `test_redis_field_manager.py` (30 tests)

- **`TestFieldOpsSingleField`** (5): set/get round-trip for str / int /
  dict; `get` on missing key returns `None`; `exists`.
- **`TestFieldOpsAtomicCounters`** (6): `increment` (default + delta),
  `increment_by`, `increment_double`, `decrement` (default + delta),
  `decrement_by`.
- **`TestFieldOpsMultiField`** (8): `set_all` / `get_all` /
  `get_many_typed` / `get_many` / `get_fields` / `size` / `remove` /
  `batch_set`.
- **`TestFieldOpsLockNotYetImplemented`** (3): `get_with_lock` /
  `get_with_lock_typed` / `get_many_with_lock` raise
  `NotImplementedError` (M4).
- **`TestHashFunctionHighLevel`** (7): anti-avalanche TTL on
  `set(..., timeout_millis)`, low-level `set` does NOT set TTL,
  `increment(key, field, delta)` / `decrement(key, field, delta)`
  via the merged signature, three lock helpers raise.
- **`TestProviderRegistrarWiring`** (2): `field_ops()` returns
  `RedisFieldManager`; `hash_function()` is the same instance.

### `test_redis_collection_manager.py` (25 tests)

- **`TestCollectionOpsCore`** (12): add / size / get / exists /
  remove / pop / pop_empty / pop_many / set (replace) /
  set_with_anti_avalanche_ttl / batch_set / plus the add-duplicate
  idempotency check.
- **`TestCollectionOpsLockNotYetImplemented`** (1): `get_with_lock`
  raises.
- **`TestSetFunction`** (12): `get_from_set` / `pop_data_from_set` /
  `pop_members_from_set` / `difference_from_set` /
  `difference_from_set_with_key` / `difference_and_store_from_set` /
  `exists_in_set` / `batch_add_to_set` / `add_set` / `add_set_item` /
  `remove_set_item` / `get_set_size`.
- **`TestSetFunctionLockNotYetImplemented`** (1):
  `get_from_set_with_lock` raises.
- **`TestProviderRegistrarWiring`** (2): `collection_ops()` returns
  `RedisCollectionManager`; `set_function()` is the same instance.

## Issues fixed during M2

1. **`hpttl` returns a list, not an int** — the anti-avalanche TTL
   test assumed the raw `hpttl(key, "f")` return was an `int`, but
   `redis-py` returns a list of TTLs (one per field requested). Fixed
   by unwrapping `ptls[0]` / `httl[0]` in the two assertions.

## Known limitations (will be addressed in M3-M4)

- **All `*_with_lock` stampede prevention** raise
  `NotImplementedError` (M4: `RedisLockManager` + Lua release).
- **Bloom filter integration on writes** is not wired (M4:
  `RedisSharedBloomFilter`).
- **Perf guard wrapping** is deferred (M4).

## M1+M2 status

`ProviderRegistrar` real methods: **6/30**

| Method | Status | Manager |
|---|---|---|
| `value_ops` | real (M1) | `RedisStringManager` |
| `field_ops` | real (M2) | `RedisFieldManager` |
| `collection_ops` | real (M2) | `RedisCollectionManager` |
| `struct_ops` | stub | M3 |
| `ranking_ops` / `key_ops` / `bitmap_ops` / `hyper_log_ops` / `geo_ops` / `script_ops` / `limiter_ops` / `lock_ops` / `notification_ops` / `event_ops` / `bounded_queue_ops` / `bounded_stack_ops` | stub | M3-M4 |
| `cache_infrastructure` | real (M1) | `RedisCacheInfrastructure` |
| `string_function` | real (M1) | `RedisStringManager` |
| `hash_function` | real (M2) | `RedisFieldManager` |
| `set_function` | real (M2) | `RedisCollectionManager` |
| 8 other function accessors | stub | M3-M4 |
| `provider` / `connection_string` | real (M1) | registrar |

## Verification commands

```bash
# All M1 + M2 tests (104/104 should pass)
uv run --package atlas-richie-cache-redis pytest \
  components/cache-redis/tests/ -v

# Just M2 net new
uv run --package atlas-richie-cache-redis pytest \
  components/cache-redis/tests/test_redis_field_manager.py \
  components/cache-redis/tests/test_redis_collection_manager.py
```

## Next: M3 (10 remaining manager pairs + 8 remaining function stubs)

Estimated scope: ~2500-3500 lines of new code + ~100-120 new tests.
The pattern is now well-established (manager = ops + function, with
`timeout_millis`/`delta` defaults merged for collision resolution,
anti-avalanche on high-level helpers only).

Read this doc + R-220-cache-redis-m1-handoff.md for the full
context before starting M3.
