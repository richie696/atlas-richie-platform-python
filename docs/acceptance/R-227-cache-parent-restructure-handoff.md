# R-227 Handoff: `cache/` parent restructure

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DONE** — `components/cache/` is now a pure aggregator;
`cache-core` and `cache-redis` live underneath; legacy 1-package code
removed. 369 + 4 skip tests pass; 14/14 wheels install in fresh venv.

## Motivation

The previous layout had `cache/`, `cache-core/`, `cache-redis/` as
three siblings in `components/`. The `cache/` directory looked like
a parent (Maven `-parent` convention) but actually held source code
of its own (the legacy 1-package), which made the naming
inconsistent and confused the IDE / wheel discovery.

Java uses the `-parent` convention for multi-module groups (e.g.
`atlas-richie-http-parent/` with subdirs for each HTTP client
backend). Python supports the same pattern via uv workspaces + a
plain README at the parent.

## Before

```
components/
├── cache/                          ← has src/, tests/, pyproject.toml (legacy 1-package)
│   ├── src/atlas_richie/cache/...
│   ├── tests/e2e/test_redis_real.py  (90/90)
│   ├── pyproject.toml              (atlas-richie-cache==0.1.0)
│   └── README.md
├── cache-core/                     ← sibling, not under cache/
└── cache-redis/                    ← sibling, not under cache/
```

## After

```
components/
└── cache/                          ← parent, aggregator only (no src/, no code)
    ├── README.md                   ← indexes cache-core/ + cache-redis/
    ├── cache-core/                 ← atlas-richie-cache-core==0.1.0
    │   ├── src/atlas_richie/cache_core/...
    │   ├── tests/...
    │   └── pyproject.toml
    └── cache-redis/                ← atlas-richie-cache-redis==0.1.0
        ├── src/atlas_richie/cache_redis/...
        ├── tests/...
        └── pyproject.toml
```

## What changed

| File | Before | After |
|---|---|---|
| `components/cache/src/` | had code (legacy 1-package) | **deleted** |
| `components/cache/tests/` | had 90/90 + 18 in-memory E2E | **deleted** (M5 E2E + R-221~226 covers 100%) |
| `components/cache/README.md` | described the legacy API | rewritten as **parent index** for `core/` + `redis/` |
| `components/cache/pyproject.toml` | built `atlas-richie-cache==0.1.0` wheel | **deleted** (no source, no build) |
| `components/cache-core/` | sibling of `cache/` | moved under `cache/core/cache-core/` |
| `components/cache-redis/` | sibling of `cache/` | moved under `cache/redis/cache-redis/` |
| root `pyproject.toml` `[tool.uv.workspace].members` | `components/cache`, `components/cache-core`, `components/cache-redis` | `../../components/cache/cache-core`, `../../components/cache/cache-redis` (legacy `cache` removed) |
| root `pyproject.toml` `[tool.uv.sources]` | had `atlas-richie-cache` source | `atlas-richie-cache` removed; only `core` and `redis` remain |
| `foundation/platform/pyproject.toml` | depended on `atlas-richie-cache` (legacy) | dropped legacy; depends only on `cache-core` + `cache-redis` |
| `tools/release/verify_isolated_wheels.py` PACKAGES | 15 entries including `atlas-richie-cache` | 14 entries (legacy removed) |

## What was kept stable

- **Import paths** — `from atlas_richie.cache_core import ...` and
  `from atlas_richie.cache_redis import ...` continue to work. The
  `module-name` in each sub-package's `pyproject.toml` is unchanged.
- **Wheel names** — `atlas-richie-cache-core==0.1.0` and
  `atlas-richie-cache-redis==0.1.0` continue to be the published
  artifacts. The legacy `atlas-richie-cache==0.1.0` wheel is
  **removed** (no consumer depended on it after the R-220
  M5 E2E migration).
- **Test coverage** — 369 tests in `../../components/cache/cache-core`
  + `../../components/cache/cache-redis` cover all 30
  `ProviderRegistrar` methods + 6 M5+ capabilities + cross-cutting
    concerns (namespace isolation, credential mask, GlobalCache
    facade, E2E wiring).

