# F6.4.17 Centralize deterministic demo time-series profiles

Date: 2026-10-08

Status: slice complete; F6.4 remains open.

## Requirement and risk

F6.4 requires chart/curve demo facts to have one app-owned seed source and to remain consistent with summary readings. The current mock projection repeats each summary as a flat line with an artificial midpoint gap. That makes a chart look like a measured history while not providing any scenario-owned curve facts.

This slice will add immutable relative profiles to `MOCK_OBSERVATION_SCENARIO`, project them at the request's actual window/step, and preserve the final summary value, source, coverage, and unavailable TPS semantics. Profiles are explicitly synthetic and used only by the opt-in Mock handlers.

## Implementation

- Added frozen profiles for QPS, p95, blocked ratio, CPU, and memory to the app-owned observation scenario; feature projections now consume these profiles instead of defining curve samples themselves.
- `metricBundleFromFacts` interpolates the scenario shape across the validated query step, caps output at `MAX_OBSERVATION_POINTS`, keeps samples in the half-open UTC window, and aligns `sampledAtMs` with the final point. Every profile ends at its summary value; unavailable metrics still return no points.
- Added architecture coverage preventing feature observation projections from defining their own profile seed.
- The change affects only deterministic demo projections. Real HTTP adapters still decode the server's exact series unchanged.

## Test matrix

| ID | Layer | Action | Assertions |
| --- | --- | --- | --- |
| F6.4.17-1 | Logic | Project the same scenario and query twice | Identical ordered points, non-flat profile, last point equals the summary value |
| F6.4.17-2 | Logic | Query varied window/step and missing metrics | Points stay within the half-open window, count is bounded by `MAX_OBSERVATION_POINTS`, and missing/TPS readings remain unavailable with empty series |
| F6.4.17-3 | HTTP | Read fleet/application/instance/realtime metrics through MSW + the real HTTP adapters | Each response carries scenario-derived curves, preserves scope-specific summary/coverage and publication annotations, and validates against the wire schema |
| F6.4.17-4 | Architecture | Scan seed ownership and feature projection boundaries | Profile values exist only in the app-owned scenario; feature projections do not define duplicate demo curves |
| F6.4.17-5 | Rendered UI | Inspect the explicitly labeled demo chart in Codex IAB | Chart renders an actual varying line with the selected range; do not call Chrome/Edge/CDP or claim Python/live integration |

## Results

- `npm run typecheck`: passed.
- `npm run test:architecture`: **16/16** passed.
- `npm run test:logic`: **254/254** passed.
- `npm run test:http`: **100/100** passed, including loopback-only controlled HTTP tests.
- Full `npm run check`: **exit 0**; includes format, lint, all logic/HTTP/contract/tool suites, i18n, production/demo builds, build-profile **3/3**, and Sites **4/4**. It does not run `test:e2e`.
- Codex IAB rendered the demo real-time route. The QPS, p95, blocked-ratio, CPU, and memory cards showed **60/60** samples; visual inspection confirmed the QPS, p95, CPU, and memory lines vary rather than render as flat summary repetitions. The page identifies its data as synthetic demo data. No Chrome, Edge, or CDP was used.

## Acceptance boundary

Passing this slice closes only the demo curve seed/projection issue. It does not prove real Collector history, browser automation E2E, or Python Console integration. No real database/configuration center is in scope. Existing production/demo bundle warning remains: a JavaScript chunk exceeds 500 kB; this slice does not adjust the threshold or claim bundle optimization.
