# F6.4.20 Centralize instance identity and capability seeds

Date: 2026-10-09

Status: slice complete; F6.4 remains open.

## Requirement

Instance directory responses must project stable demo identity, supported observation scopes, and last-report timing from the app-owned observation scenario. A feature fixture may shape a response, but must not invent reusable seed facts.

## Implementation

- Added `containerId`, `processId`, `supportedScopes`, and `lastReportOffsetMs` to each app-owned instance seed.
- Updated the instance observation projection to consume those facts instead of synthesizing IDs, supported scopes, and a fixed report offset.
- Added a small public `features/applications/model.ts` entry for model vocabulary. The app Mock scenario imports `INSTANCE_LAYER` through that entry, avoiding both a private feature-model import and a feature barrel that would pull UI/SCSS into a Node HTTP test bundle.
- Extended HTTP consistency assertions and the architecture guard for seed ownership and projection behavior.

## Verification

- `npm run test:http:focused -- 'OBSERVATION-SEED-CONSISTENCY|MOCK-CLOCK-HTTP'`: **2/2 passed**.
- `npm run test:architecture`: **16/16 passed**.
- `npm run typecheck`: passed.
- Prettier check on changed MJS tests and `git diff --check`: passed.
- The broader `npm run check:fast` passed earlier in this slice before the final public-model-entry adjustment; it was not repeated after that small import-only change. Full milestone check and E2E were intentionally not run.

## Acceptance boundary

This closes only the instance identity/capability/time seed slice. F6.4 remains open for remaining health, summary, user, rule plan/version, and scenario-difference seeds. No browser, Chrome, Edge, CDP, Python Console, database, Nacos, Consul, or production service was accessed. This is not full page E2E or real backend integration evidence.
