# R-228 Handoff: Centralized version management (`versions.toml`)

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DONE** — single `versions.toml` at repo root is the
canonical source of truth; `tools/sync_versions.py` propagates
every change into all 15 `pyproject.toml` files (own `version` +
cross-component dependency constraints).

## Motivation

Before R-228, every `pyproject.toml` carried its own `version = "0.1.0"`
and the inter-component dependencies were written inline as
`"atlas-richie-cache-core>=0.1.0,<0.2.0"` (or, on some adapter
packages, just `"atlas-richie-mcp"` with a separate
`[tool.uv.sources]` workspace mapping).

Bumping a single package required editing **at least three** files
(one for the package's own `version`, plus 2+ for downstream
consumers that reference it). Skipping a single file left the
workspace inconsistent. Maven solves this with `<revision>` in
the parent POM; Python + uv has no native equivalent, so we
implemented one.

## The model

```text
versions.toml                 (single source of truth)
    │
    ▼
tools/sync_versions.py        (one-shot propagation)
    │
    ├──▶ foundation/contracts/pyproject.toml
    │       project.version = "0.1.0"  (from versions.toml)
    │       dependencies = ["atlas-richie-...>=0.1.0,<0.2.0", ...]
    │
    ├──▶ foundation/platform/pyproject.toml
    │       project.version = "0.1.0"
    │       dependencies = ["atlas-richie-contracts>=0.1.0,<0.2.0", ...]
    │
    └──▶ ... (15 files total)
```

Bumping workflow:

```bash
# 1. edit versions.toml
sed -i '' 's/0.1.0/0.2.0/g' versions.toml

# 2. propagate
python tools/sync_versions.py

# 3. verify no drift
python tools/sync_versions.py --check
# → "OK: all pyproject.toml files are in sync with versions.toml"

# 4. build + test + publish
uv build --wheel --no-index --out-dir dist/ ...
python tools/release/verify_isolated_wheels.py
```

## What's in `versions.toml`

```toml
[versions]
atlas-richie-contracts              = "0.1.0"
atlas-richie-testing                = "0.1.0"
atlas-richie-platform               = "0.1.0"
atlas-richie-http                   = "0.1.0"
atlas-richie-mcp                    = "0.1.0"
atlas-richie-oauth                  = "0.1.0"
atlas-richie-resilience             = "0.1.0"
atlas-richie-cache-core             = "0.1.0"
atlas-richie-cache-redis            = "0.1.0"
atlas-richie-oauth-jose             = "0.1.0"
atlas-richie-mcp-schema-jsonschema  = "0.1.0"
atlas-richie-mcp-asgi               = "0.1.0"
atlas-richie-mcp-oauth              = "0.1.0"
atlas-richie-mcp-http               = "0.1.0"
atlas-richie-mcp-legacy             = "0.1.0"
```

15 packages, all currently at `0.1.0`. The script is the only
writer to `pyproject.toml` files, so the value is single-tracked
through `versions.toml`.

## How `tools/sync_versions.py` works

The script:

1. Reads `versions.toml` and validates every version is
   semver (`\d+\.\d+\.\d+`).
2. Discovers every `pyproject.toml` under the repo (skipping
   `.venv`, `dist`, `node_modules`, `.git`, `__pycache__`).
3. For each `pyproject.toml`:
   - Reads `project.name` and `project.version` via `tomllib`.
   - Skips files without a `[project] name` (the root workspace
     aggregator).
   - Updates the OWN `version = "X.Y.Z"` line via a precise
     text-regex (NOT `tomllib` round-trip — see trade-off below).
   - Updates every `atlas-richie-*` entry in `project.dependencies`
     to `>=X.Y.Z,<X.(Y+1).0` (the standard Python
     "compatible-release" form).
4. Verifies that every `atlas-richie-*` package referenced in any
   `pyproject.toml` is declared in `versions.toml`. Missing entries
   fail loudly with a clear error.

