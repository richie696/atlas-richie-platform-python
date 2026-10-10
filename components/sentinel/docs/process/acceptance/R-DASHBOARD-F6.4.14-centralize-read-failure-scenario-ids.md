# F6.4.14 Centralize read-failure Mock scenario identities

Date: 2026-10-08

## Scope

Centralize reserved application IDs used by fleet and realtime HTTP Mock failure/recovery probes. These identifiers describe opt-in test/demo scenarios, not real applications, and belong to the app-owned `MOCK_OBSERVATION_SCENARIO`. Feature handlers consume them as scenario input; tests read them from the same canonical source.

Add an architecture check that enforces two ownership rules:

1. Feature fixture modules are imported only by that feature's explicit `mock.ts` entry.
2. Reserved read-scenario IDs occur only in `app/api/mockObservationScenario.ts`.

## Implementation

- Moved the fleet forbidden/recovery and metrics recovery/retry application IDs into `MOCK_OBSERVATION_SCENARIO.readScenarios`.
- Fleet and realtime fixture handler factories now use the injected scenario; feature mock entry points no longer export their own copies of those IDs.
- HTTP tests use IDs from the app-owned scenario.
- `workflow-ownership.test.mjs` scans actual source imports and seed occurrences, preventing feature/UI source from acquiring fixture ownership or redefining these scenario identities.

## Verification

- `npm run typecheck`: passed.
- `npm run test:architecture`: passed, including the new F6.4 ownership assertion.
- `npm run test:logic`: 253/253 passed.
- `npm run test:http`: 99/99 passed when the existing controlled loopback tests were allowed to bind only to `127.0.0.1`; the default sandbox run had the known `listen EPERM` on those tests.
- No browser E2E was run. No Chrome, Edge, CDP, Python Console, database, Nacos, Consul, or external service was used.

## Status boundary

This closes only the reserved read-failure scenario-ID ownership slice. It does not complete F6.4's full seed inventory, nor prove live backend behavior or browser E2E.
