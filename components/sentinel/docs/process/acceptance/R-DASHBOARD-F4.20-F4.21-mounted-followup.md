# F4.20 / F4.21 setup-secret mounted follow-up

Status: **focused mounted verification passed**. This supplements, but does not replace or close, the shared F4.20/F4.21 acceptance record.

## Scope and evidence

`dashboard-prototype/tests/verification/setup-sensitive-fields-mounted.test.mjs` mounts the production `InitializationPage`, `SetupWizard`, form controls, `InitializationWorkflow`, and `NavigationProtectionProvider` under React with Happy DOM. A controlled in-memory port supplies only synthetic bootstrap/receipt facts; no Python service, database, configuration center, or browser E2E is involved.

The mounted test covers two lifecycle paths:

1. After the app-level navigation discard is confirmed, the registered setup cleanup clears database credentials, administrator password/confirmation, and direct Nacos credentials. It preserves non-sensitive database/source selections and locations, performs no initialization write, and leaves workflow snapshots free of form secrets.
2. A simulated lost initialization response remains `result-unknown`; neither completion nor secret cleanup runs, and a second submit does not replay the write. Inspecting the original request and receiving its completed receipt transitions to `ready`, invokes cleanup once, removes the setup form from the DOM, and calls completion once.

The test uses synthetic strings at runtime only. No credential values are written to this record, a fixture file, browser storage, or workflow snapshots.

## Verification

- `node --test tests/verification/setup-sensitive-fields-mounted.test.mjs` — **1 passed**.
- `npm run test:logic:focused -- 'SETUP|F4\\.20'` — **32 passed**.
- `npx eslint tests/verification/setup-sensitive-fields-mounted.test.mjs --max-warnings=0` — **passed**.
- `npm run typecheck` — **passed**.
- `npx prettier --check tests/verification/setup-sensitive-fields-mounted.test.mjs ../docs/process/acceptance/R-DASHBOARD-F4.20-F4.21-mounted-followup.md` — **passed**.

## Boundary

This is mounted React evidence against a controlled port, not service/database acceptance. The ambiguous-outcome assertion checks that the real mounted page does not invoke its registered cleanup before receipt confirmation; direct values are subsequently checked as blank on the discard path. Full browser E2E remains deferred to the project’s final E2E gate.
