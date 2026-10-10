# B0.1 Rule Binding Registration — Focused Acceptance Record

## Scope and ownership

The Console relational database owns rule-binding management metadata and the
exact non-secret provider target mapping. Nacos/Consul remain the sole stores of
rule arrays and active snapshots. This slice creates one binding and its target
atomically; it does not write or probe the configuration center. The request
must identify an already registered source and its expected revision. Provider
identity and display label are derived from that authoritative source row.

No GoF pattern is introduced: this is a single synchronous use case using the
existing application/port/SQL-adapter split. A command/worker is unnecessary
because creating Console metadata has no asynchronous external side effect.

## Risk-to-test matrix (written before implementation)

| ID | Risk / source | Layer | Action | Required assertion |
| --- | --- | --- | --- | --- |
| RB-01 P0 | Admin-only command; F6 operation security contract | ASGI HTTP | Submit as anonymous, `view`, and `admin` | Anonymous/view rejected; no persistence call for rejected identities |
| RB-02 P0 | CSRF/Origin; browser write policy | ASGI HTTP | Omit/alter CSRF token or send untrusted Origin | Rejected before authority mutation |
| RB-03 P0 | Exact registered-source identity and revision; B0.1 design | SQL integration | Create against missing source, mismatched provider, then stale revision | No binding/target/audit mutation; stable conflict or validation response |
| RB-04 P0 | Atomic metadata + target + audit | SQL integration | Create valid Nacos and Consul targets; inject audit/persistence failure | Success has all rows; failure leaves none |
| RB-05 P1 | Idempotent retry and key misuse | SQL + ASGI | Repeat same key/payload, then same key with different payload/actor/session | Same safe result and one binding/audit; changed payload or owner is conflict/forbidden |
| RB-06 P0 | Binding uniqueness and target location safety | Domain + SQL | Duplicate scope/kind, malformed target, credential-bearing location | Conflict/fail-closed; no credential or rule content stored in binding metadata |
| RB-07 P1 | Browser contract | React focused tests | Use the same POST through MSW and live HTTP gateway | Typed request/response and stable conflict/validation mapping; no direct fixture result path |
| RB-08 P0 | Concurrent idempotent replay across independent SQL stores | PostgreSQL + MySQL integration | Hold the shared authenticated-session row, launch two independent stores with the same command/key, then release the lock | Both callers recover the same binding; exactly one binding, target, receipt, and audit persist |

## Evidence boundary

Use temporary SQLite/ASGI for this focused slice only. These tests do not prove
PostgreSQL/MySQL migration behavior, production deployment assembly, browser
rendering, or Nacos/Consul connectivity. Those remain explicit later gates; the
complete Dashboard E2E is reserved for the final implementation milestone.

## Implementation status

The server application/SQL slice defines `POST /api/v1/rulesets` with a
strict provider target body, admin session + Origin/CSRF verification,
`Idempotency-Key` equality, current-role/session revalidation inside the SQL
transaction, source provider/revision matching, and atomic metadata/target/
receipt/audit persistence. Same key + same actor/session + same payload recovers
the original binding; changed payload/owner is rejected. Rule content is never
accepted by this endpoint. The React feature now has a consumer-owned
registration command type and `RuleSetPort.registerBinding()`; its HTTP adapter
enforces the strict body/201 response identity, CSRF and idempotency key. The
OpenAPI operation is synchronized as `createRuleBinding`, with admin +
`rules:write` authorization and endpoint-specific error codes. The audit action
has English/Japanese/Chinese labels.
The React rules feature also has an admin-only registration dialog backed by
the source-catalog read port and the same `RuleSetPort.registerBinding()`
command used by live mode. The form uses the registered source identity and
revision, exposes provider-specific Nacos/Consul target fields, and only creates
binding metadata; it does not write rule content.

Focused validation from `components/sentinel/sentinel-console`:

```sh
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_rule_binding_registration_store.py \
  tests/test_rule_bindings_api.py \
  tests/test_rule_binding_directory_reader.py
```

Result: **21 passed**. This includes SQLite migration-driven atomicity, retry,
scope/source/provider conflicts, in-transaction admin/CSRF authority checks,
Consul and Nacos target forms, HTTP admin/view/Origin/CSRF/body validation and
directory regression. `compileall` passed for Console source.

React validation from `components/sentinel/dashboard-prototype`:

```sh
npm run check:fast
npm run test:http:focused -- 'RULE-BINDING|CONSOLE-MACHINE'
npm run i18n:check
```

After UI and mock completion, `npm run check:fast`, `npm run i18n:check`, and
`npm run test:http:focused -- 'RULE-BINDING-REGISTRATION-MOCK|RULE-BINDING|CONSOLE-MACHINE'`
passed. The focused HTTP run has **11 passed**, including a shared-source mock
flow: register a source through the system HTTP port, create a binding through
the rule HTTP port, safely replay the identical request, and read back the
binding, empty snapshot, and exact publication target. Reusing the request key
with changed data is rejected. Python route/OpenAPI parity combined with the
registration/directory suites previously passed **45 tests**.

Still open: no mounted UI/browser test has been run (reserved for final E2E),
and this focused HTTP test does not prove deployed React→Python runtime wiring.
PostgreSQL/MySQL registration migration and concurrent retries are now covered
by the RB-08 opt-in acceptance helper. It holds one synthetic administrator
session row, confirms both independent SQL store instances have entered the
locking authorization query, then releases the lock. PostgreSQL 16 passed **6/6**
acceptance tests; MySQL 8.4 passed **7/7** against fresh, disposable databases.
The separate SQLite registration-store suite passed **7/7**, and the post-change
focused SQLite plus both-dialect concurrency selection passed **9/9**. No
production SQL code change was needed: the existing in-transaction account and
session `FOR UPDATE` authority serializes same-session retries before receipt
lookup, after which the second transaction recovers the committed receipt. The
acceptance databases were created only for this run, had no persistent volumes,
used loopback-only random ports, and were removed after verification.

Still open: no mounted UI/browser test has been run (reserved for final E2E),
and these acceptance tests do not prove deployed React→Python runtime wiring.
No real Nacos/Consul call was made. This record does not close B0.1 or F6/F7.
