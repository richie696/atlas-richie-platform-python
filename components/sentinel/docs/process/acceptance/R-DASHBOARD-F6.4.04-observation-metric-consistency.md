# F6.4.04 — Cross-page observation metric consistency

Status: **slice complete** (2026-10-08). F6.4 remains open.

## Risk-to-test matrix

| ID | Risk | Test boundary | Required assertion |
| --- | --- | --- | --- |
| OBS-SEED-01 | Fleet and realtime handlers report different values or coverage for the same scope. | Console transport + MSW + Fleet/metrics HTTP adapters. | Fleet and realtime bundles have identical values, quality, denominator, and coverage for each requested metric. |
| OBS-SEED-02 | Application QPS is duplicated instead of being supported by its process observations. | Console transport + MSW + Fleet/metrics/instance adapters. | Each app's QPS equals the sum of its registered process QPS; fleet QPS equals the app sum. |
| OBS-SEED-03 | Process detail reuses application aggregate QPS, or inventory omits a seeded app's process. | Instance catalog/detail and metrics adapters. | Process values match process seed facts, every seeded app has catalog coverage, and app aggregation is consistent. |
| OBS-SEED-04 | Unknown app/instance identity borrows another target's metric facts. | Metrics and instance HTTP adapters. | Unknown app returns `no_samples`; unknown instance remains an explicit not-found response. |
| OBS-SEED-05 | Changing one source silently breaks app/feature dependency ownership. | Typecheck, architecture, build-profile tests. | Seed remains app-owned; feature modules receive data by explicit factory input; live artifact excludes mock runtime. |

## Design boundary

The app-owned scenario is the only synthetic source of application and process identities and QPS facts. Application QPS is derived once from process QPS. Non-additive metrics such as p95 latency and ratios are explicit aggregate facts rather than averages of per-process percentiles. Fleet, realtime, and instance feature fixtures remain responsible for projecting their own query contracts; no feature imports app modules and no production metric policy is moved into a demo-only abstraction.

No GoF pattern is selected: this change has one fixed immutable dataset and deterministic projections, not competing implementations, runtime algorithm selection, or resource lifecycle coordination.

## Acceptance boundary

This slice proves consistency among current synthetic HTTP observations only. It does not prove Reporter ingestion, real inventory completeness, aggregation semantics of a production collector, Python Console integration, or browser E2E.

## Evidence and result

- `npm run test:logic`: **247/247 passed**; `npm run typecheck`: passed.
- `npm run check`: all component gates completed successfully, including format/lint/hooks, architecture **13/13**, logic **247/247**, HTTP **90/90**, OpenAPI contract tooling, browser/visual/i18n/verification tooling, production and demo builds, build profiles **2/2**, and Sites **4/4**. The production and demo builds retain the existing Zod PURE-comment and large initial-chunk warnings. The HTTP suite uses an isolated local loopback listener; no external service was contacted.
- Codex in-app browser (IAB), local Mock profile: fleet Overview showed **189 req/s**, p95 **63 ms**, blocked ratio **4%**, CPU **49%**, memory **50%**, with coverage **4/4**; Realtime showed the same values and coverage. Applications showed **4** registered processes with QPS **22 + 20 + 84 + 63**, grouped under all three apps; these sum to the same fleet/app values. The browser session used a synthetic Viewer identity only. No Chrome, Edge, or CDP was launched or connected.
- `git diff --check`: passed.

The test proves synthetic transport-level agreement and truthful missing-data coverage, not live collector semantics. F6.4 remains unchecked because other fixture families and scenario authority still need migration.
