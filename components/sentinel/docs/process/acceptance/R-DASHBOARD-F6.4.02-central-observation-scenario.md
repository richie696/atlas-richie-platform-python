# F6.4.02 — Centralize the Observation Demo Scenario

Status: **slice complete** (2026-10-08). F6.4 remains open.

## Scope

Make the application assembly the single owner of the mock environment, application inventory, observation window, and per-application QPS values used by the fleet and instance HTTP mock paths. Feature mock builders receive those facts as explicit inputs; they must not import application assembly or invent conflicting catalog facts.

This slice does not centralize rule, identity, incident, system, or realtime-only seed facts and does not close F6.4. It does not change live HTTP behavior or call an external service.

## Test and acceptance design

| Case | Evidence required |
| --- | --- |
| Catalog identity | Observation catalog and fleet/instance snapshots use the same environment and application IDs. |
| Time consistency | Default fleet and instance observation queries use the same immutable UTC window. |
| Metric consistency | For every application represented by instance observations, its fleet QPS agrees with the corresponding instance observation QPS. |
| Query integrity | Existing filtering, pagination, unsupported-scope, and wire-schema tests remain green after dependency injection. |
| Ownership | App assembly supplies the scenario to handler factories; feature code has no import from `src/app`. |

Run the focused logic and HTTP suites and the architecture check. If a visual check is needed, use only the Codex in-app browser; Chrome, Edge, and CDP are out of scope.

## Acceptance boundary

Passing these checks proves consistency only for the fleet/instance observation demo scenario. It is not evidence for the remaining F6.4 seed families, full browser E2E, Python Console integration, or live mode.

## Evidence

- The application assembly now owns the shared `test-env`, application catalog, UTC demo window, per-application QPS, and instance identities. Fleet and instance mock-handler factories receive that scenario explicitly; feature source does not import the app assembly.
- The aggregate fleet QPS is now derived as 189 from the three application QPS values (42 + 84 + 63). Instance observations for app-one/app-two use the same per-application values. Unknown application targets return explicit `no_samples` metric readings rather than borrowing app-one's QPS.
- Automated checks passed: typecheck; logic **247/247**; HTTP **89/89** (including isolated local loopback transport); architecture **13/13**; format and lint; production and demo builds; build-profile **2/2**; Sites worker **4/4**.
- Codex in-app browser rendered `#/overview` with 189 req/s and `#/applications?env=test-env&app=app-one` with two app-one instances each at 42 req/s. No Chrome, Edge, or CDP was launched or connected.
- Builds retain the existing Zod pure-annotation warnings and approximately 1.19 MB initial JavaScript chunk warning.
- Remaining: rules, identity, faults, system, realtime, health/plan/version and other fixture seeds are not yet centrally migrated. This slice does not prove browser E2E or Python/live integration.
