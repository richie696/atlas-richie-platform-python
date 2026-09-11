# Changelog

All notable changes are documented here. The project follows Keep a Changelog
categories and Semantic Versioning.

## [Unreleased]

### Added

- Framework-neutral HTTP, OAuth 2.1, and MCP component packages.
- Modern MCP Streamable HTTP, MRTR, client cache/pagination, and legacy dialect adapter.
- **`atlas-richie-cache-core`** + **`atlas-richie-cache-redis`** (R-220):
  distributed cache component with 16 ops + 11 function Protocols, 30-method
  `ProviderRegistrar` SPI, in-memory test doubles, and a Redis backend
  (16 manager classes, each implementing one ops Protocol + the
  corresponding function Protocol). Importable as `atlas_richie.cache_core`
  / `atlas_richie.cache_redis`; installable as separate wheels or as the
  `atlas-richie-platform` aggregate.
- **L2 distributed cache** (R-223, `atlas-richie-cache-redis`): two-tier
  cache-aside with L1 (`cachetools.TTLCache`) + L2 (Redis). Per-region
  per-instance sizing via `L2CacheFactory`; same-config returns the same
  instance, different-config returns a different one.
- **Bloom filters** (R-222, `atlas-richie-cache-core` +
  `atlas-richie-cache-redis`): `BloomFilterConfig` + `InMemoryBloomFilter`
  (process-local bytearray) + `RedisSharedBloomFilter` (BITSET-backed,
  Lua atomic for `SETBIT`). 8 concurrency tests verify atomicity under
  contention.
- **Pub/Sub notification** (R-221): `NotificationOps.subscribe()` with
  `RedisNotificationListener` handle; `NotificationFunction` + tests.
- **SnowflakeIdBuilder** (R-224): 64-bit Snowflake ID with Redis-backed
  round-robin `workerId` allocation; each `snowflake()` call returns a
  fresh builder with a fresh workerId.
- **Stampede prevention** (R-M4): `*_with_lock` methods for
  Value / String / Hash / Set / Struct — 10 method bodies across 4
  manager classes, replacing `raise NotImplementedError("...M4...")`
  placeholders. Per-key stampede lock via Lua `SET NX PX` + compare-and-
  delete `GET` + `DEL`. Concurrent caller fan-in verified to 1-3 loader
  calls max (10-thread barrier-synchronized test).
- **Bilingual docstrings** (R-229 + R-230): 89 public-API docstrings
  carry a `中文 ---- / English --------` bilingual block. R-229 ported
  Java Javadoc (77 files: contracts, function, commons, config, enums,
  local, operations, ops, cache-redis managers); R-230 added fresh
  Chinese summaries to 12 top-level glue files that have no Java
  counterpart (framework static facade, registry, registrar SPI,
  cache-redis root, L2 cache).
- **9 handoff docs** in `docs/acceptance/` documenting the R-220 →
  R-M4 implementation (each milestone: motivation, architecture, files
  changed, review gate, follow-ups).
- **Loader timeout enforcement** (R-M5.1): all 10 `*_with_lock` methods
  gained an optional `loader_timeout_millis: int | None = None` keyword
  argument. Uses a single-worker `concurrent.futures.ThreadPoolExecutor`
  + `future.result(timeout=...)`; on timeout the method returns `None`
  (no cache write, no exception) and the stampede lock is released
  cleanly. `None` preserves legacy unbounded behavior — 100%
  backward compatible. Helper `_call_db_loader_with_timeout` is
  re-used by 4 managers, no duplication.
- **L1 (cachetools) + in-process stampede integration** (R-M5.2):
  `L2DistributedCache.get_or_load(key, loader, *, ttl_seconds,
  loader_timeout_millis)` — a loader-driven read that funnels
  concurrent in-process misses to ONE loader call via per-key
  `threading.Lock` + `WeakValueDictionary`-backed lock table. The
  in-process lock is the L2-layer stampede defense; cross-process
  defense stays in `RedisStringManager.get_with_lock` (R-M4). L1
  hit path is unchanged (no lock, no network) — warm cache pays
  zero lock cost. `L2DistributedCache.get()` is unchanged (backward
  compatible — `get_or_load` is purely additive).
- **98 new tests** (R-M5.1): 10 in
  `test_redis_string_manager_loader_timeout.py`, 56 in
  `test_redis_field_manager_loader_timeout.py`, 32 in
  `test_redis_collection_struct_loader_timeout.py`. Cover loader
  timeout / exception propagation / cache-hit unaffected / lock
  re-acquisition / concurrent funnel / batch-specific
  (`get_many_with_lock`).
- **14 new tests** (R-M5.2): `test_l2_distributed_cache_get_or_load.py`.
  Cover L1 hit short-circuit / L2 read-through / loader success+None+timeout+raise /
  concurrent in-process funnel (10 threads → 1 loader call) /
  per-key granularity (5 keys × 2 threads → 5 loader calls) /
  weakref table cleanup / TTL applied / argument validation.
