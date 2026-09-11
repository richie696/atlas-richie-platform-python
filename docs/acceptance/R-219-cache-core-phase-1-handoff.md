# R-219 Phase 1 Handoff: `atlas-richie-cache-core` framework

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** Phase 1 **DONE** — 35/35 unit tests green, 0 backend dependency,
workspace-integrated.

## Goal

Translate the Java reference `atlas-richie-component/atlas-richie-cache`'s
framework layer (non-Spring, non-Redis) into a new
`atlas-richie-cache-core` Python package that:

1. Mirrors the Java 2-tier architecture (`ops` low-level primitives +
   `function` high-level business helpers).
2. Replaces Spring's DI with a `ProviderRegistrar` SPI + `CacheRegistry`
   mutex-guarded singleton (per locked decision: "ProviderRegistrar
   (not BackendRegistrar) — core 不 import 后端; CacheRegistry 互斥").
3. Replaces JSR-107 with a Pythonic `LocalCache` static facade backed by
   `cachetools.LRUCache` (per locked decision: "LocalCache 用 cachetools
   提供 Python 原生进程级缓存 API（不 模仿 JSR-107 接口形状）").
4. Carries zero backend dependency. `redis-py` is NOT installed by this
   package; the Redis provider will live in a separate
   `atlas-richie-cache-redis` package in Phase 4.

## What was built

### Package layout

```
components/cache-core/
├── pyproject.toml                                  # name=atlas-richie-cache-core, v0.1.0
├── README.md
├── src/atlas_richie/cache_core/
│   ├── __init__.py                                 # public API: GlobalCache, GlobalCacheManager, LocalCache, LocalCacheManager, ProviderRegistrar, CacheRegistry, StateError
│   ├── ops/                  (16 Protocols)        # ValueOps, StructOps, FieldOps, CollectionOps, RankingOps, KeyOps, BitmapOps, HyperLogOps, GeoOps, ScriptOps, LimiterOps, LockOps, BoundedQueueOps, BoundedStackOps, NotificationOps, EventOps, CacheInfrastructure
│   ├── function/             (11 Protocols)        # StringFunction, HashFunction, SetFunction, ZSetFunction, GeoFunction, HyperLogFunction, BitmapFunction, LockFunction, NotificationFunction, EventFunction, CacheFunction (base Protocol)
│   ├── contracts/            (5 Protocols)         # DistributedLock, DistributedBatchLock, PubSubBus, KeyspaceEventBus, KeyspaceEventListener, BloomFilter, SnowflakeIdBuilder
│   ├── commons/                                    # CacheKeyUtils, GeoPointResult
│   ├── enums/                                      # CacheProvider, KeyTypeEnum, L2CachingRegion
│   ├── config/                                     # BloomFilterConfig, BloomFilterType
│   ├── operations/           (6 classes)           # BoundedListCapacityLimits, BoundedListElementConverter, BoundedQueue, BoundedStack, SetCapacityLimits, ZSetCapacityLimits
│   ├── local/                (7 files)
│   │   ├── enums/                                  # CacheProvider (local: CACHETOOLS / EHCACHE / CAFFEINE / CACHE2K / REDIS), ExpiryPolicy (StrEnum)
│   │   ├── config/                                 # LocalCacheProperties (pydantic-settings), CacheDefinition (per-region override)
│   │   ├── util/                                   # DefensiveCopyUtils (deepcopy with immutable fast-path)
│   │   └── manage/                                 # CacheName (Protocol), ExpiryWrapper (frozen dataclass), LocalCacheManager (Holder), LocalCache (static facade)
│   ├── registry/             (2 files)             # ProviderRegistrar (Protocol SPI, 30 abstract methods), CacheRegistry (mutex-guarded singleton) + StateError
│   ├── facade/                                     # GlobalCache (static facade, 16 ops + 11 functions + lifecycle)
│   └── holder/                                      # GlobalCacheManager (per-instance Holder wrapping a registrar)
└── tests/
    └── test_cache_core_smoke.py                    # 35 tests, all green
```

### Architecture decisions

| Decision | Choice | Why |
|---|---|---|
| Backend discovery | `ProviderRegistrar` (Protocol) implemented by backends; `CacheRegistry.register(...)` mutex-singleton | "core 不 import 后端"; "CacheRegistry 互斥" (per locked decision). Avoids Spring IoC. |
| Function layer | 11 Protocols extending `CacheFunction` (which is itself a Protocol) | Two-tier ops + function (per Java mirror). Static methods + class constants on `CacheFunction` shared via Protocol default implementations. |
| L2CachingRegion + CacheName | `StrEnum` with explicit `get_cache()` (no `Protocol` inheritance) | `Protocol` (ABCMeta) + `StrEnum` (EnumMeta) clash; structural typing works because `CacheName` is a `Protocol`. |
| LocalCache | Static classmethods, lazy `LocalCacheManager` singleton, `set_manager(...)` for test injection, `reset()` for teardown | Mirrors Java `LocalCache` shape; uses double-checked locking under the hood. |
| LocalCacheManager | Per-region `_CacheBucket` (one `cachetools.LRUCache` + parallel `_expiries` dict) | Per-key TTL override works because cachetools.TTLCache does not support per-entry TTL. |
| ExpiryPolicy | `ACCESSED` + `ETERNAL` fully supported; `CREATED` / `MODIFIED` / `TOUCHED` fall back to `ACCESSED` semantics (Phase 1 simplification) | Strict JSR-107 semantics would duplicate complexity the user explicitly rejected ("不 模仿 JSR-107"). Documented as known limitation. |
| Defensive copy | `copy.deepcopy` with `pickle` fallback on `TypeError`; skip-copy for `None` / `bool` / `int` / `float` / `str` / `bytes` / `complex` / `tuple[immutable]` / `frozenset[immutable]` | Java's Fury is overkill; this matches the contract (caller cannot mutate the stored value) without the deep-copy tax for primitives. |
| `CacheFunction` constant defaults | Set on the Protocol class body (`CacheFunction.LOCK_KEY = "LOCK_KEY_"` after the class) | Protocols declare attributes; setting defaults outside the class body is the documented idiom for Protocols with default values. |
| Workspace integration | `components/cache-core` added to `[tool.uv.workspace] members` and `[tool.uv.sources]`; `atlas-richie-cache-core==0.1.0` added to `foundation/platform` aggregate and `tools/release/verify_isolated_wheels.py` PACKAGES | One-component-one-package rule; framework layer sits at the same level as the existing `components/cache`. |

### Public API

```python
from atlas_richie.cache_core import (
    GlobalCache,                 # static facade
    GlobalCacheManager,          # per-instance Holder
    LocalCache,                  # static facade (in-process)
    LocalCacheManager,           # Holder (in-process)
    ProviderRegistrar,           # SPI for backends
    CacheRegistry,               # mutex-guarded singleton
    StateError,                  # raised by register/active on misuse
)
```

### Backend contract (for `atlas-richie-cache-redis` and beyond)

A backend must:

1. Implement `ProviderRegistrar` (30 abstract methods: 16 ops + 1
   `CacheInfrastructure` + 11 functions + `provider()` + `connection_string()`).
2. Call `CacheRegistry.register(registrar)` exactly once at process
   startup.
3. Call `CacheRegistry.unregister()` on graceful shutdown (to allow
   re-registration in tests).

A second `register()` raises `StateError`. The contract enforces
"one process, one provider" at runtime.

## What was fixed during implementation

Three real bugs surfaced during the smoke test (R-219 had no
end-to-end run before this):

1. **`L2CachingRegion(StrEnum, CacheName)`** — metaclass conflict
   between `EnumMeta` and `Protocol`'s `ABCMeta`. Fix: drop the
   `CacheName` from the bases; just define `get_cache()` on the
   enum. `CacheName` is a `Protocol`, so duck typing (structural
   subtyping) handles the rest. Documented in the file's docstring.

2. **`typing.Map` not in Python 3.12** — leftover from Java/older
   typing. 17 occurrences across `string_function.py`,
   `hash_function.py`, `value_ops.py`, `field_ops.py`. Replaced with
   `Dict` (matches the rest of the codebase's `dict[K, V]` style).

3. **`class HashFunction(CacheFunction, Protocol)`** — `CacheFunction`
   was a concrete class with class-level constants, which a `Protocol`
   cannot extend (Protocols can only inherit from Protocols). Fix:
   make `CacheFunction` itself a `Protocol`; use Protocol default
   implementations for the static helper; set the constant defaults
   on the Protocol class body after the class definition.

All three fixes are documented in the affected files' docstrings.

## Tests

`components/cache-core/tests/test_cache_core_smoke.py` — **35/35 passing**
in 0.16s.

Coverage:

- `TestCacheRegistry` (4): unregistered raises, install/active,
  double-install raises, uninstall resets.
- `TestGlobalCacheFacade` (4): raises when unregistered, delegates to
  registrar, `active()` returns Holder, raises after uninstall.
- `TestGlobalCacheManagerHolder` (2): delegation, `close()` is no-op.
- `TestProviderRegistrarShape` (1): exact 30 abstract methods
  (catches drift if anyone adds a method without updating backends).
- `TestConcurrentRegistry` (1): 50 install/uninstall iterations in a
  worker thread (mutex correctness).
- `TestLocalCacheBasics` (7): put/get, get-missing, put_with_ttl,
  put_if_absent, CAS replace, get_and_remove, get_and_put.
- `TestLocalCacheRegions` (3): multi-region isolation, region size,
  clear_region.
- `TestLocalCacheExpiryPolicies` (2): ETERNAL no-expire, custom
  CacheDefinition.
- `TestDefensiveCopy` (3): immutable fast-path, deep-copy list,
  get-returns-copy.
- `TestValueObjects` (3): ExpiryWrapper, CacheKeyUtils,
  L2CachingRegion structural CacheName.
- `TestBoundedListCapacityLimits` (4): validate in-range,
  reject out-of-range, can_grow, compute_doubled.
- `TestProtocolSatisfaction` (1): `_FakeRegistrar` exposes all required
  methods (catches missing-method bugs at the stub level).

## Non-goals (deferred to later R-### phases)

- **Phase 2** — Spring decorator translation: `@Component` /
  `@Autowired` → `ProviderRegistrar`; `@ConfigurationProperties` →
  pydantic-settings. (Not needed: Python has no DI container, so the
  Spring → ProviderRegistrar mapping is already implicit. The only
  remaining work here is documenting the wiring patterns in the
  backend's `pyproject.toml`.)
- **Phase 3** — JSR-107 reconciliation: **resolved** by locked
  decision (cachetools, NOT JSR-107 shape). The `ExpiryPolicy.ETERNAL`
  fallback in `LocalCache` is a known simplification.
- **Phase 4** — Redisson reconciliation: Bloom Filter (Redis shared
  version) **must be atomic via Lua**; use `redis-py` SETBIT/GETBIT for
  bit-level operations. To be done when `atlas-richie-cache-redis`
  is implemented.
- **Phase 5** — Core passes 90/90 E2E (will need a real Redis
  ProviderRegistrar to plug in; the framework itself is now ready).
- **Phase 6** — `atlas-richie-cache-redis` package: 17 managers
  (`RedisValueManager`, `RedisFieldManager`, …) implementing the 30
  `ProviderRegistrar` methods 1:1 from Java's `redis/manage/`.

## Verification commands

```bash
# Sync workspace
uv sync

# Run core smoke tests
uv run --package atlas-richie-cache-core pytest components/cache-core/tests/ -v

# Build isolated wheel (after `python tools/release/prepare_wheelhouse.py`)
python tools/release/verify_isolated_wheels.py

# Legacy in-memory tests (pre-existing failures, not in R-219 scope)
# 18 failures are in `test_in_memory.py` because `GlobalCacheManager.memory()`
# classmethod was never implemented. Real Redis E2E (69/69) still passes.
uv run --package atlas-richie-cache pytest components/cache/tests/e2e/test_redis_real.py
```

## Files touched

- **New:** `components/cache-core/` (entire package — 18 new Python
  files + tests + README + pyproject.toml)
- **Modified:**
  - `pyproject.toml` — added `components/cache-core` to workspace members
    and sources
  - `foundation/platform/pyproject.toml` — added
    `atlas-richie-cache-core>=0.1.0,<0.2.0` to dependencies
  - `tools/release/verify_isolated_wheels.py` — added
    `("atlas-richie-cache-core==0.1.0", "atlas_richie.cache_core")` to
    PACKAGES
- **Unchanged:** `components/cache/` (the legacy 1-package implementation
  still works for the 90/90 real-Redis E2E).
