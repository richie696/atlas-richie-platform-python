# Python Console B0.2 — Persistence Foundation Test Design

Status: **partial implementation and isolated real-database acceptance; B0.2 remains open**.

## Local implementation evidence (2026-10-07)

- SQLAlchemy mappings and Alembic revision `0001_identity_control` are present
  in the package source. The migration creates the singleton setup guard,
  account/session/initialization-operation/audit tables, database constraints,
  and exactly one uninitialized guard row.
- `PasswordHashService` uses Argon2id and verifies both valid and invalid
  candidates. `AesGcmSecretCipher` uses a versioned AES-256-GCM envelope with
  key-id rotation and owner/field associated data; modified ciphertext and a
  mismatched owner context are rejected.
- Source-tree test run: **22 passed**. The built wheel was installed into a
  separate temporary target and the same suite imported the installed package:
  **22 passed**. `compileall` and `git diff --check` passed.
- `uv build components/sentinel/sentinel-console` produced an sdist and wheel;
  wheel inspection confirmed that `migration_runner.py`, Alembic `env.py`,
  revision `v0001_identity_control.py`, and the bootstrap SQLAlchemy adapter
  are packaged.
- The test runtime dependencies were isolated under `/private/tmp`; the project's
  managed virtual environment was not modified. Docker is installed but its
  daemon socket returned permission denied, so no PostgreSQL/MySQL containers
  were started and no real database was contacted.

These checks establish a local package/migration/security foundation and one
bootstrap-read API vertical slice. They do **not** establish PostgreSQL/MySQL
migration or locking behavior, setup command flows, database credential
protection at rest, multi-worker bootstrap recovery, account/role/password-
change/audit use cases, or live browser-to-Python persistence. B0.2 remains
open.

## Account username identity slice (2026-10-07)

- `AccountUsername` owns bounded input validation, ECMAScript-compatible edge
  trimming, NFKC/lowercase identity, preserved display spelling and the fixed
  SHA-256 lookup digest. The persistence mapping and initial migration use a
  64-character unique `username_key`; canonical clear text is not stored.
- React mock search/create use one feature-owned canonicalization function.
  The account, login and bootstrap administrator contracts now point to the
  same semantics; Python remains the live-mode authority.
- Python `unittest` evidence: username vectors **4/4** and SQLite persistence
  tests **5/5**, including `Admin`/full-width `Ａdmin` unique collision.
  Frontend logic **225/225**, focused MSW account duplicate test **1/1**,
  typecheck, lint, format, OpenAPI `contract:check`, compileall and
  `git diff --check` passed.
- The first full frontend HTTP attempt was **77/78** because the sandbox rejected
  the controlled loopback listener (`listen EPERM`). After allowing this test's
  isolated `127.0.0.1` listener, the full suite reran **79/79 passed**; the new
  mock duplicate test is included. Full pytest invocation could not start
  because the offline environment lacks pytest and Starlette distributions;
  selected unittest modules ran directly on Python 3.12.14 with isolated
  dependencies. This does not replace the full Console suite or browser/Python
  E2E.
- PostgreSQL/MySQL normalization and uniqueness, runtime Unicode-table-version
  parity, and actual create/login/bootstrap persistence remain unverified.

## Bootstrap initialization read adapter (2026-10-07)

The application reads the initialization fact from the relational guard row;
the deployment-owned setup-window marker remains a separate authority. The
application use case composes those facts and only checks the request's
operator session while both facts permit setup. ORM rows and SQLAlchemy errors
must not cross the application Port.

| Risk | Test | Result |
| --- | --- | --- |
| Wrong authority ownership | Adapter test against migrated SQLite | **Pass** — SQLAlchemy adapter reads only `console_guard.initialized`; setup-window remains a separate application Port |
| Missing/corrupt guard | Adapter + ASGI integration test | **Pass** — stable 503; never reports uninitialized |
| Database connection failure | ASGI integration test using a synthetic nonexistent SQLite parent directory | **Pass** — stable 503; driver path/message is not reflected and setup/operator authorities are not queried |
| Initialized setup can be reopened | ASGI integration test | **Pass** — returns only `{"initialized": true}` and skips the setup-window/operator authorities |
| Setup authority sequencing | Application/API tests | **Pass** — reads setup-window only when uninitialized; verifies operator only when the window is open |
| Persistence leak | Port/API assertions | **Pass** — ORM record and SQLAlchemy details do not appear in application/API output |

SQLite is accepted only for this local adapter/API integration test. The same
adapter contract still requires PostgreSQL and MySQL runs against disposable,
isolated databases before B0.2 can close. Deployment-backed setup-window reader,
operator-code exchange, CSRF/Origin, and production startup composition are not
yet implemented.

## Current-session read slice — test design (2026-10-07)

This slice implements only `GET /api/v1/auth/me`; login/session creation,
logout, CSRF rotation and production startup wiring remain separate work.
The browser session is an opaque cookie. The API adapter must not echo it, the
application hashes it before crossing the persistence Port, and the database
reader returns only an active account/session projection. Role capability
mapping is a domain rule, not a SQL column or an API-layer guess.

| Risk | Test | Required assertion |
| --- | --- | --- |
| Anonymous session is mistaken for admin | ASGI API test, no cookie | 200 + JSON `null`; persistence reader is not called |
| Raw cookie leaks or is persisted | SQLite migration/API integration | Reader receives only SHA-256 digest; response has no cookie/hash/password fields |
| Revoked/expired session retains authority | SQLite integration | 200 + JSON `null` for each state |
| Disabled account retains authority | SQLite integration | 200 + JSON `null`; account is checked on every read |
| Role capabilities drift | Domain unit tests | admin gets the two contract capabilities; view gets metrics only |
| Persistence is unavailable but appears anonymous | SQLite connection-failure API test | stable 503 `service_unavailable`, no driver detail |
| Bad request-id reaches persistence | ASGI API test | 400 and no reader call |

All database runs in this slice use isolated in-memory SQLite. This does not
prove PostgreSQL/MySQL behavior or a live login/browser flow.

## Current-session read slice — implementation evidence (2026-10-07)

- Implemented `GET /api/v1/auth/me`, `ReadSession`, the consumer-owned
  `CurrentSessionReader` Port, and `SqlAlchemyCurrentSessionReader`. The app
  composition now requires this authority explicitly; it does not select an
  anonymous/demo session provider by default.
- The use case accepts only bounded URL-safe opaque session values, hashes the
  cookie before calling the Port, and maps persisted roles to the contract's
  finite capabilities. The SQL adapter checks expiry, revocation and current
  account status on each read, and maps SQLAlchemy failures to a safe authority
  error. The HTTP route emits only the safe identity projection or JSON `null`
  with `Cache-Control: no-store` and `Vary: Cookie`.
- Local command: `PYTHONPATH=src:/private/tmp/sentinel-console-deps.viomBu:/Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel/.venv/lib/python3.12/site-packages /private/tmp/sentinel-console-account-identity-env-20261007/bin/python -m unittest discover -s tests -v` — **37/37 passed**. The 11 session tests cover use-case/domain mapping, safe ASGI response, and SQLite persistence/expiry/revocation/status behavior. `compileall`, `git diff --check`, and the touched-source 88-column check also pass.
- Starlette/HTTPX were reused from the existing isolated Sentinel venv and SQLAlchemy/Alembic/SQLite dependencies from the temporary Console dependency path; no package installation or network access was needed. This runtime-verifies the ASGI route against test doubles and SQLite, not production database dialects.
- No login/logout/session-creation or CSRF rotation is implemented by this
  slice. No PostgreSQL/MySQL database was contacted; SQLite is local evidence
  only. B0.2 and live browser-to-Python authentication remain open.

## Full current Console regression recheck (2026-10-08)

- Re-ran the current Console source-tree suite with Python **3.12.14** and the
  existing isolated dependency directories:
  `PYTHONPATH=src:/private/tmp/sentinel-console-deps.viomBu:/Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel/.venv/lib/python3.12/site-packages /private/tmp/sentinel-console-account-identity-env-20261007/bin/python -m unittest discover -s tests -v` — **46/46 passed**.
- This is a current regression signal for the implemented bootstrap/session-read/account-directory slices and local SQLite persistence tests. It does not add login, logout, session creation, CSRF/Origin enforcement, account mutations, or browser-to-Python wiring; the suite uses test authorities and isolated SQLite, not PostgreSQL/MySQL.
- **B0.2 remains open.** Do not treat this rerun as production-dialect, service-startup, or live E2E acceptance.

## Current-session logout slice (2026-10-08)

- Implemented `POST /api/v1/auth/logout`, `RevokeCurrentSession`, the
  consumer-owned `CurrentSessionRevoker` Port, and
  `SqlAlchemyCurrentSessionRevoker`. `build_app` now requires the revocation
  authority and a non-empty explicit browser-origin allowlist; it does not
  invent a permissive origin policy.
- The HTTP adapter rejects missing, duplicate, malformed, or unconfigured
  Origin/CSRF proof before persistence. The use case hashes the opaque session
  cookie and CSRF token before crossing the Port. The SQL adapter checks the
  stored CSRF digest in constant time and conditionally updates only an active,
  unexpired, unrevoked matching session. Confirmed revocation returns a bodyless
  204, `Cache-Control: no-store`, and clears the HttpOnly/Secure/SameSite=Lax
  session cookie. Database failures and invalid Port results fail closed.
