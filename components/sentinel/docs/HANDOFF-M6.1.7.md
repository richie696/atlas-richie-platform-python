# R-SENTINEL-M6.1.7 HANDOFF — Nacos 3.x SDK + Polling

> **Verified state, 2026-09-13.** This document supersedes the earlier
> conclusion that Nacos 3.2.3 could not be used with SDK 3.2.0.

| Field | Verified value |
| --- | --- |
| SDK / server | `nacos-sdk-python==3.2.0` / Nacos `3.2.3` |
| Source refresh model | SDK async config API plus bounded polling; listener push is not a correctness dependency |
| Public API | `NacosRuleSourceConfig.poll_interval` (default 1s, minimum 100ms); existing source protocol unchanged |
| Real acceptance | All five scenarios passed against local Docker `nacos-pg-3.2.3` |
| Container after test | Restored and running |

## What is implemented

- SDK API uses `v2.nacos`, `ClientConfigBuilder`, `GRPCConfig(port_offset=1000)`,
  and `NacosConfigService`.
- The adapter disables SDK startup/fail-over config cache. Nacos remains the
  control-plane authority for rules.
- `snapshots()` yields the initial snapshot and then a polling task fetches the
  five rule data-ids. A changed checksum is stored as pending; the public
  `last_success_version` advances only immediately before the caller receives
  that snapshot.
- Nacos SDK failures are classified by semantics:
  - credential refusal: `AUTH`, no automatic retry;
  - absent/empty configuration: `NOT_FOUND` / `EMPTY`, source becomes `STALE`;
  - invalid rule JSON/schema: `DECODE`, last-known-good remains intact;
  - disconnected gRPC client (`-401` with `UNHEALTHY`) and server-side `5xx`:
    `NETWORK`, bounded retry and private SDK service reconstruction.
- A real-suite readiness probe now performs an authenticated, side-effect-free
  config read. It does not mistake an open TCP port during Nacos startup for a
  usable control plane.

## Real Nacos 3.2.3 evidence

Run from `components/sentinel/sentinel-source-nacos`:

```bash
.venv/bin/python -m pytest tests/integration/ -m integration -vv
```

The verified run completed all five scenarios:

1. Initial load returns a Flow rule from Nacos.
2. A second client publishes v2; polling yields a distinct v2 snapshot.
3. Invalid JSON increments `DECODE`, keeps the v1 version, and enters `STALE`.
4. `docker stop` causes `NETWORK`; after `docker start`, a reconstructed SDK
   client accepts a v2 publish and the source yields the new rule.
5. `aclose()` is idempotent and stops the iterator.

Focused package regression:

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration
```

## Remaining third-party warning

The final five-scenario run shut down cleanly; it did not emit a gRPC pending-
task warning. The only warning is `nacos-sdk-python`'s Pydantic 2 deprecation
notice for its class-based model configuration. It does not affect the rule
source lifecycle. Track it when upgrading the SDK, but do not replace the
official SDK or alter the component's behavior solely to suppress it.

## Relevant commits

- `ae15740` — SDK 3.2.0 and polling implementation.
- `713b118` — real integration suite and initial handoff.
- `de8d6aa` — extension and operations documentation.
- `30951cc` — original polling-state correction.

The follow-up verification fixes in the working tree should be committed with
this handoff update as one scoped M6.1.7 correction.
