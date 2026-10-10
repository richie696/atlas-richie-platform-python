# Dashboard F4.03 — Overview drill-down test design

Status: **implemented; route context and required read-state matrix verified with logic, HTTP/MSW, and Codex in-app browser**.

## Scope and ownership

The Overview feature is responsible for translating an already validated fleet
query context into read-only navigation. It does not own the destination
application, incident or rule facts. The application URL remains the shareable
context contract; destination features and the Python Console remain the
authorities for target existence and authorization.

This slice adds explicit paths from the fleet overview to:

- the selected/attention application in Applications;
- the incident timeline for the current application or fleet scope;
- the rule-binding directory for the selected application, especially from its
  rule-coverage cell.

Every path must retain the environment and exact `[from,to)` UTC window. An
application-specific rule-coverage path must use that row's `appId`, not the
currently selected app or a guessed binding. No navigation action writes data.

## Risk-to-test matrix

| Risk                                                    | Test                                              | Required assertion                                                                                                                                                |
| ------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Relative range is recomputed during navigation          | Pure navigation/route round trip                  | `env`, exact RFC3339 `from`/`to`, and explicit target `appId` survive; no credentials or inferred IDs                                                             |
| Fleet-wide incident action loses scope                  | Overview UI navigation contract                   | Faults destination receives fleet sentinel, environment and exact window                                                                                          |
| Application rule coverage opens an unrelated rules list | Row action contract                               | Rules destination receives that row's app ID, environment and exact window                                                                                        |
| No attention target creates an invalid app link         | Zero-target UI/model case                         | Attention action is absent; no route contains `undefined` or an invented ID                                                                                       |
| Destination route rewrites away the carried window      | Rules/faults destination filter transition        | Changing page-local filter or selecting a target preserves the incoming exact window                                                                              |
| Read states are conflated or leak old data              | Existing QueryResource/ObservationQueryView tests | Loading, empty, partial, denied, stale/error and retry remain distinct; denied/changed owner clears protected values; retry re-reads and does not echo raw errors |
| Mock/demo cannot reproduce denied or recovery UI        | HTTP fixture + in-app browser                     | Reserved mock-only targets deterministically yield 403 denied, and 503 then success on explicit read retry; no behavior enters the live adapter                   |
| User cannot follow destination or refresh state         | Codex in-app browser                              | Actual overview links reach expected routes and rendered query context preserves env/app/window; no Chrome/Edge process is started                                |

## Evidence boundary

Logic tests prove route-context projection only. HTTP/MSW tests prove the
frontend adapter and mock contract only. In-app browser evidence proves the
rendered frontend path against the configured local demo/mock service. None of
these prove Python authorization, production incident aggregation, rule
coverage persistence, or real provider/collector data; those remain backend
and live-integration acceptance items.

## Current result (2026-10-08)

- Implemented exact-window route resolution for Overview and the observation
  pages. Overview summary, application rows, and rule-coverage drill-downs
  carry the canonical UTC `from`/`to`; rules page filter/binding navigation
  carries the same bounds instead of recomputing the relative range.
- Added translated “查看故障分析” and “查看规则覆盖” actions. The latter uses
  the current application row's identity and explicitly sets application scope.
- Logic tests cover exact-window precedence, invalid-window fallback using one
  stable anchor, and fault/rule route round trips. Shared QueryResource tests
  cover loading/empty/filtered-empty/partial, denied, stale/error and retry
  transitions; the shared QueryView has explicit presentation for each state.
- Codex in-app browser only (no Chrome/Edge): Overview rendered `app-two`,
  `test-env`, exact `15:59:10.220Z–16:59:10.220Z`; “查看故障分析” reached the
  matching incident list; “查看规则覆盖” reached the matching rule directory
  and rendered a legitimate empty state (0 bindings) rather than an error; the
  app-row “查看实例” action opened the matching application/instance page with
  the same window. Partial telemetry was visibly labeled on Overview.
- The earlier browser tab showed a stale read-error snapshot. A fresh in-app
  browser session issued successful catalog/rule requests and rendered the
  expected empty result. This was not reproduced in the fresh session and did
  not justify a source change.
- Latest successful checks: typecheck, format check, lint, architecture tests
  (13/13), logic tests (235/235), HTTP tests (80/80), contract check,
  production build, demo build, and `git diff --check`. The HTTP suite's
  controlled loopback test required permission to bind a temporary `127.0.0.1`
  port. Vite still reports a >500 KB initial-chunk warning.
- **Full browser-suite E2E remains separate:** no Chrome/Edge-backed `test:e2e`
  was run. Python Console and real production data remain outside this frontend
  slice.

## Current read-state completion (2026-10-08)

- The opt-in demo HTTP handler now has two explicitly reserved synthetic targets:
  `mock-forbidden-application` returns a safe 403/`forbidden`;
  `mock-recovering-application` returns one 503/`service_unavailable`, then a
  successful empty snapshot after the user explicitly retries. These IDs are
  not added to the catalog and no live adapter or production build imports the
  mock handler. Scenario counters are isolated to the mock handler and reset in
  HTTP tests.
- Codex in-app browser only (no Chrome/Edge): the forbidden target rendered
  “当前会话没有查看该数据的权限。” with no retry action. The transient target
  rendered the safe read-failure message and “重试读取”; clicking it issued the
  next read and rendered the explicit empty-state message, not invented rows or
  stale error text. Earlier paths in this record verify app/fault/rule
  drill-downs and exact window preservation; F4.06 additionally verifies
  instance identity preservation on these destinations.
- `npm run test:logic` **239/239**, `npm run test:http` **82/82**,
  `npm run test:architecture` **13/13**, typecheck, format, lint, i18n,
  production/demo builds, build-profile tests (**2/2**) and `git diff --check`
  passed. HTTP suite's controlled loopback test required an approved local
  listener. Builds retain the existing Zod annotation and >500 KB chunk
  warnings.
- **Evidence boundary:** failure/recovery outcomes are synthetic HTTP mock
  responses and prove rendered frontend state transitions only. They do not
  prove Python Console authorization or its retry/recovery behavior. Full E2E
  acceptance and real backend/provider/database integration remain open.
