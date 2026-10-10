# F6.4.16 Compose instance rule receipts from the publication scenario

Date: 2026-10-08

## Scope

Align the application/instance read model with the canonical rule publication and fleet coverage facts. The app composition layer is the only place that joins these scenarios; feature fixture code projects the supplied facts and does not invent versions or receipt states.

## Implementation

- Added `app/api/mockApplicationScenario.ts`, composing the canonical observation inventory and rule deployment scenario.
- The instance assigned the publication's applied receipt reports the event version as desired and applied. Other instances of the bound app remain pending on the event version while reporting the baseline version as applied. Instances of apps without a rule binding report unknown with no invented version.
- Overview `ruleCoverage` is derived from the composed instance receipts and the canonical instance inventory: expected is the app's instance count, reporting is the number confirmed on the desired rule version.
- Instance fixture projection now consumes scenario receipts. The architecture check rejects reintroducing hardcoded `version-one`/applied receipt facts into the feature-owned projection.
- HTTP tests verify both the overview denominator/coverage and the application endpoint's per-instance receipt status against the shared scenario.

## Verification

- `npm run typecheck`: passed.
- `npm run test:architecture`: **15/15** passed.
- `npm run test:logic`: **253/253** passed.
- `npm run test:http`: **100/100** passed, including controlled local-loopback HTTP coverage.
- Full `npm run check`: **exit 0**, including formatting, lint, architecture/logic/HTTP/contract/tool checks, i18n, production/demo builds, build profiles, and Sites tests. This command does not run browser E2E.
- Codex IAB verified the Overview coverage and application detail flow: instance-1 displays “当前进程已加载 · version-event-flow / version-event-flow”; instance-2 displays “等待当前进程加载 · version-one / version-event-flow”. No Chrome, Edge, or CDP was launched or used.
- No Python Console, real database, Nacos, Consul, or external service was accessed.

## Status boundary

This is one cross-page Mock seed consistency slice, not completion of F6.4. Remaining seed families and full product E2E remain open; these tests do not prove Python backend or real source integration.
