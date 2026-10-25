# Dashboard F4.09 — Immutable versions, publication and activation plans

Status: **frontend mock slice verified with focused tests and Codex in-app browser**.

## Ownership and boundary

The rules feature owns immutable version selection, publication intent, instance
receipt presentation, and explicit plan commands. Plans are persisted/executed by
the backend contract; the browser does not schedule activation or restoration.
Publishing historical content is a new publication against an observed source
baseline, not a rewind of a runtime epoch.

## Risk-to-evidence matrix

| Risk | Evidence | Result |
| --- | --- | --- |
| Partial instance convergence is confused with invalid rule configuration | IAB rendered state + three-locale copy checks | Dedicated receipt wording; applied/pending/restart-required counts stay distinct |
| A historical rollback is presented as reversing runtime history | IAB + logic tests | It is a new publication; the UI does not claim all instances applied |
| Plan omits restore target, zone, or exact UTC interval | IAB + schedule logic | Explicit target/restore, IANA zone, and UTC preview are visible |
| Overlapping plans silently overwrite a schedule | IAB + HTTP | UI preflight blocks; mock HTTP independently returns 409 |
| Cancelled plan still appears pending or creates a browser timer | IAB + HTTP | Cancellation is read back as cancelled; another plan is command-persisted; no frontend timer |
| Restart-required counts as applied | IAB + logic | Receipt coverage reports 1/3 applied, with pending and restart-required separate |
| Unknown command result is replayed or treated as rollback | Logic + HTTP contract | Focused workflow tests preserve original operation lookup/no-replay contract; not manually injected in IAB |

## Verification performed (2026-10-08)

- Logic: `node --test --test-name-pattern='DEPLOY-|PUBLICATION-|ACTIVATION-|SCHEDULE-' tests/logic/run.mjs` — **19/19 passed**.
- HTTP: `node --test --test-name-pattern='RULE-MOCK-DEPLOYMENT|RULE-MOCK:' tests/http/run.mjs` — **2/2 passed**. Covers independent per-binding baseline versions, partial receipt counts, server-side overlap conflict, cancellation, creation after cancellation, and fixture reset.
- Architecture: `npm run test:architecture` — **13/13 passed**.
- `npm run typecheck`, `npm run format:check`, `npm run lint`, `npm run contract:check`, `npm run i18n:check`, and `git diff --check` — passed.
- Codex in-app browser only (no Chrome or Edge): opened the event-version detail; published the event version and refreshed the publication list; published the historical baseline as a separate new publication; read per-process partial receipts and verified the 1/3 coverage plus the restart-required warning; confirmed overlap is blocked; cancelled the seeded pending plan with a reason and refreshed its cancelled state; created a non-overlapping plan and read it back from the plans list. Reload restored the mock seed state.
- During one longer sequence containing plan cancellation/creation followed by repeated publications, a later refresh briefly rendered stale/error states. A clean mock reload and independent repeated event/baseline publication sequence both read back successfully; the transient was not reproduced in the focused contracts. This remains a recorded demo-path stability observation, not evidence about a live backend.

## Evidence boundary

All browser writes and reads were served by the local demo MSW handlers. The
historical baseline remains the current source snapshot in this fixture, so this
proves the UI's “historical version as a new publication” path, not a live
configuration-center rollback or runtime change. The full CDP `test:e2e` suite
was intentionally not run because it starts Chrome; unknown-outcome behavior is
covered by focused logic/HTTP contracts, not claimed as manually tested in IAB.
Python persistence, Nacos/Consul conditional writes, backend scheduling,
cross-language behavior, Agent loading, and restart-required runtime behavior
remain unverified.