- `GET /system/bootstrap` supplies the anonymous preflight nonce: it creates a
  random value if the CSRF cookie is missing/invalid, returns that value in
  `x-sentinel-csrf`, and sets a matching Secure/HttpOnly/SameSite=Strict
  `__Host-` cookie with `Path=/` and no Domain. Valid values are reused to avoid
  cross-tab nonce races. Logout requires the
  header and cookie pair to match before it checks the session's stored digest.
- Isolated SQLite persistence tests verify successful revocation and `/auth/me`
  readback becoming anonymous through the composed ASGI app and adapter, wrong
  CSRF, expired/unknown sessions, and a
  bounded database failure. ASGI tests cover exact-origin rejection, duplicate
  Origin/CSRF/Cookie headers, malformed/missing proof, bodyless 204/cookie
  deletion, and safe errors. Python 3.12.14 full source suite:
  **59/59 passed**; `compileall`, `git diff --check`, and the 88-column check for
  new Python sources passed. Frontend OpenAPI generation and `contract:check`
  passed after recording the logout proof/cookie semantics.
- This is ASGI + isolated SQLite evidence only. Login, session creation/rotation,
  production app startup wiring, PostgreSQL/MySQL,
  and browser-to-Python E2E remain unimplemented/unverified; no real database or
  external configuration center was used. **B0.2 remains open.**

## Login and session-creation slice — local implementation evidence (2026-10-08)

The frozen frontend contract is `POST /api/v1/auth/login`: login is a
CSRF-protected command, and a malformed/lost success response is an unknown
outcome. The browser must inspect `GET /api/v1/auth/me`; it must not replay the
password-bearing command. The HTTP boundary owns strict body/header/cookie
parsing and response cookies; the application owns username normalization,
authentication outcome and session issuance; SQLAlchemy owns the atomic
credential/session/last-login persistence. Raw passwords, opaque cookies and
CSRF tokens must not cross persistence Ports.

| Risk | Required proof | Required assertion |
| --- | --- | --- |
| CSRF/origin bypass | ASGI route with isolated authorities | Missing, duplicate or disallowed Origin; missing/duplicate CSRF header or cookie; and header-cookie mismatch reject before credential lookup or rate-limit mutation |
| Credential enumeration | application + SQLite integration | Unknown username, wrong password, disabled account and malformed stored hash have one public rejection shape; never reveal which account fact failed |
| Username identity drift | domain + SQLite integration | Login uses `AccountUsername.lookup_key`; trim/case/NFKC variants resolve the same account as setup/account creation |
| Password disclosure | adapter/use-case/API tests | Clear password is used only for verification; no Port DTO, exception, response, captured log or SQL row contains it; stored password remains Argon2id hash |
| Session fixation/replay | composed ASGI + SQLite | Successful login mints a fresh high-entropy opaque session, persists only its digest, binds a new CSRF digest, rotates both browser cookies and emits only the safe `SessionIdentity` |
| Stale identity retention | composed ASGI + SQLite | Follow-up `/auth/me` returns the exact role/capabilities and session epoch; disabled account/session revocation is still authoritative on every read |
| Abuse/rate limit | rate-limit boundary + ASGI | Contract `429 rate_limited` is exercised without account enumeration; no credential verification occurs after a limit decision; retry delay is bounded by the OpenAPI maximum |
| Storage outage | SQLite integration with unavailable authority | Stable 503 with no SQL/driver detail; no success cookies are set and no fallback identity is granted |
| Malformed request | ASGI boundary | Unknown fields, duplicate proof headers/cookies, oversized/malformed JSON and invalid request ID reject before expensive password verification |
| Unknown command result | frontend HTTP + real backend flow | A lost/malformed login ACK remains unknown; the workflow performs only `/auth/me` inspection and never automatically replays the password |

Before production acceptance, rate-limit identity and deployment behavior must
be explicit for trusted reverse proxies and multiple workers; an in-process
counter is not sufficient evidence. The test suite will separate ASGI/test
authority, SQLite composition, disposable PostgreSQL/MySQL behavior, and
React-to-Python browser E2E. Until these layers pass, the login slice and B0.2
remain open.

### Local verification result

- Implemented the `/api/v1/auth/login` application/API slice and SQLAlchemy
  credential/session adapters. The route rejects duplicate JSON keys and
  malformed Unicode, applies bounded request parsing, and returns one generic
  401 for unknown, wrong, disabled, or corrupt credentials. CSRF/Origin checks
  happen before rate-limit or credential authorities. Session and CSRF tokens
  are returned only through Secure cookies/header; persistence receives only
  SHA-256 digests. Login revokes a previous session only when it belongs to the
  same account. A valid login rotates the current session and `/auth/me` reads
  the new identity back.
- Login and malformed-input regressions: **9/9**; complete Console unittest
  suite: **68/68 passed**. `compileall`, `git diff --check`, and the 88-column
  check for new production Python sources also pass.
- Verification used Python 3.12.14, the existing isolated dependency paths, and
  in-memory SQLite. The test limiter is an injected test double; no production
  limiter or startup composition exists. The app requires a deployment HMAC
  key, while actual trusted-proxy client identity policy remains open; no PostgreSQL/MySQL
  dialect, multi-worker behavior, or React-to-Python browser E2E was verified.
  Therefore this local slice does not close B0.2 or F7.1.

### Explicit trusted-proxy client address policy (2026-10-09)

`ClientAddressResolver` now gives the login HTTP boundary a deployment-owned
policy seam. Its default trusts only the ASGI connection peer. A forwarding
chain is considered only when that immediate peer is inside an explicitly
configured strict, non-global CIDR; the resolver walks `X-Forwarded-For` from
right to left and uses the nearest address not covered by a trusted-proxy
network. Empty or malformed chains fall back to the peer. CIDRs that include
globally routable addresses are rejected, including IPv4 `/1` networks. The
resolver does not parse `Forwarded` or `X-Real-IP`. Deployments must ensure the
trusted proxy appends observed peers and sanitizes caller-supplied forwarding
headers.

Python 3.12 `test_login_api`: **13/13 passed**. The ASGI/SQLite route tests
prove that an untrusted caller cannot choose its HMAC rate-limit identity, a
trusted multi-hop chain selects the nearest untrusted address, malformed input
falls back to the proxy peer, and globally routable/noncanonical CIDRs are
rejected.
This is local test evidence only: there is no production launcher/environment
parser or real ingress test, and the multi-worker limiter remains a required
deployment-owned dependency. B0.2 and F7.1 remain open.

### SQL-backed login-attempt limiter — local implementation evidence (2026-10-09)

`SqlAlchemyLoginAttemptLimiter` now implements the existing application Port.
It stores only the keyed client-identity digest, failure-window start/count,
block expiry, and row expiry. The failure threshold, window, and block duration
are required constructor policy; this change does not silently choose an
operator-facing security threshold. PostgreSQL and SQLite use native
`ON CONFLICT DO NOTHING`; MySQL uses a no-op duplicate-key update. The adapter
then locks the digest row with `SELECT FOR UPDATE`, updates the state in one
transaction, and retries no application-side command. Expired rows are pruned
in bounded batches during limiter mutations. Database errors fail closed as a
sanitized `LoginAuthorityUnavailable`.

Python 3.12 focused tests: **25/25 passed** across the new limiter, login API,
and persistence foundation modules. They include a composed ASGI wrong-password
→ database-backed 429 path, retry timing/reset, independent engine instances on
one isolated SQLite file, eight concurrent first failures in SQLite, success
clearing only that digest, invalid digest/clock and unavailable database
fail-closed behavior, schema migration, and SQL compilation for PostgreSQL,
MySQL, and SQLite dialects. `compileall` and the touched new-source 88-column
check passed.

These results do **not** prove actual PostgreSQL/MySQL behavior or multiple
processes: SQL compilation and multiple engine objects are not live dialect or
worker acceptance. Production `build_app`/launcher composition still does not
construct the limiter, and no deployment policy values or environment parser
are wired. Disposable PostgreSQL/MySQL multi-connection contention, process
restart persistence, configured ingress, and real browser-to-Python E2E remain
open. This local slice does not close B0.2 or F7.1.

## Scope

Establish the Python Console's relational persistence foundation for PostgreSQL
and MySQL: SQLAlchemy async engine/session ownership, Alembic schema migration,
identity/session/audit tables, password hashing, and server-side encryption for
write-only configuration secrets. SQLite is allowed only as a fast local
migration/unit-test dialect; it cannot satisfy PostgreSQL/MySQL acceptance.

The Console service owns persistence and authorization decisions. The React
application remains an HTTP client and cannot connect to a database. The
per-process `sentinel-dashboard` package remains independent and unchanged.

## Design constraints

- Use SQLAlchemy's async engine and Alembic migration history. The database kind
  maps to a supported dialect/driver at one infrastructure boundary; do not
  add a hand-built ORM, generic provider hierarchy, or duplicated persistence
  implementation.
- Keep setup input DTOs separate from persisted models. A successful connectivity
  check cannot migrate, persist credentials, initialize accounts, or register a
  configuration source.
- Account passwords are one-way Argon2id hashes; reversible encryption is only
  for connection credentials needed again by a server-side connector. The
  encryption key comes from deployment configuration, not from the same database.
- Serialize first-admin creation and mutations that could remove the last admin
  with a database-owned guard row/transaction. No test double can prove this
  concurrency guarantee.
