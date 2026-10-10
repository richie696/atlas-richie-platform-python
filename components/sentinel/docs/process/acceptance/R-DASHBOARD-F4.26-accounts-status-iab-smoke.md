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
