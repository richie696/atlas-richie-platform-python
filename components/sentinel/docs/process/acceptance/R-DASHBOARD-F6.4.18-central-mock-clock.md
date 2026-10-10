# F6.4.18 Centralize the demo runtime clock

Date: 2026-10-09

Status: slice complete; F6.4 remains open.

## Requirement and risk

F6.4 calls for one app-owned clock for Mock responses. Reading `Date.now()` independently in handlers made otherwise related snapshots depend on request timing and complicated deterministic replay.

## Implementation

- Added `MOCK_SCENARIO_NOW_MS`, sampled once when the explicit demo Mock assembly loads. The assembly exposes it to handlers through one `mockClock` function.
- Injected that clock into application catalog, incident timeline/evidence, rule-set, system-observation, and source-registration handlers. Test-created application and incident handler factories may still receive their own clock for isolation.
- Kept query-derived metric and instance sample times tied to the requested window; the shared clock is for response/operation observation timestamps, not a replacement for sample time.
- Added an HTTP-level test through the app's assembled MSW registry proving application catalog, system connection, and incident timeline timestamps use the same captured instant.
- The observation consistency HTTP test now explicitly retries the designated synthetic one-shot `503` and resets that handler state around the test, so its consistency assertions do not fail on the demo recovery scenario.
- Removed two obsolete recovery-seed identifiers from the F6.4 architecture guard; neither identifier exists in the current app-owned scenario.

## Test matrix

| ID        | Layer  | Action                                                                                                      | Assertions                                                                                              |
| --------- | ------ | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| F6.4.18-1 | HTTP   | Read application catalog, system connection snapshot, and incident timeline through assembled Mock handlers | All response observation timestamps equal the single app-owned Mock instant                             |
| F6.4.18-2 | HTTP   | Run observation coherence with a configured transient Mock failure                                          | The bounded retry recovers; metric facts remain consistent across fleet/application/process projections |
| F6.4.18-3 | Static | Run frontend fast gate                                                                                      | TypeScript, formatting, lint, and OpenAPI contract remain valid                                         |

## Results

- Focused command: `npm run test:http:focused -- 'MOCK-CLOCK-HTTP|OBSERVATION-SEED-CONSISTENCY|INCIDENT-MOCK|INSTANCE-MOCK'` — **7/7 passed**.
- `npm run test:architecture` — **16/16 passed**.
- `npm run check:fast` — passed.

## Acceptance boundary

This closes only Mock response-clock consistency for the listed handlers. It does not close the full F6.4 seed inventory, page E2E, Python Console integration, or real service behavior. No browser, Python Console, database, configuration center, or external service was used.
