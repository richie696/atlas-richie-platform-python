# atlas-richie-sentinel-source-nacos

Nacos-based rule source for Atlas Richie Sentinel. Loads Flow / Degrade
/ ParamFlow / System / Authority rules from Nacos config center with
long-poll refresh; implements the new `SnapshotRuleSource` contract,
plugged in via the main package's `assemble_sources` entry.

Part of the **Atlas Richie Sentinel** family — the Python equivalent of
Alibaba Sentinel + Resilience4j.

## Status

**M6.1.1 — wheel scaffold in progress.** The wheel, package, and
pyproject are in place; the actual `NacosRuleSource` implementation is
scheduled for M6.1.2 - M6.1.5 (config / lifecycle / error classification
/ aclose). Contract tests land in M6.1.6.

| Sub-task | Status |
| -------- | ------ |
| M6.1.1 wheel scaffold + workspace | ✅ done |
| M6.1.2 `NacosRuleSourceConfig` frozen dataclass | ⏳ |
| M6.1.3 lifecycle (first read → publish → subscribe) | ⏳ |
| M6.1.4 error classification + last-known-good | ⏳ |
| M6.1.5 idempotent `aclose()` | ⏳ |
| M6.1.6 contract suite + Nacos tests | ⏳ |
| M6.1 real-service validation (5 scenarios) | ⏳ |

## Dependency isolation (M6.1.1 hard constraint)

- Only this wheel declares `nacos-sdk-python>=2.0,<3.0`.
- Main package / ASGI / HTTPX / Dashboard dependency graph is
  **unchanged** (main package remains zero 3rd-party).
- `rg "nacos" components/sentinel/sentinel/src/` must return empty
  (extension isolation proof).

## Install

```bash
uv add atlas-richie-sentinel-source-nacos
```

## Usage (planned, available after M6.1.5)

```python
from atlas_richie.sentinel_source_nacos import (
    NacosRuleSource, NacosRuleSourceConfig,
)
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.rules.repository import RuleRepository
from datetime import timedelta

config = NacosRuleSourceConfig(
    source_id="nacos-prod",
    server_addresses=("nacos-1.example.com:8848", "nacos-2.example.com:8848"),
    namespace="sentinel-prod",
    group="DEFAULT_GROUP",
    data_id_prefix="sentinel-rules",
    username=None,  # or NacosAuth.basic("user", "pass") for auth
    tls=None,       # or NacosTLS(ca=..., cert=..., key=...) for mTLS
    connect_timeout=timedelta(seconds=3),
    read_timeout=timedelta(seconds=10),
    reconnect_initial=timedelta(seconds=1),
    reconnect_max=timedelta(seconds=30),
)

engine = SentinelEngine()
repo = RuleRepository()
source = NacosRuleSource(config)

await engine.assemble_sources(
    [
        RuleSourceAssembly(
            source=source,
            priority=100,
            failover_after=timedelta(seconds=5),
        ),
    ],
    repository=repo,
)
```

## See also

- `components/sentinel/docs/MIGRATION-M6.md` — 1.0 → 1.x migration
- `components/sentinel/docs/EXTENSION_GUIDE.md` §3 — extension author guide
- `components/sentinel/docs/PLANNING.md` §M6.1 — Nacos source roadmap
- `components/sentinel/docs/DESIGN.md` §10 — RuleSource architecture
