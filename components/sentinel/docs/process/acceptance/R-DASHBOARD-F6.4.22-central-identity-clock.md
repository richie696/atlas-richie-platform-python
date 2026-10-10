# F6.4.22 Use the app Mock clock for account last-login seeds

Date: 2026-10-09

Status: slice complete; F6.4 remains open.

## Requirement

Identity seed timestamps should remain coherent with the one app-level Mock clock. A fixed historical timestamp in an app scenario is misleading when the demo runtime clock is captured at startup.

## Implementation

- Changed the canonical administrator/viewer identity scenario from fixed `lastLoginAt` strings to `lastLoginOffsetMs` values.
- `createAccountManagementMockHandlers` now accepts an injected clock and derives its initial directory timestamps from the scenario offsets.
- App Mock assembly injects the shared `mockClock`, preserving deterministic app-level responses; standalone handler tests retain an explicit default clock.
- Extended the identity HTTP consistency test and architecture ownership guard.

## Verification

- `npm run test:http:focused -- 'IDENTITY-MOCK-SEED'`: **1/1 passed**.
- `npm run test:architecture`: **16/16 passed**.
- `npm run check:fast`: passed (typecheck, source format, lint, OpenAPI consistency).
- Full milestone check and E2E were intentionally not run.

## Acceptance boundary

This verifies only the synthetic identity directory's timestamp projection. It does not establish real account last-login persistence, backend timezone behavior, Python Console integration, or cross-process session semantics. No browser, Chrome, Edge, CDP, database, configuration center, or production service was accessed.
