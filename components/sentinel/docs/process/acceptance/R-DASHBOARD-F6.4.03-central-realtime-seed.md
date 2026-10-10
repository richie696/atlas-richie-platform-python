# F6.4.03 — Align Realtime Mock Metrics with the App-Owned Scenario

Status: **slice complete** (2026-10-08). F6.4 remains open.

## Test design

| ID | Priority | Action | Required assertion |
| --- | --- | --- | --- |
| RT-SEED-01 | P1 | Read fleet-scope realtime metrics through MSW and the real Console HTTP adapter. | Environment uses the app scenario; aggregate QPS equals the sum of registered app QPS values. |
| RT-SEED-02 | P1 | Read realtime metrics for each registered application. | QPS equals the fleet/instance scenario's value; app-one annotation identity is the scenario's declared identity. |
| RT-SEED-03 | P1 | Read metrics for an unknown application. | No QPS is borrowed from another app; value/sample time are null and quality is `no_samples`. |
| RT-SEED-04 | P1 | Exercise transient and retryable mock failures. | The first response follows the existing failure sequence; successful later reads do not fabricate an unknown app's metrics. |
| RT-SEED-05 | P1 | Inspect dependency graph/build profile. | Realtime feature receives scenario by argument, imports no app module; live artifact still excludes MSW. |

## Evidence

- Realtime handler factory receives the app-owned `MockObservationScenario`; fleet QPS is derived from the registered applications rather than a duplicate realtime fixture. Registered apps return their declared QPS and annotation identity; unknown apps return `no_samples` with null value/sample time.
- HTTP contract tests cover fleet aggregation, app-two QPS (`84`), unknown-app isolation, and synthetic transient failures. Typecheck, Prettier, ESLint, architecture tests, logic tests, HTTP tests (including the isolated loopback transport), i18n/contract/tooling checks, production/demo builds, build profiles, and Sites worker tests passed through `npm run check`.
- Codex in-app browser smoke on the demo/mock application route `#/realtime?env=test-env&app=app-two` rendered the selected app and `HTTP QPS 84 req/s`. No Chrome, Edge, or CDP was launched or connected.
- Build output retains the existing Zod PURE annotation and large initial-chunk warnings; these did not fail the build.

## Acceptance boundary

The slice proves realtime observation seed consistency only. It is not live Python/backend evidence and does not prove browser E2E automation. Other realtime UI fixture modules and the remaining rules, identity, faults, system, health, plan, version, and chart seeds stay in scope for F6.4 follow-up.
