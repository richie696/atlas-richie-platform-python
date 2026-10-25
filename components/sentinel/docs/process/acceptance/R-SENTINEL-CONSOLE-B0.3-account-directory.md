# B0.3 Account Directory Read — Acceptance Matrix

Status: implementation slice / local evidence only. This document does not claim production database or browser acceptance.

## Scope

Implement the read-only account directory consumed by the dashboard:

- `GET /api/v1/accounts?page={page}&pageSize={pageSize}&search={search}&status={status?}`
- `GET /api/v1/accounts/{accountId}`

The server resolves the session on every request and permits only `admin`. Responses expose only `id`, `username`, `roleId`, `status`, `builtIn`, `lastLoginAt`, `revision`, and `lastActiveAdmin`. Passwords, hashes, session data, display names, and raw exceptions are forbidden. This slice does not implement account mutations, login/session creation, audit writes, or production startup wiring.

## Acceptance matrix

| Case | Setup / input | Expected evidence |
|---|---|---|
| Admin list | active admin session; page 1 | 200, safe `items/page/pageSize/total`, stable ordering |
| Pagination | more than one page; boundary and out-of-range page | exact page count invariant, empty out-of-range page |
| Search | username substring | matching rows only; `%` and `_` are treated literally rather than as SQL wildcards |
| Status filter | `active` and `disabled` | every returned row matches filter |
| Admin detail | existing opaque account id | 200 safe record |
| Missing detail | unknown valid id | 200 JSON `null`, per current frontend port |
| Anonymous | absent, malformed, expired or revoked cookie | 401 safe error |
| Viewer | active `view` session | 403 safe error for list and detail |
| Invalid query | repeated/unknown query key, non-integer/out-of-range pagination, unsupported status, oversized search | 400 safe error |
| DTO secrecy | persisted hash and session facts present | neither hash nor credential/session field appears in serialized response |
| Derived admin fact | zero/one/multiple active admins | only the sole active admin record has `lastActiveAdmin=true` |
| Persistence failure | reader raises safe authority error | 503 safe error, no exception details |
| Migration | fresh SQLite and upgrade from v0001 | `built_in` defaults false, `last_login_at` nullable; migration repeat is idempotent |

## Verification boundary

Python 3.12.14 full Console suite: **46 passed**. `git diff --check`, `compileall`, and the changed production-source 88-column check passed. The run used the existing local dependency directories without downloading packages or writing into a project virtualenv. SQLite is an isolated adapter test only. PostgreSQL/MySQL migrations, provider-specific Unicode search/collation behavior, transaction isolation, production wiring, browser-to-Python integration, and live user data remain unverified. No browser was needed for this backend-only slice. Use only the Codex in-app browser for any later UI inspection; do not launch Chrome, Edge, or CDP.

## Design boundary

Reuse the existing consumer-owned read-port / SQLAlchemy adapter structure. No new GoF pattern is introduced. Account mutation `Command` handling is intentionally deferred to its own design and transaction tests.