- The external bootstrap-completed marker must survive database outages and
  worker restarts; it is not inferred as “not initialized” from a failed DB
  read. Its durable multi-worker deployment mechanism remains a separate
  implementation/acceptance obligation.
- No migration/check test may contact an operator-provided or real database.
  Production dialect acceptance uses disposable, explicitly isolated
  PostgreSQL/MySQL instances and is recorded separately.

## First-run initialization — persistence ownership gate

The frozen `POST /api/v1/system/bootstrap/initialize` contract accepts the
selected database credentials, creates the first administrator, registers the
first rule source, and promises durable idempotency/initialization facts. The
implementation must not infer “uninitialized” from an unavailable database.
Before wiring that command, the service must have an explicit durable owner for
the runtime database locator and bootstrap completion/setup-window facts.

This is a real lifecycle boundary, not a request to add a generic provider
framework. Encrypting a database password and writing the ciphertext into the
same target database does not by itself solve startup: after a process restart,
the service still needs an independently available locator to open that
database before it can read/decrypt the record. The existing `SecretCipher`
protects stored secrets but does not provide that locator or multi-worker
coordination.

Required design contract before implementation:

- Name the deployment-owned authority that persists/loads the active database
  connection locator, setup-window state, and completed marker across restart
  and workers; define how first-run can write the selected target without
  relying on the target database being reachable first.
- Define ordering and failure recovery across the external runtime-configuration
  write, schema migration, first-admin/source transaction, operation receipt,
  and setup-window closure. A partial external write or lost HTTP response must
  not grant a second initialization or report an unsafe rollback.
- Keep raw database/rule-source credentials out of logs, receipts, audit,
  process arguments, URL paths, and permanent request objects. Any reversible
  secret storage uses a deployment-owned encryption key; test wrong-key,
  rotation, and restart behavior.
- Define the supported single-process/local and multi-worker/Kubernetes modes;
  never silently fall back to process memory or local SQLite for production.

| ID | Risk | Required focused/local evidence | Milestone evidence |
| --- | --- | --- | --- |
| BOOT-INIT-01 | Runtime cannot reconnect after restart or a worker reads stale DB config | Store/load contract test with secret-free representation and unavailable-authority failure | Restart and two-worker run using the selected deployment-owned authority |
| BOOT-INIT-02 | Two first-run requests create duplicate admins or sources | SQLite transaction/idempotency tests and failure injection | Competing transactions on isolated PostgreSQL and MySQL; exactly one initialized state |
| BOOT-INIT-03 | Migration, external config, or marker partial failure is mistaken for success/rollback | Each stage failure maps to a stable outcome; no false `initialized=true` | Restart after each injected failure and verify safe recovery/no second administrator |
| BOOT-INIT-04 | Lost response or repeated key duplicates setup or leaks submitted input | Same operator/key/canonical input returns the original safe receipt; changed input/actor conflicts | Multi-worker retry and actor isolation on each supported production dialect |
| BOOT-INIT-05 | Database/source credentials become observable or unrecoverable | Ciphertext/context/key-rotation tests; no secret in `repr`, receipt, API, audit, or captured logs | Restart with active/previous deployment keys and verify connector can retrieve only its owned secret |

### Selected runtime locator authority — file adapter slice implemented

The deployment-owned runtime database locator will be an explicit encrypted
configuration file outside the selected target database. The deployment must
pre-create and mount its parent directory as durable writable storage and
provide the encryption key ring out-of-band. This covers a single Console
instance with multiple worker processes; multiple hosts may share the same
mount only when its atomic-rename and advisory-lock guarantees have been
verified for that filesystem. The target database remains the authority for
initialized/admin/source/operation facts; a missing locator is the only
authoritative first-run signal, while an unreadable locator or an unreachable
configured database is unavailable and must fail closed.

The write boundary is a deployment-file Adapter implementing the application
locator Port. It uses the existing AES-256-GCM cipher with owner/field-bound
associated data, exact-schema JSON, sidecar advisory locking, revision CAS,
mode-0600 files, same-directory atomic replacement and fsync. This Adapter
candidate is chosen because it isolates filesystem durability and locking from
bootstrap policy; no GoF Command hierarchy is added. Initialization remains a
synchronous use case and the target DB receipt remains its idempotency
boundary. This design does not claim multi-host/NFS behavior without a specific
filesystem acceptance run; ordinary environment-variable-only runtime URLs,
process memory, and an implicit local-SQLite fallback are not production
fallbacks.

| ID | Risk | Required focused/local evidence | Milestone evidence |
| --- | --- | --- | --- |
| RUNTIME-LOCATOR-01 | Secret leakage or wrong-key acceptance | AES-GCM encrypt/decrypt, owner context, malformed envelope, missing key, secret-free repr/error | Restart with current/retained key ring in deployed secret manager |
| RUNTIME-LOCATOR-02 | Lost update or two workers overwrite setup | Competing revision CAS writers; only one expected revision succeeds | Multiple worker processes on the selected mounted filesystem |
| RUNTIME-LOCATOR-03 | Crash during replacement corrupts active locator | Temp-write/fsync/atomic-replace failure injection; previous complete revision remains readable | Process kill at each write boundary and restart |
| RUNTIME-LOCATOR-04 | Unsafe path or permissive file permissions | Reject relative path, symlink leaf/parent, non-regular or group/world-readable files; created lock/data mode 0600 | Deployment volume permissions and restart check |

The encrypted locator Port and POSIX file adapter are implemented, and the four
RUNTIME-LOCATOR local risks have focused coverage. No PostgreSQL/MySQL instance
is contacted by these local tests. This is not a completed first-run workflow:
startup activation, bootstrap transaction/recovery, operator grant persistence,
deployment mount/key provisioning, and real filesystem/production-dialect
evidence still remain required. The explicit environment configuration builds
the locator store and the runtime engine resolver; neither is wired into a
production launcher or setup transaction yet.

The setup candidate mapping accepts only PostgreSQL/MySQL with complete
credentials and a valid port, safely builds the async SQLAlchemy URL, and
remains a pure no-network operation. DNS pinning and TLS are deliberately left
to the deployment-owned connector before any connection is opened.

### Setup-window file authority — focused contract plan

The deployment-owned setup-window state is stored separately from the runtime
database locator. Absence of the state file means closed; only an explicit
open-state write enables first-run setup. Any malformed, unsafe, or unreadable
file is unavailable and never interpreted as open. The same-host local POSIX
atomic-file component owns locking, mode-0600 replacement, fsync, and byte-CAS;
the setup adapter owns only its exact JSON schema and mapping to the application
Port. `SENTINEL_CONSOLE_SETUP_WINDOW_PATH` selects the pre-provisioned file
location but never supplies an open/closed default. The config/store are
available for explicit composition; production launcher and initializer wiring
are still separate work. No process-local boolean or implicit environment
default is accepted.

| ID | Risk | Focused/local evidence | Deferred milestone evidence |
| --- | --- | --- | --- |
| SETUP-WINDOW-01 | Missing/corrupt state accidentally opens setup | Missing means false; duplicate/unknown fields, invalid revision, unsupported schema, wrong key shape fail closed | Restart and operator flow using provisioned deployment mount |
| SETUP-WINDOW-02 | Two workers overwrite a concurrent close/reopen | Byte-CAS with competing expected revisions; only one write succeeds | Multi-process test on the selected production mount |
| SETUP-WINDOW-03 | File contents/lock are replaced unsafely | Reject symlink, non-regular, permissive mode; temp+fsync+replace and directory fsync | Crash injection and mounted filesystem acceptance |
| SETUP-WINDOW-04 | Test claims multi-host/NFS guarantees from local behavior | State the adapter's local POSIX support boundary | Explicit two-host/filesystem deployment proof before that mode is supported |

## Account command follow-up — test design before implementation

The frozen HTTP contract is `POST /api/v1/accounts/commands` plus
`GET /api/v1/accounts/operations/{requestKey}`. The three command variants are
create, status change, and role change. This is a synchronous application
use-case over the existing discriminated HTTP request, not a background queue;
the database transaction and durable operation receipt are the idempotency
boundary. No GoF Command object hierarchy or second generic command framework
is planned.

| ID | Risk | Required local proof | Stronger acceptance still required |
| --- | --- | --- | --- |
| ACCT-CMD-01 | Missing/duplicate Origin, CSRF header/cookie, malformed or duplicate-key JSON, mismatched `Idempotency-Key` | ASGI tests prove rejection before mutation Port | Live browser-to-Console request |
| ACCT-CMD-02 | Anonymous/viewer can mutate or inspect another actor's operation | ASGI/API negative authorization; operation lookup is bound to current actor | Concurrent session/account revocation on PostgreSQL/MySQL |
| ACCT-CMD-03 | Username or password rules diverge from setup/login | Domain and command tests for UTF-16 bounds, ECMAScript trim/NFKC/case identity, role enum, 12–1024 password length | Cross-runtime vectors and production dialect uniqueness |
| ACCT-CMD-04 | Password or submitted command leaks into receipt, API, or audit | SQLite assertion that only Argon2id account hash is persisted; operation/audit projections contain no plaintext or credential fingerprint; response is allow-listed | PostgreSQL/MySQL schema and log review |
| ACCT-CMD-05 | Duplicate key repeats create or key reuse changes effect | SQLite composed API test: same actor/key/input returns the same safe receipt; changed input or actor is rejected; no second account/audit event | Multi-worker concurrent retry against PostgreSQL/MySQL |
| ACCT-CMD-06 | Stale revision, built-in demotion/disable, or last-admin race | Use-case rejection and SQLite guarded-transaction tests; mutation and receipt commit atomically | Competing transactions on both supported production dialects; prove at least one last-admin mutation is rejected |
| ACCT-CMD-07 | Persistence failure is mistaken for known rejection or leaks SQL details | ASGI failure maps to stable 503; transaction leaves no partial account/audit/receipt | Fault injection and recovery against production dialects |
| ACCT-CMD-08 | Completed-operation lookup returns mutable current state or another actor's data | Receipt snapshot matches the original request/effect and remains safe after later account changes | Browser unknown-outcome inspection without command replay |