The `--check` flag turns the script into a CI gate: it walks all
the same files but exits non-zero (1) if any drift is detected.
Run it from `.github/workflows/ci.yml` or as a pre-commit hook.

## Trade-offs and what we learned

### Why NOT `tomllib` + `tomli_w`

The first implementation used `tomllib.loads` + `tomli_w.dumps` for
the round-trip. It looked clean. It also:

1. **Lost the `[tool.uv.build-backend]` table** on every file.
   tomli_w re-emits dotted keys as nested sub-tables, but our
   `[tool.uv.build-backend]` table header uses a dash in the last
   segment (`build-backend`) which tomli_w handled inconsistently
   across versions. The result: `module-name` and `module-root`
   became top-level keys on 7 of the 15 files, breaking
   `uv build --wheel` with `Expected a Python module at: ...` errors.
2. **Lost comments** (acceptable — pyproject.toml files rarely have
   meaningful comments in this repo).
3. **Lost blank-line formatting** (acceptable — easy to re-apply
   via a formatter).

The fix: a **targeted text-manipulation** approach that touches
only the `version = "..."` line inside `[project]` and the
`dependencies = [...]` array. Everything else is byte-preserved.

### Why bare-name deps got rewritten to `>=0.1.0,<0.2.0`

Before R-228, some adapter packages used bare names like
`dependencies = ["atlas-richie-mcp"]` with a separate
`[tool.uv.sources] atlas-richie-mcp = { workspace = true }`. This
works inside the workspace (uv resolves the workspace member
regardless of constraints) but is **wrong for the published wheel**:
an external consumer would have no version constraint, so `pip
install atlas-richie-mcp-asgi` would fail to resolve
`atlas-richie-mcp` at all.

The sync script now rewrites every bare-name `atlas-richie-*` dep
to the canonical `>=X.Y.Z,<X.(Y+1).0` form. The `[tool.uv.sources]`
workspace mapping is preserved untouched (it still helps inside
the workspace) but the published wheel's `METADATA` is now
self-sufficient.

## Files changed

| File | Change |
|---|---|
| `versions.toml` | **new** — 15 package → version mappings |
| `tools/sync_versions.py` | **new** — sync script (~250 lines, 0 deps beyond `tomllib`) |
| `foundation/contracts/pyproject.toml` | already correct (no change) |
| `foundation/platform/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `foundation/testing/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `components/oauth/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `components/mcp/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `components/resilience/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `components/http/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `components/cache/cache-core/pyproject.toml` | rewritten (manual restore from corruption) |
| `components/cache/cache-redis/pyproject.toml` | rewritten (manual restore from corruption) |
| `adapters/oauth-jose/pyproject.toml` | synced + restored `[tool.uv.build-backend]` |
| `adapters/mcp-asgi/pyproject.toml` | synced |
| `adapters/mcp-oauth/pyproject.toml` | synced |
| `adapters/mcp-http/pyproject.toml` | synced |
| `adapters/mcp-legacy/pyproject.toml` | synced |
| `adapters/mcp-schema-jsonschema/pyproject.toml` | synced |

## Review gate

- ✅ `python tools/sync_versions.py` — first run rewrote 9 files
  (5 already correct, 4 needed version constraints added); second
  run is a no-op.
- ✅ `python tools/sync_versions.py --check` — "OK: all pyproject.toml
  files are in sync with versions.toml"
- ✅ `uv build --wheel` for `cache-core` + `cache-redis` + `platform` —
  3 new wheels
- ✅ `pytest components/cache/cache-core/tests/ components/cache/cache-redis/tests/` — **369 passed + 4 skipped** in 26.70s
- ✅ `tools/release/verify_isolated_wheels.py` — 14 packages install in
  fresh venv, no broken requirements, `import atlas_richie.platform` succeeds

## Recommended CI integration

Add to `.github/workflows/ci.yml` (or pre-commit):

```yaml
- name: Check versions.toml sync
  run: python tools/sync_versions.py --check
```

This will fail the build if anyone bumps a version in a single
`pyproject.toml` without updating `versions.toml` + running the
sync.