- **2 more handoff docs**: `R-M5-1-loader-timeout-handoff.md` and
  `R-M5-2-l1-stampede-handoff.md` (plus the R-M5.2 design doc
  `R-M5-2-l1-stampede-design.md`).

### Changed

- **Cache parent restructure** (R-227): single-package
  `components/cache/src/` replaced with
  `components/cache/{cache-core, cache-redis}/` to keep
  `atlas_richie.cache_core` and `atlas_richie.cache_redis` as
  separately installable wheels. Public import paths unchanged.
- **Centralized version management** (R-228): `versions.toml` is the
  single source of truth for all 15 package versions.
  `tools/sync_versions.py` propagates every change into every
  `pyproject.toml` (own `version` + cross-component dependency
  constraints rewritten to `>=X.Y.Z,<X.(Y+1).0`). Replaces per-package
  manual `version` editing with one atomic edit + script run.

### Fixed

- **`CacheFunction` Protocol parent class** (R-229): `class CacheFunction:`
  was missing the `Protocol` parent, causing all 11 subclasses
  (`HashFunction`, `SetFunction`, `StringFunction`, etc.) to fail under
  Python 3.12+. Fixed to `class CacheFunction(Protocol):`.
- **PEP 420 namespace package cleanup** (R-220 → R-M4 cycle): three
  stale empty `__init__.py` files at
  `components/cache/{cache-core,cache-redis}/src/atlas_richie/{,cache_redis/local/}__init__.py`
  were deleted; `atlas_richie` is now a true namespace package. The
  previous empty `__init__.py` files caused `atlas_richie.cache_core`
  and `atlas_richie.cache_redis` to be mutually exclusive depending on
  `sys.path` import order.
- **Bilingual docstring format consistency**: the same anchor convention
  (`中文\n----` + `English\n--------`) is now applied uniformly across
  89 files. Javadoc tag conversion rules
  (`@param` → `Args:`, `@return` → `Returns:`, `@throws` → `Raises:`,
  `<p>` → blank line, `<b>` → `**bold**`, `@author`/`@since`/`@version`
  dropped) are documented in `docs/acceptance/R-229-bilingual-docstring-migration-handoff.md`.

### Removed

- 9 obsolete "NotImplementedError-placeholder" tests across
  `test_redis_field_manager.py`,
  `test_redis_collection_manager.py`,
  `test_redis_struct_manager.py`. The `*_with_lock` methods these
  tests asserted as "not yet implemented" are now real in R-M4.
  Replaced by 103 new stampede-prevention tests
  (12 in `test_redis_string_manager_with_lock.py`,
   48 in `test_redis_field_manager_with_lock.py`,
   35 in `test_redis_collection_struct_with_lock.py`,
    8 in `test_redis_bloom_filter_atomicity.py`).

### Added (R-M5 follow-ups)

- **98 new tests** (R-M5.1): 10 in
  `test_redis_string_manager_loader_timeout.py`, 56 in
  `test_redis_field_manager_loader_timeout.py`, 32 in
  `test_redis_collection_struct_loader_timeout.py`. Cover loader
  timeout / exception propagation / cache-hit unaffected / lock
  re-acquisition / concurrent funnel / batch-specific
  (`get_many_with_lock`).
- **14 new tests** (R-M5.2): `test_l2_distributed_cache_get_or_load.py`.
  Cover L1 hit short-circuit / L2 read-through / loader success+None+timeout+raise /
  concurrent in-process funnel (10 threads → 1 loader call) /
  per-key granularity (5 keys × 2 threads → 5 loader calls) /
  weakref table cleanup / TTL applied / argument validation.

## Release process

1. Update this file and package versions in one reviewed change.
2. Tag the exact commit as `v<version>` after CI succeeds.
3. The protected `pypi` GitHub environment publishes the verified artifacts with trusted publishing.
4. Verify uploaded hashes and install each wheel in isolation before announcing the release.

## Verification snapshot (R-M5.2 commit `c08ed30`)

```text
pytest components/cache/cache-core/tests/ \
        components/cache/cache-redis/tests/ -q
→ 574 passed, 4 skipped, 0 failures
```

Test count trajectory:
- R-220 baseline: 369 passed, 4 skipped
- + R-M4 (12 + 48 + 35 + 8 sample/worker) − 9 obsolete = +94 net → 462
- + R-M5.1 sample (10) → 471 (+ 1 known flaky keyspace)
- + R-M5.1 worker (88) → 560 (full suite, no flaky this run)
- + R-M5.2 (14) → 574
- All 4 skipped are pre-existing `keyspace listener` E2E tests marked
  `xfail` for environments without Redis keyspace notification config.
- 1 pre-existing flaky (`test_redis_event_manager.py::TestKeyspaceEventListener::test_expired_event_fires`)
  passes on isolated run; full-suite timing-sensitive.