Before implementation, the operation fingerprint must use a deployment-held,
domain-separated HMAC key rather than a plain digest of a password-bearing
request. Its key-version/rotation behavior must be stored with the operation
and tested; raw input and credential-derived digests must never be returned by
the operation API. Mutation, durable receipt, and audit facts must commit in
one transaction. SQLite tests are local first-pass evidence only; they cannot
close dialect locking, multi-worker idempotency, or last-admin concurrency.

### Account password value — implemented domain sub-slice (2026-10-08)

- `AccountPassword` enforces the account-create wire bounds of 12–1024
  UTF-16 code units, matching JavaScript string length. It preserves exact
  input text (no trim/normalization), rejects unpaired surrogates, and hides
  the value from `repr`.
- Isolated unit evidence: **4/4 passed** for minimum/maximum, astral Unicode
  counting, below/above bounds, unpaired surrogate rejection, and secret-free
  representation. This value is the domain boundary for the upcoming create
  use case; account command HTTP/persistence does not yet consume it.
- This sub-slice does not prove hashing/storage secrecy, account creation,
  cross-runtime production database behavior, or any browser flow. It does not
  close ACCT-CMD-03 or B0.2.

### Account command write path — local SQLite/ASGI slice (2026-10-08)

- Implemented the frozen synchronous account command contract for create,
  active/disabled status, and role changes. The application use case validates
  immutable domain values, computes domain-separated versioned HMAC request
  fingerprints, and hashes create passwords. The SQLAlchemy adapter rechecks
  the persisted admin session and CSRF digest inside the transaction, serializes
  mutations on the initialized guard row, and commits account mutation, safe
  immutable operation receipt, and audit event atomically. Receipt lookup is
  restricted to the original active admin actor; the API projection is
  allow-listed and contains no password, hash, fingerprint, session, or raw
  request body.
- Added Alembic revision `0003_account_command_receipts` and updated the local
  migration-head/schema assertions. Retaining an old fingerprint key while
  switching the active key allows a retry to recover its original receipt;
  dropping a historical key remains an explicit retention/operations decision.
- Focused ASGI + isolated SQLite tests: **6/6 passed**. They cover create and
  safe receipt replay after later mutation, changed-input idempotency conflict,
  HMAC-key rotation retry, viewer denial and cross-admin receipt isolation,
  status/role/stale revision/built-in/last-admin cases, and Origin/CSRF/
  duplicate-JSON rejection. Complete Console unittest suite on Python 3.12.14:
  **78/78 passed**. `compileall` and scoped `git diff --check` passed.
- Command used:
  `PYTHONPATH=src:tests:/private/tmp/sentinel-console-deps.viomBu:/Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel/.venv/lib/python3.12/site-packages /private/tmp/sentinel-console-account-identity-env-20261007/bin/python -m unittest discover -s tests -v`
- This evidence is only local ASGI + in-memory SQLite. `build_app` registers
  account commands only when explicitly injected; production startup does not
  yet wire this service. PostgreSQL/MySQL migration and row-lock semantics,
  multi-worker concurrent idempotency/last-admin behavior, production key
  loading/rotation, duplicate-username contention, setup persistence, password
  change, trusted-proxy rate-limit identity, and React-to-Python browser E2E
  remain unverified. **ACCT-CMD-01–08 and B0.2 remain open.**

## Own-password change — test design before implementation

The frozen contract is `POST /api/v1/auth/password`. The account is derived
only from the active session; input contains `currentPassword` and
`newPassword`, without confirmation or target account. The request is
CSRF/Origin protected and has unknown-outcome semantics: the browser must not
replay an unacknowledged password command. Local design selects the allowed
`reauthenticate` success disposition: update the one-way hash and revoke all
sessions for the account in one transaction, then clear browser cookies in the
response. A lost success response remains unknown; no read can prove whether
the password changed.

| ID | Risk | Required local proof | Stronger acceptance still required |
| --- | --- | --- | --- |
| PASS-01 | Wrong origin/CSRF, duplicate proof, unknown body fields or oversized/duplicate JSON reaches verifier | ASGI negative test asserts no credential read/write | Browser to production Console |
| PASS-02 | Password input rules differ from frozen schema | UTF-16 bounds for current/new password; no trim/normalization; no confirmation/target | React-Python vectors |
| PASS-03 | Wrong current password mutates account or enumerates another account | ASGI + SQLite negative test; unchanged hash/session/audit | Production dialect |
| PASS-04 | Successful change stores plaintext, preserves old sessions, or returns an unsafe shape | SQLite verifies Argon2id hash, all account sessions revoked, audit has no secret, response is `reauthenticate` and clears cookies | PostgreSQL/MySQL transaction proof and browser re-login |
| PASS-05 | Concurrent password change/session revocation races | Transaction rechecks current session, CSRF and expected prior hash before update | Concurrent PostgreSQL/MySQL test |
| PASS-06 | Database failure appears as success or exposes SQL/hash details | ASGI stable 503 and no partial update | Fault/recovery on production dialect |
| PASS-07 | Lost ACK causes password replay | Contract/UI rule is no automatic replay; document that local test cannot prove browser workflow | Browser unknown-outcome milestone |

No GoF pattern is selected: this is one synchronous use case with a minimal
credential-read boundary and one atomic persistence boundary; no queued,
retryable or multi-handler command execution is required.

### Own-password change — local implementation evidence (2026-10-08)

- Implemented `POST /api/v1/auth/password`. The HTTP boundary accepts only
  `currentPassword` and `newPassword`, derives the target account from the
  current cookie session, and checks exact Origin plus double-submit CSRF.
  Persisted CSRF/session proof is checked before Argon2 work and is checked
  again in the write transaction to close the race. Current-password
  verification uses the existing password hash service; the replacement is
  one-way Argon2id.
- The SQLAlchemy writer updates the password hash and account revision, revokes
  every session for that account, and appends a credential-free audit fact in
  one transaction. A DB failure rolls all three back. Confirmed success uses
  the frozen `reauthenticate` disposition and deletes both browser cookies.
  Password commands are non-replayable; browser handling of unknown ACK remains
  a later milestone acceptance.
- Focused ASGI + in-memory SQLite tests: **5/5 passed**. They cover admin/view
  self-service, wrong current password without mutation/audit, Origin/CSRF and
  malformed body rejection before expensive hash work, all-session revocation,
  Argon2id verification, safe response/audit, and transaction rollback on an
  induced database write failure. Complete Console unittest suite: **83/83
  passed** on Python 3.12.14; `compileall` and scoped `git diff --check` passed.
- This does not establish PostgreSQL/MySQL locking or concurrent password
  changes, production app composition, trusted-proxy/multi-worker login
  limiting, or browser unknown-outcome handling. Only the SQLite test database
  was used; no real database or configuration center was contacted. B0.2
  remains open.

## Risk-to-test matrix

| Risk | Required proof | Local first pass |
| --- | --- | --- |
| Package can't resolve selected dialects | Build and import extras for PostgreSQL, MySQL, and local SQLite | Install/build; no remote connection |
| Setup credentials appear in DSN repr/log | URL redaction test and captured log negative assertion | Unit test |
| Setup connection test has unintended writes | Test checks only connectivity; assert no DDL/DML or persisted credential | Service/adapter test |
| DNS rebinding after bootstrap | Persist the approved address and TLS hostname in the authenticated runtime locator, and use that exact target for runtime connections | Covered locally for locator v2 and runtime engine construction; real-dialect network verification remains pending |
| Initial schema differs from migration history | Apply Alembic head to empty disposable DB and inspect required constraints | SQLite local test; production dialects remain pending |
| Duplicate/case-variant username | Database unique constraint on canonical login key | SQLite + PostgreSQL/MySQL later |
| Cross-runtime username identity drift | The same trim/NFKC/lowercase vectors produce the same lookup identity in React mock and Python domain; UTF-16 input limit matches the browser contract | TypeScript + Python unit vectors; cross-dialect persistence collision check later |
| Password recoverable or unhashed | Argon2id verify/negative verify; stored field is encoded one-way hash | Unit test |
| Direct credential recoverable without deployment key | AEAD ciphertext differs from plaintext; wrong key/tampering rejects | Unit test |
| Concurrent first initialization creates two admins | Two concurrent transactions against same PostgreSQL/MySQL instance | Deferred; requires isolated dialect runtime |
| Last admin can be concurrently disabled/deleted | Two competing transactions preserve >=1 active admin or exactly one succeeds | Deferred; requires isolated dialect runtime |
| SQLite results are misrepresented | Every evidence record names SQLite as local only | Documentation/status gate |

### Account username identity contract (local design/test gate)

