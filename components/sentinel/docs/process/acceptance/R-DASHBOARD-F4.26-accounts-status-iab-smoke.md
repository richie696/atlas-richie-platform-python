# F4.26 Account Status — IAB Mock Smoke

Status: partial rendered acceptance; F4.26 remains open.

## Evidence

- Used a fresh local Mock session in the Codex in-app browser only. No Chrome,
  Edge, CDP, Python Console, database, or real service was involved.
- The built-in `admin` row rendered its disable action as disabled.
- For the ordinary `viewer` account, opening the disable action displayed a
  confirmation dialog naming the target and warning that login would be denied
  and existing sessions invalidated. Cancel closed the dialog while the row
  remained enabled. A second attempt followed by explicit confirmation closed
  the dialog and refreshed the row to `已停用`.
- The visible status transition is backed by the account-management Mock HTTP
  handler. It is not evidence of database persistence, concurrent last-admin
  protection, or a production authenticated account service.

## Remaining

- 2026-10-12 real MySQL + SQL-composed ASGI HTTP acceptance now covers the backend
  boundary previously missing here. Two independent administrator cookie/CSRF
  sessions concurrently demote themselves through `POST /api/v1/accounts/commands`;
  exactly one command completes and the other receives a durable `last_admin`
  rejection. The remaining administrator reads its own receipt through
  `GET /api/v1/accounts/operations/{request_key}`. It then submits a status command
  with the stale revision of the changed account and receives a durable `conflict`
  receipt. Persisted assertions verify one active administrator, the final
  admin/view roles, three operation records, and three audit records. The successful
  demotion actor cannot read the admin-only receipt after the command because its
  role has correctly changed to `view`; the test therefore verifies that completed
  result at the database boundary. Focused command passed against disposable MySQL
  8.4.11 + Consul 1.21.1 and the harness confirmed cleanup. This is HTTP/SQL
  integration evidence, not mounted React or final IAB E2E.

- 2026-10-10 account-directory protection explanation: added a presentation projection
  from the existing `accountStatusIssue` policy and rendered its existing localized
  `management.builtIn` / `management.lastAdmin` copy beside the disabled action.
  `npm run test:logic:focused -- ACCOUNT-STATUS` passed **5/5**; the actual
  `AccountDirectory` React component SSR check rendered both reasons in zh-CN, en-US,
  and ja-JP and omitted raw translation keys (**1/1**); `npm run check:fast` passed.
  This proves the localized component output and static checks, not mounted browser
  layout, server-side concurrent last-admin enforcement, or full F4.26 acceptance.

- Focused workflow evidence (2026-10-09): `npm run test:logic:focused -- ACCOUNT-STATUS`
  passed **4/4**. Added cases prove that a confirmed status receipt carries the selected
  account ID/revision, refreshes the active directory only after confirmation, and that a
  concurrent `last_admin` rejection remains a conflict mapped to the safe localized
  `management.lastAdmin` message without changing the prior directory fact. This is a
  controlled Port test, not a shared-service concurrency or rendered-dialog test.
- The related source slice passed `npm run typecheck`, `npm run format:check`, and
  `npm run lint`; no full browser E2E was run, per the final-only E2E cadence.

- IAB did not exercise a persisted last-active-admin conflict or server-side
  revision conflict/failure surface. The demo seed protects its only admin as a
  built-in account, so the UI path does not isolate the separate last-admin
  condition.
- A two-tab IAB probe was attempted against the same Mock origin. Tab 1 disabled
  `viewer`; tab 2 still showed its original enabled row and its subsequent
  disable command also succeeded instead of returning `conflict`. Source review
  confirms `createAccountManagementMockHandlers` owns a fresh in-memory state
  closure per Mock handler factory, while `mockConsoleHandlers` constructs that
  factory inside each page's Mock module. Therefore the two-tab result reflects
  isolated Mock state, not a proven failure of the future shared Python
  Console's revision check. It also means cross-tab concurrency cannot be
  accepted using this Mock arrangement; it must be verified against one shared
  backend or a deliberately shared test authority. No workaround or command
  replay was used.
- Python Console/API authorization, relational transactions, and concurrent
  uniqueness/last-admin invariants remain B0 work. F4.26 is not checked.

### 2026-10-12 current mounted IAB outcome

- On the primary IAB dev port (`127.0.0.1:5173`), the account directory first
  showed a read failure; an explicit retry did not change it. A full page refresh
  under the same admin session then rendered the admin/viewer rows and the
  built-in admin protection explanation.
- A single confirmed `viewer` disable command transitioned the Dialog to
  `result-unknown`. Two read-only “Check operation” attempts did not resolve it;
  confirm/cancel stayed disabled. The original tab was retained for later
  reconciliation. No duplicate command was sent and the tab was not refreshed or
  closed.
- A second tab showed the default viewer-active directory, but its own
  `createAppConsoleMockAssembly()` creates an independent in-memory authority;
  it cannot authoritatively settle the first tab's operation.
- The app-level HTTP comparison now exercises the real app auth owner, account
  adapter, workflow, and complete app Mock handlers. `ACCOUNT-APP-MOCK-STATUS`
  passed **1/1**, including viewer disable→enable, completed receipts and
  directory read-back. This does not override the mounted unknown result.
- F4.26 remains open. The current browser exposes no request/response observer to
  identify the original command/lookup outcome, and Python live/real shared-store
  authorization remains B0 work.
- A later IAB inventory no longer listed the original unknown-operation tab. We
  did not intentionally refresh or close it, but cannot claim the browser owner
  remains available for interactive reconciliation. No duplicate command was
  sent; the outcome is still unresolved.

### 2026-10-12 final mounted re-verification

- In a new Codex IAB tab at `127.0.0.1:5173`, the page explicitly identified
  itself as local Mock/demo. The built-in admin disable control was disabled and
  explained. Viewer status change required a confirmation Dialog; confirming
  disable refreshed the list to `已停用`, and confirming enable refreshed it back
  to `启用`. The Mock account was restored to its original enabled state.
- This mounted result supersedes the earlier statement that no mounted status
  command succeeded in the test tab. It does not erase the separate earlier
  unknown command event in another IAB owner, nor does Mock prove Python page
  integration. F4.26 is now closed for the frontend command/UI scope based on
  this mounted confirmation/read-back plus §15.225, §15.490 and real MySQL/ASGI
  command conflict evidence in §15.879; React→Python browser acceptance remains
  in B0.5.
