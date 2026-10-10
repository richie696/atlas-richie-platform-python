# F6.7 Runtime mode and bootstrap acceptance

Date: 2026-10-09

## Delivered

- Runtime configuration explicitly resolves `mock | live` and validates the API URL as a safe absolute HTTP(S) origin.
- `.env.example` documents local mock mode, optional first-run demo profile, controlled live mode, and the live-only production default.
- Console bootstrap now awaits the request interception boundary before creating request services or mounting React pages.
- Interception failure propagates to the existing fail-closed startup message; request-capable services and pages are not created or rendered.
- Feature code remains unaware of mock/live selection.

## Evidence

- `npm run test:logic:focused -- 'RUNTIME-(MOCK|LIVE|MODE|BOOTSTRAP)'`: **5/5 passed**.
- `npm run check:fast`: **passed** (TypeScript, Prettier, ESLint, OpenAPI consistency).
- Codex in-app browser mock-start smoke: `http://127.0.0.1:5175/#/overview?app=all&range=1h` resolved to the login route and rendered the login form. The smoke did not submit credentials or exercise a complete page journey.
- `npx prettier --check` on the acceptance/progress documents and `git diff --check`: **passed**.

## Not covered

- No full page E2E or `check:milestone` run; those remain reserved for milestone closure.
- No Python Console or live backend was running, so no claim is made about real live-mode connectivity.
- The browser smoke used the demo profile only; production artifact isolation is tracked separately in F6.8.
