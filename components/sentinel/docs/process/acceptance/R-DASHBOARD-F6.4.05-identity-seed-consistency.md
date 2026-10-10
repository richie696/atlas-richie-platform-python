# F6.4.05 — Identity mock seed consistency

Status: **slice complete** (2026-10-08). F6.4 remains open.

## Risk-to-test matrix

| ID | Risk | Test boundary | Required assertion |
| --- | --- | --- | --- |
| ID-SEED-01 | Login and `/auth/me` return synthetic identities absent from account directory. | Combined identity/account MSW handlers through HTTP. | Session account ID, username, and role match the seeded account row. |
| ID-SEED-02 | Login and account-directory handlers carry duplicate canonical seed data that drifts. | TypeScript typecheck plus seed-driven mock initialization. | Both handlers derive identity fields from one identity-owned mock seed. |
| ID-SEED-03 | Old fixture summaries remain as a second inactive source and mislead future changes. | Source reference scan and architecture/build checks. | Remove the unreferenced obsolete account fixture and update stale ownership comments. |
| ID-SEED-04 | The change weakens the mock role boundary or exposes credentials. | Existing identity/account authorization tests. | Viewer remains denied from account-directory reads; no password enters session or account rows. |

## Design boundary

The identity feature owns the canonical synthetic account identities used for local Mock login and account-directory initialization. Mock credentials remain write-only inputs to login and are not added to the seed, session, browser storage, or account response. The mock role storage continues to provide only the authorization role; `/auth/me` maps that role back to the matching canonical seeded account.

No new abstraction pattern is needed: this is one immutable seed shared by two existing HTTP mock handlers. No production identity or backend contract changes are in scope.

## Acceptance boundary

This slice establishes local Mock identity/account agreement only. It does not prove real Python Console authentication, account persistence, or cross-process sessions.

## Evidence and result

- `npm run test:http`: **91/91 passed**, including a combined identity/account mock test proving login and `/auth/me` resolve to the canonical directory row; the View role still receives `403` for directory reads and the account response contains no mock password.
- `npm run test:logic`: **247/247 passed**; `npm run typecheck`, `npm run lint`, and `npm run test:architecture` passed (**13/13**).
- `npm run test:build-profiles`: **2/2 passed**; the live artifact still excludes mock handlers and demo identity. `git diff --check` passed. A repository source scan finds no remaining imports or references to the deleted unused `identityFixtures.ts`.
- Codex in-app browser (IAB), local Mock profile: after logging in as the synthetic administrator, the session menu was labelled `admin` rather than the former non-directory `mock-admin`. No Chrome, Edge, or CDP was launched or connected.

The change only repairs local demonstration identity facts. It does not claim Python Console or persistent-account behavior.
