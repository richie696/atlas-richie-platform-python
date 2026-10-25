# F4.22 — mounted login cooldown verification

Date: 2026-10-12  
Scope: React `LoginEntryPage`, `useLoginCooldown`, and the production `AuthenticationWorkflow` mounted in Happy DOM. The workflow Port is synthetic and deterministic; this is not browser E2E or Python Console integration.

## Covered behavior

- [x] A canonical synthetic `429 rate_limited` with a bounded `retryAfterMs` reaches the actual login page through the production workflow and disables its submit button.
- [x] Editing both username and password during the active cooldown leaves submit disabled; dispatching the form event during the cooldown does not issue another login command.
- [x] Unmounting during cooldown clears the interval. Remounting the same workflow under React `StrictMode` performs setup/cleanup/setup and retains exactly one live countdown interval.
- [x] Advancing the injected monotonic clock to the deadline restores explicit submission without automatically retrying. A subsequent explicit submission, after entering credentials again, is the only action that dispatches another command.
- [x] A timeout/unknown login result disables the form, rejects a repeated form event without another command, exposes the explicit “Check current session” action, and does not create a retry timer.

## Verification

- `node --test tests/verification/login-cooldown-mounted.test.mjs`: **1 passed**.
- `npm run test:logic:focused -- 'F4[.]22'`: **8 passed**.
- `npm run typecheck`, `npm run lint`, `npm run format:check`, targeted Prettier check for this test/note, and `git diff --check`: **passed**.

## Evidence boundary

This verifies the real React page and hook lifecycle in Happy DOM with a synthetic Port and deterministic clock. It does not prove real browser timing/rendering, live transport decoding, Python API rate limiting, cookie/CSRF behavior, disabled-account behavior, or end-to-end service integration. F4.22 remains open pending its broader acceptance gates. No production behavior was changed.
