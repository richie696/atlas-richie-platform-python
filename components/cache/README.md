# atlas-richie-cache (parent — aggregator only)

This directory is a **pure aggregator** for the `atlas-richie-cache*`
family of Python packages. It has **no source code** and is **not a
buildable wheel** — it just lists the child packages and points the
IDE / tooling at them.

## Children

| Path | Wheel | Source |
|---|---|---|
| [`cache-core`](cache-core) | `atlas-richie-cache-core` | `atlas_richie.cache_core` — framework, contracts, static facades, holders, shared utilities, local cache |
| [`cache-redis`](cache-redis) | `atlas-richie-cache-redis` | `atlas_richie.cache_redis` — Redis backend (Lua-atomic lock / bounded queue / bounded stack / bloom / snowflake / L2 fan-out / pub-sub) |

Future backends (Dragonfly, KeyDB, ...) will land as siblings of
`redis/`, e.g. `dragonfly/cache-dragonfly/`. The aggregator grows
sideways, not downwards — each backend is independent and only
shares the framework contracts from `core/`.

## Workspace layout

The repo-root `pyproject.toml` lists the subdirs directly under
`[tool.uv.workspace].members`. There is no nested `cache/`-level
workspace because `uv` does not support nested workspaces — every
package belongs to exactly one workspace.

Import paths and wheel names are stable: callers write
`from atlas_richie.cache_core import ...` and
`from atlas_richie.cache_redis import ...` regardless of where the
code lives on disk.