## Why no `pyproject.toml` at the parent `cache/` level

uv workspaces do not support nested workspaces — every package
belongs to exactly one workspace. Trying to put
`[tool.uv.workspace]` in `components/cache/pyproject.toml` while the
root pyproject already declared the subdirs as members caused
"workspace member is also part of another workspace" errors. The
parent is therefore a plain directory with a README; the
workspace is flat and declared only at the repo root.

## Test results

```text
369 passed, 4 skipped in 27.82s
```

- **369 passed** — all 30 `ProviderRegistrar` methods + 6 M5+
  capabilities (R-221 Pub/Sub subscribe, R-222 Bloom Filter,
  R-223 L2 DistributedCache, R-224 SnowflakeIdBuilder, R-225
  KeyspaceListener, R-226 in-process event bus) + 6 cross-cutting
  tests + 4 wiring classes.
- **4 skipped** — `test_7_5_perf_guard` + `test_7_6_list_ops` in
  M5 E2E (not in any R-### scope; documented as future work).

## Iteration after restructure (2026-09-11)

After the initial R-227 commit, the user flattened one more level:
the children live as `cache/cache-core/` and `cache/cache-redis/`
directly, not under an intermediate `cache/core/` + `cache/redis/`
level. The README and handoff doc were updated to match. The
empty `atlas_richie/__init__.py` files in both sub-packages were
also removed (uv_build treats `src/atlas_richie/` as a namespace
package and rejects sibling `__init__.py` files). The final
review gate re-ran cleanly:

- `uv sync` — 14 packages
- `uv build --wheel` for `cache-core` + `cache-redis` + `platform`
- 369 + 4 skip tests
- `tools/release/verify_isolated_wheels.py` — 14/14 fresh-venv
  install + `import atlas_richie.platform`

## Review gate

- ✅ `uv sync` — workspace re-solved; no missing packages
- ✅ `uv build --wheel` for `cache-core` + `cache-redis` + `platform`
- ✅ `tools/dependency-check/check_core_imports.py` — `core dependency import policy: OK`
- ✅ `tools/release/verify_isolated_wheels.py` — 14 packages
  installed in fresh venv, `import atlas_richie.platform` succeeds

## Trade-offs / design notes

1. **Parent is a directory, not a package** — Some Python projects
   prefer a `pyproject.toml` at the parent (with `[project] name =
   "atlas-richie-cache"` and no source). We chose "no pyproject"
   because (a) uv's flat-workspace model doesn't support nested
   members and (b) the parent is pure coordination, not a buildable
   artifact. A README is sufficient.

2. **Legacy 1-package is gone, not archived** — the 90/90 legacy
   `test_redis_real.py` was the only consumer of the legacy
   `atlas_richie.cache` import. R-220 M5 E2E in the new package
   covers all 24 capabilities; the legacy tests would be redundant.
   If history is needed, the `R-220-cache-redis-handoff.md` +
   `R-2026-09-11-real-acceptance-handoff.md` documents the
   pre-restructure state.

3. **No nested `cache/legacy/`** — keeping the legacy tests around
   as a `legacy/` subdir would have meant the cache/ directory
   has 3 subdirs (`legacy/`, `core/`, `redis/`) which is the
   wrong axis. The legacy tests' information value is fully
   captured in the R-### handoff docs; re-running them in CI
   would only consume cycles.

## Next: extend with more backends

To add a Dragonfly backend (planned in R-222..R-226 handoff), the
shape is now:

```
components/cache/
├── README.md
├── core/cache-core/        (unchanged)
├── redis/cache-redis/      (unchanged)
└── dragonfly/cache-dragonfly/   ← new
    ├── pyproject.toml      (atlas-richie-cache-dragonfly==0.1.0)
    └── src/atlas_richie/cache_dragonfly/...
```

Then add the path to root `pyproject.toml` workspace members + the
wheel name to `verify_isolated_wheels.py` PACKAGES. The
`atlas-richie-cache` aggregator (in `foundation/platform`) just
adds the new dependency.
