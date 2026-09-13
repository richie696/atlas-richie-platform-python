# atlas-richie-sentinel-source-nacos

Nacos-based rule source for Atlas Richie Sentinel. Loads Flow / Degrade
/ ParamFlow / System / Authority rules from Nacos config center with
polling refresh; implements the new `SnapshotRuleSource` contract,
plugged in via the main package's `assemble_sources` entry.

Part of the **Atlas Richie Sentinel** family — the Python equivalent of
Alibaba Sentinel + Resilience4j.

## Status

**M6.1.7 — Nacos 3.x polling implementation.** `NacosRuleSource` uses
the async `nacos-sdk-python` 3.x API, with a bounded polling loop as its
correctness path, 5-way error classification, and idempotent `aclose()`.

| Sub-task | Status |
| -------- | ------ |
| M6.1.1 wheel scaffold + workspace | ✅ done |
| M6.1.2 `NacosRuleSourceConfig` frozen dataclass + value objects | ✅ done |
| M6.1.3 lifecycle (first read → poll → yield) | ✅ done |
| M6.1.4 error classification + last-known-good + backoff | ✅ done |
| M6.1.5 idempotent `aclose()` + redaction | ✅ done |
| M6.1.6 contract suite + Nacos tests | ✅ done |
| M6.1.7 Nacos 3.x SDK + polling | ✅ done |

## Dependency isolation (M6.1.1 hard constraint)

- Only this wheel declares `nacos-sdk-python>=3.0,<4.0`.
- Main package / ASGI / HTTPX / Dashboard dependency graph is
  **unchanged** (main package remains zero 3rd-party).
- `rg "nacos" components/sentinel/sentinel/src/` must return empty
  (extension isolation proof).

## C-layer isolation (M6.1.0 P0 decision 1)

- This extension does **not** import main-package
  `atlas_richie.sentinel.source._supervisor.*`.
- Test enforces: any `__module__` of attributes exported from
  `atlas_richie.sentinel_source_nacos` MUST NOT start with
  `atlas_richie.sentinel.source._supervisor`.

## Install

```bash
uv add atlas-richie-sentinel-source-nacos
```

## Usage

```python
import asyncio
from datetime import timedelta

from atlas_richie.sentinel_source_nacos import (
    NacosRuleSource,
    NacosRuleSourceConfig,
    NacosAuth,
    NacosTLS,
)
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.source.rule_source import RuleSourceAssembly


async def main() -> None:
    # 1) Nacos source config (frozen dataclass; required fields no defaults)
    config = NacosRuleSourceConfig(
        source_id="nacos-prod",
        server_addresses=("nacos-1.example.com:8848", "nacos-2.example.com:8848"),
        namespace="sentinel-prod",
        group="DEFAULT_GROUP",
        data_id_prefix="sentinel-rules",
        auth=NacosAuth(username="sentinel", password="***"),  # or None
        # tls=NacosTLS(ca="-----BEGIN CA...", cert=..., key=...),
        connect_timeout=timedelta(seconds=3),
        read_timeout=timedelta(seconds=10),
        reconnect_initial=timedelta(seconds=1),
        reconnect_max=timedelta(seconds=30),
    )

    # 2) Nacos source — implements SnapshotRuleSource Protocol
    source = NacosRuleSource(config)

    # 3) Plug into the engine's multi-source arbitration
    engine = SentinelEngine()
    repo = RuleRepository()
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

    # 4) On shutdown: aclose() is idempotent and never raises
    await source.aclose()


asyncio.run(main())
```

### 5 data-id convention

The wheel reads 5 Nacos data-ids, derived from `data_id_prefix`:

| Rule type   | data-id (Java sentinel-datasource-nacos 1:1) |
| ----------- | --------------------------------------------- |
| flow        | `<data_id_prefix>-flow-rules.json`            |
| degrade     | `<data_id_prefix>-degrade-rules.json`         |
| param_flow  | `<data_id_prefix>-param-flow-rules.json`      |
| system      | `<data_id_prefix>-system-rules.json`          |
| authority   | `<data_id_prefix>-authority-rules.json`       |

Use `config.data_id_for(rule_type)` to get the exact data-id string.

### Lifecycle (M6.1.3)

1. `NacosRuleSource(config).__init__` — validates config; state =
   `CONNECTING`; SDK client **not** yet constructed (lazy).
2. `async for snap in source.snapshots():` first `__anext__` triggers:
   pull 5 data-ids → decode → yield first `RuleSnapshot` → state =
   `READY` (or `STALE` on partial success).
3. Start one bounded polling task. Each tick reads the five data-ids,
   compares the combined checksum with the last delivered snapshot, and
   wakes the iterator only on change.
4. On a changed poll result: re-decode → yield new
   `RuleSnapshot` with updated `RuleVersion`.
5. `aclose()` cancels the polling task, shuts down the SDK client, and
   transitions to `CLOSED`. Idempotent.

### Error classification (M6.1.4)

| Error       | Trigger                                    | Recovery                          | State              |
| ----------- | ------------------------------------------ | --------------------------------- | ------------------ |
| `AUTH`      | 401/403 / SDK `NacosException`             | **No auto-retry**; await human    | `DISCONNECTED`     |
| `NOT_FOUND` | `get_config` returns `None` (404)          | last-known-good preserved         | `STALE`            |
| `EMPTY`     | `""` / `b""` / `"[]"` / `"null"` content  | last-known-good preserved         | `STALE`            |
| `DECODE`    | JSON parse / field missing / type wrong    | last-known-good preserved         | `STALE`            |
| `NETWORK`   | connection refused / timeout / DNS failure | bounded exponential backoff       | `DISCONNECTED`     |

Errors **do not** yield a new `RuleSnapshot` (last-known-good is
preserved in the caller-side `RuleRepository`).

### Observability (operator)

```python
source.state                    # current NacosSourceState
source.last_success_version     # RuleVersion | None
source.last_error               # NacosSourceError | None
source.last_error_message       # redacted str | None
source.error_count(NacosSourceError.NETWORK)  # per-type cumulative count
```

### Redaction (M6.1.5)

`last_error_message` and all `logger.warning(...)` calls go through the
`_redact` helper, which masks:

- `server_addresses` (entire tuple not exposed; `host:port` →
  `***:***`)
- `namespace`, `username`, `password`, `token`, `accessKey`,
  `secretKey`, `cert`, `key` (key=value / key:value → `***`)

The `_redact` helper is also exposed at module level for extension
tests.

## Tests

```bash
# 112 passed, 1 skipped (real Nacos)
pytest components/sentinel/sentinel-source-nacos/tests/ -q
```

The skipped test is the M6.1 real-service validation (5 scenarios via
testcontainers / docker-compose), scheduled for M6.1.

## See also

- `components/sentinel/docs/MIGRATION-M6.md` — 1.0 → 1.x migration
- `components/sentinel/docs/EXTENSION_GUIDE.md` §3 — extension author guide
- `components/sentinel/docs/PLANNING.md` §M6.1 — Nacos source roadmap
- `components/sentinel/docs/DESIGN.md` §10 — RuleSource architecture
