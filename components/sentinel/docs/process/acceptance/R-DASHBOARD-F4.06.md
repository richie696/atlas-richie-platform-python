# Dashboard F4.06 — Instance selection lifecycle

Status: **implemented and verified through logic, HTTP/MSW, and Codex in-app browser.**

## Risk-to-test matrix

| Risk | Test | Required assertion |
| --- | --- | --- |
| Filtering/pagination drops an explicit selection or auto-selects another row | Logic + in-app browser | Selection identity/epoch remains stable while rows are filtered or paged; no other row becomes selected |
| App/environment/window change carries an invalid selected instance | Route transition | Target identity is removed when its owning context changes |
| Deep link names a missing or filtered-out instance | In-app browser | No fallback detail appears; explicit missing-target state and a clear-selection action are shown |
| Instance disappears or process incarnation changes | HTTP/resource + rendered state | No stale metrics/receipt survive authoritative 404/410/epoch replacement; the user can return to directory |
| Detail navigation drops target/window | Rendered browser path | Rules, Faults and Realtime destinations preserve selected instance and exact `[from,to)` context where that destination supports it |

## Evidence boundary

MSW exercises frontend error classification only. It cannot establish that the
Python Console returns authoritative not-found/incarnation errors correctly.
All page interaction evidence in this task uses the Codex in-app browser only;
Chrome/Edge must not be launched.

## Current result (2026-10-08)

- Fixed the confirmed route merge defect: navigation merges omitted context fields
  with the prior URL, so clearing a missing instance had left its old `instance`
  and `scope` parameters in place. Explicit clear now writes `undefined` for both
  identities; changing environment, application, or observation window also
  drops the stale selected target. The regression tests merge the new context
  into the prior route and assert neither query field survives.
- Logic/HTTP evidence: filtering to `instance-2` leaves the explicitly selected
  `instance-1` detail and process receipt intact without auto-selecting the
  visible row. The HTTP adapter returns explicit 404 for a missing target and
  maps a retired process epoch (wire 410) to `instance_incarnation_changed` (409).
  `npm run test:logic` **239/239** and `npm run test:http` **81/81** passed.
- Codex in-app browser only (no Chrome/Edge): with `instance-1` selected, the
  directory filter showed only `instance-2` while the detail still identified
  `instance-1` and `incarnation-1`; the Rules and Realtime actions retained
  `env`, `app`, exact `from/to`, `instance`, and `scope`; the Faults navigation
  retained the same instance and exact `[from,to)` window. An invalid
  `instance=not-real` deep link displayed the missing-target message rather than
  another instance's detail. Clicking “清除实例选择” removed `instance` and
  `scope` from the URL and returned to the explicit “请选择一个具体实例” state.
- `npm run typecheck`, `npm run format:check`, `npm run lint`,
  `npm run i18n:check`, `npm run test:architecture` (**13/13**), production and
  demo builds, and `git diff --check` passed. Builds retain the existing Zod
  annotation and >500 KB chunk warnings. Full HTTP suite required permission
  for its isolated temporary loopback listener; after approval it passed 81/81.
- **Boundary:** all rendered evidence is local demo/mock data; the 404/retirement
  contracts are MSW responses, not a live Python Console. This acceptance used
  the Codex in-app browser only. It is a focused F4.06 acceptance, not the full
  browser E2E suite or Python/provider/database end-to-end acceptance.