- Accept the submitted spelling/case for display after trimming surrounding Unicode whitespace;
  reject empty/whitespace-only values, unpaired UTF-16 surrogate input, and raw input longer
  than 200 UTF-16 code units (same limit as the browser's JavaScript string length).
- Derive identity from `NFKC(trimmed).lower()` using the runtime's Unicode normalization/case
  tables. This value is used for case/compatibility-insensitive duplicate checks and login lookup;
  the display username preserves the trimmed spelling.
- Persist only a fixed-width lowercase SHA-256 hex digest of the canonical value as
  `username_key` (64 ASCII characters), protected by a unique constraint. Do not persist a
  second clear-text canonical username column.
- React HTTP mocks use the same text canonicalization, not a separately invented locale rule.
  Python remains authoritative in live mode; the mock never proves server persistence.

Required local vectors before implementation: `" Admin "` and `"admin"` collide;
full-width `"Ａdmin"` and ASCII `"admin"` collide; case-sensitive display spelling remains
unchanged after trimming; composed/decomposed compatibility forms collide; whitespace-only,
201 UTF-16 code units, and unpaired surrogates reject; 200 code units accept. An SQLite
integration test must insert differently spelled records with the same digest and observe the
unique-constraint failure. PostgreSQL/MySQL and cross-runtime Unicode-version behavior remain
separate acceptance items; local tests must not claim those dialects were proven.

## Acceptance boundary

The initial implementation may establish models, a migration, pure secret/hash
utilities, and SQLite-local migration tests. B0.2 remains open until PostgreSQL
and MySQL migration/transaction behavior, browser setup persistence, bootstrap
marker recovery, and concurrent first-admin/last-admin cases are run against
isolated databases. No checkbox is earned by schema compilation or SQLite alone.

### First-run coordinator focused test design

| ID | Risk | Local assertion |
| --- | --- | --- |
| BOOT-COORD-01 | Wrong effect ordering exposes a locator to an unmigrated database | Migrate the prepared target before locator CAS; initialize only after locator persistence |
| BOOT-COORD-02 | Concurrent workers create two first admins or change the selected target | A dedicated local POSIX advisory lock spans target selection through setup-window closure; SQL transaction remains the final initialized-row guard |
| BOOT-COORD-03 | A failure before the admin transaction strands setup as closed | Failure before committed guard leaves setup window open; same-target retry can rerun migration and initialization |
| BOOT-COORD-04 | Process failure after the admin transaction leaves setup open indefinitely | `is_initialized()` and an idempotent initialization retry observe the durable guard then close the setup window |
| BOOT-COORD-05 | A different target silently overwrites an already initialized database | Existing target is checked under the deployment lock; initialized target cannot be redirected |
| BOOT-COORD-06 | Engine leaks or operation recovery bypasses authorization | Every created engine is disposed; operation reader uses the existing operator-session binding and never returns an operation from a different session |

These are service-level local tests. The lock only claims one shared local POSIX
filesystem, not multi-host/NFS coordination; PostgreSQL/MySQL, process-kill,
multi-worker, and browser E2E remain later acceptance gates.

## Target-database bootstrap transaction slice (2026-10-09)

`SqlAlchemyBootstrapInitializationTransaction` implements only the transaction
inside an already selected and migrated target database. In one transaction it
creates the built-in administrator (Argon2 hash only), encrypts and registers
the selected source using the same credential envelope as ordinary registry
mutations, records an HMAC input fingerprint and secret-free operation receipt,
adds a bounded audit event, then flips `console_guard.initialized`. A repeated
request from the same operator session with an identical input recovers the
same receipt; a reused request key with different input is an explicit 409.
Target-store failure rolls back the entire group of SQL facts.

Local evidence:

- ASGI initialization route: **8 passed**, including the new idempotency-conflict
  response contract.
- Target transaction on disposable SQLite: **6 passed**, including successful
  secret encryption/one-way hashing, replay, changed-input conflict, initialized
  database rejection, and a failed-hash rollback with no partial rows.
- Nacos direct credentials and Consul credential references both use the
  registered-source authenticated-encryption envelope; raw values are absent
  from stored row projections.
- Registered-source SQL store regression: **8 passed**. Two session fixtures had
  expired because they used a fixed historical timestamp; their setup now uses
  a current UTC instant, after which all eight pass.
- `compileall` and scoped `git diff --check` passed. No full Console suite or
  E2E was run.

This transaction adapter is not production first-run composition. The caller
must supply the engine already bound to the submitted, deployment-approved
database. The adapter does not resolve/pin DNS, create the DB, run Alembic,
persist the encrypted runtime locator, close the separate setup window, or
coordinate restart recovery across those stores. Those boundaries remain open;
SQLite evidence does not prove PostgreSQL/MySQL lock behavior. No B0.2 closure
or external-database acceptance is claimed.

## Pinned bootstrap SQL engine factory

`BootstrapDatabaseEngineFactory` now composes the candidate validator with the
deployment-owned target policy before producing a prepared bootstrap result.
The result owns a lazy SQLAlchemy engine plus a secret-suppressed locator URL
and `RuntimeDatabaseTarget` derived from the *same* DNS resolution. The factory
rejects unsupported SQLite candidates and never constructs an engine before
the host, port, database kind, and all resolved addresses pass policy.
PostgreSQL keeps the requested hostname for `verify-full` certificate checking
while pinning the socket through `hostaddr`; it chooses the first approved
address and stores that choice. MySQL uses the approved addresses as the socket
hosts and the original hostname only during verified TLS hostname checking.
An unavailable optional MySQL driver fails with a stable dependency error. The
caller owns and must dispose the prepared engine.

Runtime locator schema v2 stores the database URL and target metadata together
inside the authenticated encrypted payload. Its runtime resolver validates
hostname consistency and recreates PostgreSQL `hostaddr` or the MySQL pinned
async connector instead of resolving the submitted hostname again. Schema v1
locators remain readable for deployments that provisioned their URL out of
band; those legacy records have no pin and retain legacy operator-owned DNS
semantics, so they are not evidence that a UI-submitted target is pinned.

Focused local evidence (Python 3.12.14):

- `python -m unittest tests.test_bootstrap_database_engine tests.test_bootstrap_database_connector tests.test_database_runtime`:
  **25 passed**.
- `python -m pytest tests.test_runtime_database_locator_file_store -q`:
  **8 passed**, including AEAD-protected target round-trip and legacy v1 read.
- The tests replace engine creation and the MySQL driver with fakes. They prove
  construction arguments and the socket/TLS hostname split, not live DNS,
  PostgreSQL/MySQL server behavior, TLS handshake, migration, or concurrency.
- No remote database, configuration center, browser, or full E2E was used.

The next composition still needs to order: acquire a deployment-wide setup
lock, verify the one-time setup authority, create the prepared pinned engine,
run Alembic, execute the existing target-database initialization transaction,
persist its encrypted URL and target facts, and close the external setup window
with crash-safe recovery. These effects span the target database and
deployment-owned files; they must be coordinated so a restart cannot reopen
initialization after the admin transaction committed. At the time of this
factory-slice note, the coordinator had not yet been wired; its later local
implementation evidence is recorded below. Production launcher wiring and
deployment acceptance remain open, so B0.2 remains open.

## Cross-store bootstrap coordinator — focused local evidence (2026-10-09)

`SqlAlchemyBootstrapInitializationCoordinator` now owns the recoverable order
across deployment files and the selected target database: it serializes the
workflow with a dedicated local POSIX lock, rechecks the operator grant and
setup window, resolves/pins the submitted target, runs Alembic before storing
the encrypted runtime locator, then delegates the first-admin/source/receipt/
audit/guard write to the existing single-database transaction. It disposes
every engine it creates. A retry with the same pinned URL reuses the locator
instead of resolving a new target. On a subsequent bootstrap read, a committed
database guard closes a setup marker left open by a process crash after commit.
Setup-window close is idempotent and bounded under concurrent CAS writers.

| Risk | Focused test | Result |
| --- | --- | --- |
| Initialization side effects run in unsafe order | Coordinator unit test | **Pass** — target migration → encrypted locator write → DB transaction → close marker → dispose |
| Migration fails after candidate selection | Coordinator unit test | **Pass** — engine disposed; locator and setup marker unchanged |
| DB unavailable after locator is durable | Coordinator retry test | **Pass** — retry uses the pinned locator; no new DNS resolution or locator rewrite; marker remains open |
| Process stopped after target DB commit | Coordinator recovery test | **Pass** — committed guard is read and the setup marker is closed |
| Unauthenticated/closed setup reaches DB work | Coordinator unit test | **Pass** — rejected before candidate engine creation |
| Concurrent close or cancelled lock holder strands setup | Setup-window/local-lock tests | **Pass** — idempotent close remains closed; cancellation releases the local lock |

Python 3.12.14 focused evidence: coordinator + pinned-engine-factory + target
transaction **16 passed** with `unittest`; setup-window + runtime-locator
file-store **20 passed** with `pytest`; touched modules passed `compileall`.
These tests use fakes and temporary local files/SQLite. They do not prove real
PostgreSQL/MySQL migration/locking, a deployment mount, process restart across
separate OS workers, or browser-to-Python behavior.

This coordinator is not yet wired into a production launcher or a complete
application composition. Operator-code provisioning/rotation and multi-worker
grant/rate-limit ownership remain deployment authorities; preprovisioned-mode
engine lifecycle and the TLS trust configuration must share one production
composition before the service can claim a supported startup path. B0.2 stays
open. No browser, full E2E, real database, or configuration center was used;
the complete browser journey remains reserved for final acceptance.

## Lazy runtime engine bridge — test design before implementation

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| DB-LAZY-01 | Setup-mode request silently falls back to another database | Adapter/service | Missing locator fails closed; engine factory is not called |
| DB-LAZY-02 | Two concurrent first requests create different pools | Adapter concurrency | One locator read/build/migration; both receive the same engine |
| DB-LAZY-03 | Setup initialization completes while process remains alive | ASGI lifecycle | Locator is observed after initialization; the next SQL operation can create the runtime engine without restart |
| DB-LAZY-04 | Invalid locator or migration failure leaks an engine or raw credentials | Failure/cleanup | Safe SQLAlchemy failure; any constructed engine is disposed; next operation can retry |
| DB-LAZY-05 | Shutdown leaks the cached runtime pool | Lifecycle | App lifespan disposes the cached engine exactly once |

This is an internal lazy-access Proxy over the existing `AsyncEngine`
`connect()`/`begin()` surface. It does not alter query or transaction
semantics; focused fake-engine tests prove delegation, while SQLite lifespan
tests prove lifecycle only. PostgreSQL/MySQL remains a later isolated
integration gate. No browser E2E is run in this slice.

## Lazy runtime engine bridge — implementation evidence (2026-10-09)

`RuntimeDatabaseEngineProvider` and `RuntimeDatabaseEngineBridge` now implement
that boundary. A missing locator keeps setup mode active and SQL operations
fail closed without constructing an engine. Once the initialization
coordinator persists the locator, the next SQL operation in the same process
creates and migrates one cached engine. Concurrent first use shares the
provider lock. Once activated, a different locator revision is rejected rather
than silently redirecting active services. ASGI startup validates/migrates an
existing locator, and shutdown disposes the pool. The SQL app composition only
accepts lazy runtime mode when the initialization coordinator's reader,
initializer, operation reader, and database checker are all explicitly wired.

Focused local evidence (Python 3.12.14):

- `test_runtime_database_engine_provider`: **6 passed**.
- `test_identity_composition`: **4 passed**, including provider lifecycle
  wiring and rejection of incomplete setup composition.
- `test_asgi_database_lifecycle`: **2 passed** for the pre-provisioned path.
- `compileall` and `git diff --check` passed for touched files.
- SQLite and mocks only; no real PostgreSQL/MySQL, browser, full E2E, or remote
  configuration center was used. Full E2E remains reserved for final acceptance.

**Current worktree re-verification (2026-10-13, Python 3.13.15):**
`test_runtime_database_engine_provider`, publication/activation worker
lifecycles, and bootstrap initialization API tests: **30 passed**. The new
worker-after-setup lifecycle also uses the real encrypted
`RuntimeDatabaseLocatorFileStore`: the ASGI process starts with no locator,
the publication worker and activation-plan scheduler retry without warnings,
setup writes an encrypted locator file, and both workers observe it on the
next poll without a process restart. They share one lazily created file-backed
SQLite engine and each executes `SELECT 1`. The test checks that the persisted
file does not contain the synthetic database hostname or password. This
exercises the real local locator persistence boundary; the injected SQLite
engine factory and migration remain test-only and do not replace the
PostgreSQL/MySQL acceptance gates above. `compileall` and `git diff --check`
passed; Ruff was unavailable in this environment.

The bridge is internal infrastructure and preserves only the `connect()` and
`begin()` methods already used by the SQL adapters. It does not constitute a
production launcher, operator-code provisioner, distributed bootstrap grant or
rate limiter, production TLS trust setup, multi-process acceptance, or B0.2
closure.

## First-run ASGI deployment entry point — focused local evidence (2026-10-09)

`sentinel-console serve` and `python -m atlas_richie.sentinel_console serve`
load explicit first-run configuration and compose the ASGI service. Binding
defaults to loopback; Uvicorn proxy rewriting is disabled so forwarded client
identity is resolved only by the app's configured trusted CIDRs. Configuration
parsing rejects missing key material, wildcard database networks, invalid
source target rules, invalid browser origins and non-absolute CA/authority
paths with generic errors. PostgreSQL and MySQL may use deployment-owned CA
bundles; MySQL hostname and certificate verification remain enabled. Local
`setup-window status/open/close` commands
provide explicit setup-window provisioning: absent state remains closed,
opening requires operator configuration, updates use revision compare-and-set,
and secrets are never printed. Composition rejects overlapping local authority
file paths and non-positive session lifetimes.

The focused local suite for CLI, setup-window persistence, deployment parsing,
first-run composition, identity composition and static-web base paths passed
**21/21** on the existing
Python 3.13.15 Console virtual environment. `compileall` and `git diff --check`
also passed. A system Python 3.9 attempt was invalid for this Python >=3.12
package; `uv` could not fetch missing packages because sandbox network access is
restricted, so the existing project virtual environment was reused.

This establishes a local launcher/composition path, not deployment acceptance.
No PostgreSQL/MySQL server, reverse proxy, multi-worker topology, installer
secret-delivery path, or React-to-Python browser E2E was exercised. Local setup
state uses POSIX file locking and is not a shared-filesystem/multi-host
guarantee. B0.2 remains open.

## Disposable PostgreSQL migration and last-admin concurrency (2026-10-10)

### Risk-to-test matrix

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| DB-PG-01 | A real PostgreSQL migration fails although SQLite accepts it | Migration integration | A fresh disposable PostgreSQL 16 database reaches head and a second upgrade is a no-op |
| DB-PG-02 | Concurrent administrator role changes leave no active administrator | Transaction integration | Two competing self-demotions produce one completion and one `last_admin` rejection; persisted active-admin count remains exactly one |
| DB-PG-03 | The test accidentally targets a shared database | Test safety | Require an explicit URL, loopback/test hostname, and a database name beginning `sentinel_console_test_`; run only against a throwaway container with no persistent volume |
| DB-PG-04 | Competing first-run requests create duplicate administrators or sources | Bootstrap transaction integration | Competing initialization transactions leave one initialized guard, one built-in admin/source, two safe receipts/audits, one completed result, and one `setup-closed` rejection |
| DB-PG-05 | A concurrent retry duplicates initialization or leaks a receipt across operators | Idempotency/authority integration | Same operator/key/input concurrent retries return one identical receipt and persist one operation/audit; changed input conflicts and a different valid operator is forbidden |
| DB-PG-06 | Login/session/password adapters only work on SQLite | ASGI + real SQL dialect integration | SQL-composed app can login, read current identity, change password, revoke the old session, reject the old password, and accept the new password; persisted credentials remain hashed and audit contains no secret |
| DB-PG-07 | First-run HTTP coordinator differs from its isolated transaction tests on PostgreSQL | ASGI + real SQL dialect integration | The actual first-run app authorizes the operator, initializes the target DB, persists the built-in admin and encrypted source credential, returns/replays the receipt, and closes setup |
| DB-MYSQL-01 | MySQL DDL semantics differ from SQLite/PostgreSQL | Migration integration | Fresh MySQL 8.4 reaches head, repeats cleanly, stores long revision IDs, and preserves the fixed singleton key |
| DB-MYSQL-02 | Concurrent account mutations violate last-admin invariant under InnoDB | Transaction integration | Pause one in-flight demotion after guard lock; concurrently demote both admins; assert one `last_admin` rejection and one active administrator remains |
| DB-MYSQL-03 | Competing first-run requests create duplicate administrators or sources | Bootstrap transaction integration | Competing initialization transactions leave one initialized guard, one built-in admin/source, two safe receipts/audits, one completed result, and one `setup-closed` rejection |
| DB-MYSQL-04 | A concurrent retry duplicates initialization or leaks a receipt across operators | Idempotency/authority integration | Same operator/key/input concurrent retries return one identical receipt and persist one operation/audit; changed input conflicts and a different valid operator is forbidden |
| DB-MYSQL-05 | Login/session/password adapters only work on SQLite | ASGI + real SQL dialect integration | SQL-composed app can login, read current identity, change password, revoke the old session, reject the old password, and accept the new password; persisted credentials remain hashed and audit contains no secret |
| DB-MYSQL-06 | First-run HTTP coordinator differs from its isolated transaction tests on MySQL | ASGI + real SQL dialect integration | The actual first-run app authorizes the operator, initializes the target DB, persists the built-in admin and encrypted source credential, returns/replays the receipt, and closes setup |

### Result

`tests/test_postgresql_acceptance.py` and
`tests/test_mysql_migration_acceptance.py` are opt-in via
`SENTINEL_CONSOLE_TEST_POSTGRES_URL` and `SENTINEL_CONSOLE_TEST_MYSQL_URL`.
Their URL guards reject unexpected driver names, non-loopback/non-test hosts
and database names without the dedicated test prefix. Each recorded run used
a fresh official database container with an ephemeral writable layer and
loopback-only port publishing; each container was removed at test exit. Full
Alembic upgrade and repeat-upgrade passed on PostgreSQL 16 and MySQL 8.4.11.

The PostgreSQL run exposed that Alembic's default revision table uses
`VARCHAR(32)` while revision `0017_scheduled_rule_publication_origin` is longer.
Migration 0017 now widens `alembic_version.version_num` to `VARCHAR(128)` on
PostgreSQL/MySQL before Alembic records the revision. The MySQL run also found
that a primary-key `SmallInteger` was implicitly rendered as `AUTO_INCREMENT`,
which is illegal when the same singleton column participates in a check
constraint. The initial migration and ORM mapping now explicitly disable
autoincrement for `console_guard.singleton_id`.

The PostgreSQL and MySQL concurrency tests each seed two synthetic admins,
install a short-lived DB trigger that pauses a role update, and concurrently
demote both admins. Exactly one mutation completes and one is rejected as the
last admin; the persisted active-admin count remains one. Triggers and
synthetic rows are removed in `finally`. The MySQL migration test also asserts
that the singleton key is not auto-incrementing and the revision column is 128
characters.

- PostgreSQL 16 migration + concurrency acceptance: **1 passed**.
- MySQL 8.4.11 migration/schema + concurrency acceptance: **2 passed**.
- SQLite account/migration regression set: **13 passed, 3 skipped** (database-
  specific tests require their explicit URLs).
- `compileall` and `git diff --check`: passed.

This does not verify a production database, multi-worker deployment, first-run
lifecycle end to end, or React-to-Python browser E2E. B0.2 remains open until
those independent requirements are accepted.

## Competing first-run transactions on production SQL dialects (2026-10-10)

`tests/bootstrap_database_acceptance_support.py` now exercises two concurrent
calls to the real `SqlAlchemyBootstrapInitializationTransaction` against the
same migrated database. A temporary dialect-specific trigger briefly pauses
the winner while it flips the singleton guard, making the competing request
observe the committed closed state. The test requires exactly one completed
receipt and one `setup-closed` rejection; verifies one initialized guard,
exactly one built-in admin and registered source, and one durable receipt/audit
per request; and scans the persisted admin/source/receipt/audit projection for
the synthetic admin, configuration-source, and database passwords. Trigger
and only the test-namespaced records are removed in `finally`.

- PostgreSQL 16 disposable acceptance: **2 passed** (bootstrap race plus
  migration/repeat-upgrade and last-admin race).
- MySQL 8.4.11 disposable acceptance: **3 passed** (bootstrap race plus
  migration/schema and last-admin race).
- Focused Console regression set: **25 passed, 5 skipped**; the skips are the
  opt-in PostgreSQL/MySQL cases when their explicit disposable-database URLs
  are absent.
- Python compile and `git diff --check`: passed.

The opt-in dialect suites additionally race two identical same-key retries
through two separately constructed SQL adapters, then construct a fresh adapter
to read and replay the persisted receipt. They recover the same completed
receipt without duplicating the operation, audit, admin, or source; changed
input with the original key raises the stable idempotency conflict, and another
currently valid operator cannot recover the receipt. Final isolated-container
runs: PostgreSQL 16 **3 passed** and MySQL 8.4.11 **4 passed**. The broader
focused Console regression is **25 passed, 7 skipped** (all seven are opt-in
PG/MySQL tests without an explicitly supplied test URL). Compile and
`git diff --check` passed.

This proves the target-database first-run transaction serializes competing
requests and same-key retries on these two real dialects and does not persist
the submitted secrets in the inspected records. It does not prove the full
cross-store coordinator, deployment secret delivery, ingress/multi-worker
topology, TLS/database target policy, or browser-to-Python workflow against
PostgreSQL/MySQL. B0.2 remains open.

## SQL-composed identity HTTP path on PostgreSQL and MySQL (2026-10-10)

The opt-in PostgreSQL/MySQL acceptance suites now also exercise the production
SQL identity composition through ASGI. Each case migrates a fresh disposable
database, inserts a synthetic built-in administrator with an Argon2id password,
and calls login, current-session read, own-password change, anonymous session
recheck, old-password rejection, and new-password login. Database assertions
verify the rotated hash, revocation of the original session, hashed session and
CSRF material, the password-change audit fact, and absence of submitted
password/session values from the inspected account/session/audit projection.
The unique fixture rows are deleted in `finally`; no real account or database
is used.

- PostgreSQL 16 disposable suite: **4 passed**.
- MySQL 8.4.11 disposable suite: **5 passed**.
- Focused identity/bootstrap Console regressions: **34 passed**.
- Python `compileall`, source 88-column check, and `git diff --check`: passed.

The first MySQL attempt failed before executing assertions because the readiness
probe connected to the official image's temporary initialization server, which
shuts down before the final server starts. The rerun waited for a successful
TCP connection to the published 3306 endpoint; the complete suite then passed.
This is test-harness startup behavior, not a product-code failure.

This proves the SQL-composed identity path against the two tested database
dialects in disposable local containers. It does not verify production TLS,
deployment secret delivery, ingress/multi-worker operation, full setup
coordinator recovery, or React-to-Python browser E2E. B0.2 remains open.

## Runtime activation after authorized first-run setup (2026-10-10)

The PostgreSQL/MySQL first-run HTTP acceptance now continues past the setup
response: it reconstructs a fresh first-run ASGI app from the same deployment
paths, starts its `RuntimeDatabaseEngineProvider` from the encrypted locator,
retains the approved hostname/address metadata, repeats the idempotent migration
on the real disposable database, and calls the bootstrap read route to confirm
the initialized guard. Lifespan exit must dispose the runtime engine exactly
once. This checks persisted first-run state through the reconstructed app, not
only through the setup-time coordinator.

- PostgreSQL 16 disposable acceptance: **5 passed**.
- MySQL 8.4 disposable acceptance: **6 passed**.
- Runtime-provider and SQLite first-run focused regression: **7 passed**.
- Changed Python source compiled; `git diff --check` passed; the changed file
  conforms to the 88-column source check.

The runtime provider and restart-time coordinator engine factories are replaced
with factories pointed at the disposable database URL. Thus these tests prove
locator decryption, reconstructed first-run ASGI startup/readiness, actual-
dialect migration, initialized-state readback, and runtime pool disposal, but
not production DNS pinning, PostgreSQL `verify-full`, MySQL TLS identity, or
deployment secret delivery. The first run also exposed two test-harness gaps:
the disposable MySQL image required `log_bin_trust_function_creators` for its
concurrency triggers, and the reconstructed coordinator needed the same
loopback database mapping as the runtime provider. Both were corrected in the
test harness; no product configuration was weakened. No existing database or
configuration center was used; full React-to-Python E2E remains reserved for
the final acceptance. B0.2 remains open.

## Authorized first-run ASGI flow on PostgreSQL and MySQL (2026-10-10)

The opt-in dialect suites now include a final, real-SQL first-run HTTP scenario.
It builds `build_first_run_sql_identity_app`, reads the uninitialized gate,
authorizes a synthetic operator, submits a complete database/admin/Consul setup,
checks the completed response and durable operation receipt, then verifies the
setup gate is closed and a valid repeat is rejected. Database reads confirm one
built-in admin with a verifiable Argon2id password hash and an encrypted source
credential payload; the runtime locator and operator-authority files do not
contain their submitted plaintext secrets. Test setup is synthetic and the
database container is disposable.

- PostgreSQL 16 opt-in suite: **5 passed**.
- MySQL 8.4.11 opt-in suite: **6 passed**.
- Focused login/password/identity/bootstrap regression: **34 passed**.
- `compileall` and the changed Python files' 88-column check: passed.

The ASGI app, coordinator, migrations, transaction, SQL persistence, locator
encryption and file authorities are exercised; only the bootstrap engine
factory's network connection is replaced so the synthetic candidate maps to
the loopback-only disposable database. Therefore this is real-dialect
persistence evidence, not acceptance of DNS pinning, production TLS, ingress,
or secret-delivery configuration. No browser or configuration center was used;
B0.2 remains open.

## Installed-wheel CLI startup in closed first-run mode (2026-10-10)

The current Console wheel plus its runtime and optional Uvicorn server
dependencies were installed into a disposable isolated target. The packaged
`python -m atlas_richie.sentinel_console serve` module entry point and generated
`bin/sentinel-console serve` console script were each launched with synthetic
deployment keys/state under `/private/tmp`, bound only to `127.0.0.1`, and
stopped after checking the HTTP responses:

- `GET /` returned the packaged HTML with **200**.
- `GET /api/v1/system/bootstrap` with a valid request ID returned
  `initialized=false` with **200**.
- The setup window remained closed; no SQL database or configuration center
  was contacted.

This proves the installed artifact can start and serve the closed/uninitialized
first-run shell. It does not prove authorized initialization against
PostgreSQL/MySQL, production TLS/proxy/multi-worker behavior, deployment secret
delivery, or React-to-Python browser E2E. B0.2 remains open.

## Setup-window CAS across independent local worker processes (2026-10-11)

Re-ran `tests/test_setup_window_file_store.py`, including
`test_independent_worker_processes_compare_and_swap_one_setup_window`. Two
spawned processes read the same revision and race opposite updates against a
temporary local POSIX directory. Exactly one write succeeds, the other receives
`SetupWindowRevisionConflict`, and a fresh read matches the winning revision
and value.

- `uv run --extra test pytest -q tests/test_setup_window_file_store.py` —
  **13 passed**.
- `git diff --check` — passed.

This is local multi-process advisory-lock/CAS evidence only. It does not prove
the behavior of a deployment-specific shared volume, cross-host locking, or
production ingress/secret delivery; no database or Docker container was used.
B0.2 remains open.

## Shared SQL login cooldown across app instances — test design (2026-10-12)

| Risk | Layer and setup | Action | Required evidence |
| --- | --- | --- | --- |
| Login throttling is accidentally process-local or loses concurrent first failures | Real disposable MySQL/PostgreSQL; two separately composed SQL identity ASGI apps with independent engine pools, same HMAC key/policy, and the same synthetic remote client | Both apps concurrently receive a wrong-password request from the same client; an app then receives a correct password from that client | Both in-flight attempts retain generic `401 unauthenticated`; the subsequent correct attempt returns `429 rate_limited` with bounded positive `retryAfterMs`, proving the shared SQL row serialized both concurrent failures before valid credential acceptance |
| Raw identity material is persisted | Inspect only the unique limiter row created by this test | Compare stored subject digest with a locally derived HMAC and inspect row fields | Exactly one matching digest row records the threshold/block state; neither client address nor username is stored; cleanup deletes that digest and synthetic account |
| One app can clear another app's cooldown | Same two real app/pool compositions | Directly expire only this test's block row, then authenticate successfully through App B | Login succeeds and the shared HMAC row is deleted; this uses controlled test-data mutation, not a production clock override |
| Separate OS workers lose concurrent first failures | Real disposable MySQL; two spawned worker processes with independent async engines and one synthetic digest | Release both processes together; each records two failures for that digest | Both workers exit successfully; one durable row reaches exactly the configured threshold and is blocked; cleanup deletes only that digest |
| HTTP login cooldown is accidentally process-local despite a multi-worker CLI starting | Real disposable MySQL/PostgreSQL; two independent production CLI processes with distinct loopback ports, same runtime locator, HMAC key, policy, and SQL database | Send one invalid login to process A, one to process B, then another to process B | A and B each return the first generic 401; B's second request returns bounded 429 and the shared SQL row is exactly at threshold. This proves the limit is shared across process boundaries rather than merely proving that two worker processes started |

No Nacos/Consul or browser is involved in this slice. It supplements—not
replaces—the separate final React-to-Python E2E and does not close B0.2.

### Implementation evidence

- Added the same acceptance to the opt-in PostgreSQL and MySQL suites. It builds
  two independent SQL-composed ASGI apps backed by separate engine pools and
  uses a fixed synthetic client address with the same deployment HMAC key.
- Disposable MySQL **8.4.11** run: `./tools/with_disposable_e2e_dependencies.sh
  uv run --extra test --extra mysql pytest -q
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_login_cooldown_is_shared_across_app_instances`
  — **1 passed**. Two concurrent invalid attempts through different apps
  returned generic 401; a correct password through the second app returned
  bounded `429 rate_limited`; a different client authenticated; after the
  exact test row's cooldown was expired, the original client authenticated and
  its HMAC row was cleared.
- The SQL assertion confirmed the expected HMAC digest and threshold row; raw
  username/client address were not persisted. SQLite limiter regression:
  **7 passed**. Ruff lint, touched test-module format checks, extracted helper
  formatting, `compileall`, and `git diff --check` passed.
- The harness-created MySQL and Consul containers were checked by exact name
  after exit and were absent. PostgreSQL has the same opt-in test but was not
  run in this slice.

This proves shared throttling across independent app compositions/connection
pools on MySQL, not separate OS processes, production ingress/proxy identity,
PostgreSQL parity, or React-to-Python browser E2E. B0.2 remains open.

### Spawned worker process acceptance (2026-10-12)

The app-instance scenario above proves HTTP behavior across separate engine
pools within one test process. A second opt-in MySQL case now starts two
independent Python `spawn` workers, each creating its own async engine and
recording two failures against the same synthetic digest after a shared start
gate opens. The parent process verifies one durable row has exactly four
failures and a non-null block expiry, then deletes only that digest row.

- Disposable MySQL 8.4.11: `./tools/with_disposable_e2e_dependencies.sh uv run
  --extra test --extra mysql pytest -q
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_login_cooldown_serializes_across_processes`
  — **1 passed**.
- Ruff lint, formatting of the new helper excerpt and touched acceptance class,
  `compileall`, and `git diff --check` passed. The exact temporary MySQL and
  Consul container names were checked after exit and were absent.

This validates SQL-backed failure-count serialization across separate local
OS processes against disposable MySQL. It is not an HTTP load test across
Uvicorn workers, a multi-host/shared-network deployment test, or production
proxy identity acceptance; B0.2 remains open.

### Spawned worker process acceptance on PostgreSQL (2026-10-13)

The process-level limiter helper is now dialect-neutral and is exercised by
both production database acceptance classes. PostgreSQL uses the same isolated
TLS runner as the other persistence tests; two `spawn` workers each record two
failures against one synthetic client digest. The parent confirms one durable
row reaches `failure_count=4` and a non-null `blocked_until_ms`, then deletes
only that digest row.

- Disposable PostgreSQL 16: `tools/with_disposable_postgresql_acceptance.sh uv
  run --extra test --extra postgres pytest -q
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_sql_login_cooldown_serializes_across_processes`
  — **1 passed**.
- Disposable MySQL 8.4.11 regression after making the helper dialect-neutral:
  `tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql
  pytest -q
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_login_cooldown_serializes_across_processes`
  — **1 passed**.

This proves database-dialect parity for local cross-process SQL serialization,
not distinct Uvicorn-worker HTTP routing, NFS/RWX or multi-host behavior,
production ingress/proxy identity, or browser-to-Python E2E. Runner-owned
containers and temporary CA material are removed by their respective owners;
B0.2 remains open.

### Two Uvicorn workers serve MySQL-backed login cooldown over HTTP (2026-10-13)

The PostgreSQL dual-worker HTTP acceptance in the tracker now has a MySQL
dialect counterpart. Run from `components/sentinel/sentinel-console`:

```text
tools/with_disposable_e2e_dependencies.sh uv run --no-sync --extra test \
  --extra mysql pytest -q --tb=short \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_two_uvicorn_workers_serve_mysql_login_cooldown_over_http
```

Result: **1 passed in 3.55s** against disposable TLS MySQL 8.4.11 and Consul
1.21.1. The test starts the real `python -m atlas_richie.sentinel_console
serve` CLI with exactly two Uvicorn workers and an initialized runtime locator,
sends concurrent invalid login requests (two `401` responses), then verifies
the subsequent request is denied with `429 rate_limited` and the SQL row has
one client digest with `failure_count=2`. It also asserts that both Uvicorn
server processes actually started. Test-owned MySQL
`sentinel-e2e-mysql-bf0e02414964b7224fcca2d6b93656fe` and Consul
`sentinel-e2e-consul-bf0e02414964b7224fcca2d6b93656fe` were absent after the
runner exited.

This closes only the local MySQL dual-worker HTTP limiter slice. It does not
prove PostgreSQL/MySQL multi-host or NFS/RWX coordination, production ingress
identity/TLS, external secret delivery, or React-to-Python browser E2E; B0.2
remains open.

### Two Uvicorn workers serve PostgreSQL-backed login cooldown over HTTP (2026-10-13)

Run from `components/sentinel/sentinel-console`:

```text
tools/with_disposable_postgresql_acceptance.sh uv run --no-sync --extra test \
  --extra postgres pytest -q --tb=short \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_two_uvicorn_workers_serve_postgresql_login_cooldown_over_http
```

Result: **1 passed in 3.46s** against the disposable PostgreSQL service created
by the owner runner. The acceptance starts the real `python -m
atlas_richie.sentinel_console serve` CLI with exactly two Uvicorn workers,
sends concurrent invalid login requests, and verifies the shared SQL-backed
cooldown over HTTP plus both server processes. The runner-owned PostgreSQL
container and temporary CA were removed on exit; a post-run container query
found no `sentinel-e2e-postgres-*`, `sentinel-e2e-mysql-*`, or
`sentinel-e2e-consul-*` containers.

Together with the MySQL result above, this closes the local PostgreSQL/MySQL
dual-worker HTTP limiter parity slice. It does not prove multi-host or NFS/RWX
coordination, production ingress identity/TLS, external secret delivery, or
React-to-Python browser E2E; B0.2 remains open.

### Independent Console processes share login cooldown over HTTP (2026-10-13)

The prior dual-worker cases asserted that both Uvicorn worker processes started,
but requests through a shared listener did not identify which PID served each
request. The strengthened acceptance now keeps that startup assertion for CLI A
(two workers) and starts an independent CLI B (one worker) against the same
disposable SQL database and runtime policy. It sends one failed login to A,
then one to B, then another to B. B's final request can be rate-limited only if
the SQL state written through A is visible across the separate CLI process.

- Disposable MySQL 8.4.11 + Consul 1.21.1:
  `tools/with_disposable_e2e_dependencies.sh uv run --no-sync --extra test
  --extra mysql pytest -q --tb=short
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_two_uvicorn_workers_serve_mysql_login_cooldown_over_http`
  — **1 passed in 3.56s**.
- Disposable PostgreSQL 16:
  `tools/with_disposable_postgresql_acceptance.sh uv run --no-sync --extra test
  --extra postgres pytest -q --tb=short
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_two_uvicorn_workers_serve_postgresql_login_cooldown_over_http`
  — **1 passed in 3.36s**.
- In both cases A→B→B returned **401 / 401 / 429**; the shared SQL row ended
  at `failure_count=2`. CLI A logs exactly two started server processes and
  CLI B exactly one. Both owner runners removed their disposable containers;
  a post-run query found no `sentinel-e2e-(mysql|postgres|consul)-*` containers.

This is direct local cross-CLI-process HTTP evidence for SQL-backed cooldown,
not a multi-host/NFS/RWX, production ingress/identity, external-secret, or
React-to-Python browser E2E acceptance. B0.2 remains open.
