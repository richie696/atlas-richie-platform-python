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

## Release process

1. Update this file and package versions in one reviewed change.
2. Tag the exact commit as `v<version>` after CI succeeds.
3. The protected `pypi` GitHub environment publishes the verified artifacts with trusted publishing.
4. Verify uploaded hashes and install each wheel in isolation before announcing the release.

## Verification snapshot (R-M4 commit `233bd43`)

```text
pytest components/cache/cache-core/tests/ \
        components/cache/cache-redis/tests/ -q
→ 462 passed, 4 skipped, 0 failures
```

Test count trajectory:
- R-220 baseline: 369 passed, 4 skipped
- + R-M4 sample (12) + worker 1 (48) + worker 2 (43) − 9 obsolete = 462 net
- All 4 skipped are pre-existing `keyspace listener` E2E tests marked
  `xfail` for environments without Redis keyspace notification config.
