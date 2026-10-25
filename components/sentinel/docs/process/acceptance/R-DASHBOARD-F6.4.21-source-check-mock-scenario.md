# F6.4.21 Centralize configuration-source check Mock facts

Date: 2026-10-09

Status: slice complete; F6.4 remains open.

## Test matrix

| ID | Layer | Action | Assertions |
| --- | --- | --- | --- |
| F6.4.21-1 | HTTP | Check a configured source through the Console HTTP adapter and MSW | Reachable result exposes the app scenario's capability set and does not mutate source registry |
| F6.4.21-2 | HTTP | Check the scenario's designated synthetic unavailable endpoint | Unreachable result and validity window are scenario-driven |
| F6.4.21-3 | Architecture | Inspect app scenario/model ownership and source-registration handler | Hostname/capabilities/validity facts are not duplicated in the feature fixture; app imports a non-UI model entry |

## Implementation

- Added `sourceCheck` to the app-owned `MOCK_SYSTEM_SCENARIO`, containing the synthetic unavailable hostname, result validity window, and supported capability values.
- The primary connection and successful source-check response share one scenario-owned capability array.
- `createSourceRegistrationMockHandlers` now requires the source-check scenario rather than embedding those demo facts in the handler.
- Added a small `features/system/model.ts` public vocabulary entry so app scenario assembly does not deep-import the feature's private model directory or include system UI.
- Extended the HTTP test with the unavailable case and the architecture guard with source-check seed ownership constraints.

## Verification

- `npm run test:http:focused -- 'SOURCE-MOCK-CHECK'`: **2/2 passed**.
- `npm run test:architecture`: **16/16 passed**.
- `npm run check:fast`: passed (typecheck, source formatting, lint, generated OpenAPI consistency).
- Prettier check and `git diff --check`: passed.
- Full milestone checks and browser E2E were intentionally not run.

## Acceptance boundary

This closes only the configuration-source check demo-fact slice. The mutable source registration/revision sequence is runtime Mock state, not duplicated static seed data. F6.4 remains open for a complete seed inventory and cross-page consistency acceptance. No browser, Chrome, Edge, CDP, Python Console, database, Nacos, Consul, or production service was accessed.
