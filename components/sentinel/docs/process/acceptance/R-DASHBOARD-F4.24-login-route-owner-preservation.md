# F4.24 Login Route Owner Preservation (2026-10-08, partial)

## Scope

Fix credential loss when the application replaces the public login route during its own authentication command. This record covers only the React route owner and a local demo IAB smoke test; it does not close the full F4.24 acceptance item.

## Finding and change

- `LoginEntryPage` owns the correctable credentials. The authentication workflow projects `authenticating`, then may briefly project `checking` while a known login rejection is being finalized; uncertain outcomes can project `unavailable` and require explicit session inspection.
- `App` previously replaced the public login page with a route-level feedback page during those transitions. That unmounted `LoginEntryPage` and discarded its local form state before the anonymous snapshot was restored.
- The login route now keeps its existing page owner mounted while a non-idle login command is in `authenticating`, `checking`, or `unavailable`. The page itself remains responsible for disabling inputs, presenting progress/error state, and exposing explicit inspection when the write outcome is unknown. No private route is rendered or authorized by this exception.
- Added an App-level E2E regression case for rejected credentials, username retention, and non-enumerating feedback in `dashboard-prototype/tests/e2e/app-authentication.e2e.test.mjs`. The repository E2E runner is CDP/Chrome-based; it was deliberately not invoked under the user's browser constraint.

## Evidence

- Codex in-app browser only, local Vite demo at `127.0.0.1:4190`: submitted a synthetic invalid login for `viewer`. After the failed attempt, the username remained visible in the field and the password remained masked. The displayed Japanese fallback was generic (“login failed; try again later”) and did not indicate whether an account exists.
- Fresh-tab follow-up in the same explicit local Mock mode: unknown synthetic credentials produced the expected non-enumerating strings in Japanese (`認証情報が正しくないか、このアカウントはログインできません。`), English (`Incorrect credentials, or this account cannot sign in.`), and Simplified Chinese (`账号或密码错误，或当前账号无法登录。`). Username retention and masked password were visible in each run. English Enter submission used the same rejection branch; password visibility toggled and was returned to masked. This manual evidence does not cover every keyboard/accessibility path.
- The earlier generic fallback's cause remains unverified; the fresh-tab result is not used to infer a root cause.
- `npm run typecheck`, `npm run lint`, and the full `npm run check` passed. The first check attempt was blocked by sandbox `EPERM` when `HTTP-LIVE-CONTROLLED` bound its temporary loopback server; the same full check was rerun with local-loopback permission and passed, including typecheck, format, lint, architecture **14/14**, logic **253/253**, HTTP **94/94**, contract, tooling, i18n, production/demo builds, build profiles **2/2**, and Sites **4/4**. `i18n:check` still reports **43** dynamic translation calls requiring mappings/runtime coverage.
- No Chrome, Edge, or CDP browser was launched or controlled. No Python backend, real API, database, or external configuration center was contacted.

## Remaining before F4.24 can be checked

- Verify all three localized required-field/authentication error states and password visibility behavior with repeatable automated evidence.
- Verify keyboard/Enter submission and that mock-mode messaging cannot appear in the live-only build.
- Run the full App-level E2E through an approved IAB-compatible harness; do not substitute the existing Chrome/CDP runner.
- Verify the real Python Console login error contract and behavior when that backend is available.

## 2026-10-09 supplement: formal login form SSR semantics

- The existing `F4.22-LOGIN-PAGE-RENDER` React SSR case now also asserts tri-locale username/password fields after a known rejection, `autocomplete=username`, masked `current-password`, an explicit submit button, and an initially unpressed password-reveal control with its localized show-password label.
- Validation: focused login page SSR **1/1 passed**; complete catalog suite **18/18 passed**; `npm run check:fast`, Prettier check for `tests/i18n/catalog.test.mjs`, and `git diff --check` passed.
- Boundary: server rendering does not execute Enter submission, reveal toggling, typed username retention or mounted failure recovery. No Python Console integration or full E2E was run; F4.24 remains open for final browser acceptance.

## 2026-10-10 supplement: mounted tri-locale authentication rejection case

- Extended `tests/e2e/login-entry.e2e.test.mjs` with a final mounted case that renders the real `LoginEntryPage` under StrictMode, switches the shared i18next instance through Simplified Chinese, English, and Japanese, and submits the same synthetic rejected credentials in each locale.
- Each locale asserts its formal non-enumerating error, retained editable username, masked password, and absence of the username/password/raw transport error from rendered text and browser storage.
- `node --check tests/e2e/login-entry.e2e.test.mjs` and `git diff --check` passed. The CDP-based E2E case was not run; this adds executable acceptance coverage but does not replace an IAB-compatible mounted run or real Python login verification. F4.24 remains open.

## 2026-10-10 supplement: demo-only login notice isolation

- The generic login description no longer contains demo account names. `ConsoleLoginRoute` passes the compile-time build profile to `LoginEntryPage`; only the explicit demo profile renders a localized note identifying the login and console data as simulated and listing the synthetic demo identities. The live-only profile renders the neutral description without demo identities or demo-mode messaging.
- Validation: `node --test tests/i18n/catalog.test.mjs` **18/18 passed**, including actual React SSR of live/demo login states in zh-CN, en-US, and ja-JP. `npm run check:fast` passed typecheck, Prettier, ESLint, and generated Console OpenAPI check (**43 paths / draft-partial**). `npm run build` and `npm run build:demo` both completed; inspection of the emitted route chunks confirmed the live build passes `demoMode: false` and the demo build passes `demoMode: true`. A follow-up focused login SSR assertion passed **1/1**, confirming the password-reveal control is `type="button"` with localized text and `aria-pressed`, so it cannot accidentally submit the form.
- Boundary: this proves the component copy split and app build-profile wiring at source/type level, not a live production browser bundle or mounted login interaction. Keyboard/assistive-technology automation, IAB-mounted verification, real Python Console login behavior, and final E2E remain open; F4.24 stays unchecked.
