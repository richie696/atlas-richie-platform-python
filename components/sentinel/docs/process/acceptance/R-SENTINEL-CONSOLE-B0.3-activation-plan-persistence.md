# B0.3 — Activation plan SQL persistence

Status: **scheduled activation/restoration now enqueue and reconcile through the durable publish outbox; SQL receipt storage/query exists; Consul SQL-outbox provider acceptance now passes on PostgreSQL and MySQL (see `R-SENTINEL-CONSOLE-B0.3-real-consul-sql-dialects.md`); Reporter ingress, authoritative inventory, Nacos acceptance, and full B0.3 remain open**.

## Implemented

- Alembic migration `0009_rule_activation_plans` adds a binding-scoped plan table,
  immutable target/restoration version references, explicit UTC window, IANA
  timezone, finite scheduler state and creator audit identity.
- `SqlAlchemyRuleMutationStore` supports `create_plan` and `cancel_plan`:
  - both immutable versions must exist and belong to the exact binding;
  - identical target/restoration versions are rejected;
  - overlapping windows against pending/activating/active/restoring plans are
    rejected;
  - cancellation requires the current plan revision and either `pending` or
    `blocked` state, and advances the revision;
  - plan mutation, original idempotency receipt and audit fact commit in the
    same SQL transaction.
- Plan read is backed by `SqlAlchemyRuleActivationPlanReader` and is included in
  `build_sql_identity_app` composition.
- The create check locks the existing binding's immutable version rows so two
  plan commands for that binding share a database serialization point. This
  still requires real PostgreSQL/MySQL multi-connection verification.
- Alembic migration `0016_rule_activation_plan_leases` persists claim token,
  lease expiry, and bounded non-negative attempt count. The new
  `RuleActivationPlanWorkQueue` Port and SQL adapter atomically claim due
  activation/restoration phases, transition `pending` → `activating` and
  `active` → `restoring`, reclaim expired in-flight claims with a fresh token,
  and renew only the exact still-live `(plan, revision, state, token)` claim.
  It also associates one same-binding publication idempotently, blocks the
  current claim, and completes a phase only when the linked publication's
  validation, provider write, and exact read-back are all durably `succeeded`.
  The adapter uses row locking with `skip_locked` where supported; it does not
  create a process-local timer or publish provider data itself.

## Focused evidence

Command:

```text
PYTHONPATH=components/sentinel/sentinel-console/src \
  components/sentinel/sentinel-console/.venv/bin/pytest -q \
  components/sentinel/sentinel-console/tests/test_rule_mutation_store.py \
  -k 'activation_plan_work_queue or activation_plan_create_overlap'
4 passed
```

The combined suites cover missing-version and invalid-timezone rejection,
successful creation, exact idempotent replay, overlapping-window conflict, SQL
plan read, revision-changing cancellation from `pending` and `blocked`, and
stale-revision conflicts for both states. Test setup runs the Alembic chain
through migration `0016` on isolated in-memory SQLite. The selected cases cover
phase claiming, duplicate-claim exclusion on one SQLite connection, lease
renewal, expired-lease recovery, stale-token rejection, restoration claiming,
rejection of incomplete publication read-back, verified activation/restoration
completion, claim blocking, and the existing plan create/overlap/cancel
behavior. Targeted `compileall` and `git diff --check` passed. This is not a
multi-process or multi-database claim race proof. At the time of that earlier
slice, activation-plan HTTP contract tests had not yet been rerun.

## Scheduler orchestration evidence (2026-10-09)

From `components/sentinel/sentinel-console`:

```text
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_run_rule_activation_plan_worker.py \
  tests/test_rule_activation_plan_worker_lifecycle.py \
  tests/test_rule_publication_worker_lifecycle.py \
  tests/test_first_run_composition.py \
  tests/test_rule_mutation_store.py \
  tests/test_rule_activation_plans_api.py
# 43 passed
PYTHONPATH=src .venv/bin/python -m compileall -q src/atlas_richie/sentinel_console
git diff --check
```

The SQLite execution path verifies activation and restoration operation creation,
stable plan/phase replay after lease recovery, system actor/audit correlation,
and plan transitions only after all three durable publication stages report
success. Provider stages are controlled SQL facts in this orchestration test;
the test does not call Nacos or Consul. Lifecycle tests verify explicit app
injection and task cancellation on shutdown. PostgreSQL/MySQL concurrency and
  real Nacos acceptance and broader recovery acceptance remain open; Consul's
  SQL-outbox provider acceptance now has a separate PostgreSQL/MySQL proof.

## Not proven / remaining

- `RunRuleActivationPlanWorker` claims due phases, renews each claim immediately before processing (so a claim waiting behind earlier batch items is re-fenced), creates a deterministic plan/phase request and publication identity, and writes the existing publish operation/outbox plus the system audit event. The same SQL transaction rechecks the live plan revision/state/token/lease. User-facing operation reads remain session-bound; scheduled operations have no actor/session and are linked by the constrained origin columns.
- Reclaiming an expired activation claim reuses the same operation/publication and does not add another audit or publication record. Restoration selects the explicit restore version and uses the activated version as its expected CAS baseline.
- An isolated-SQLite orchestration test advances both phases only after all three publication facts are durably marked `succeeded`, including exact read-back; the plan remains `activating` while publication work is pending. This test simulates successful provider receipts at the durable outbox boundary. It is not evidence that Nacos/Consul accepted or returned a real write.
- `build_app`, identity composition, and first-run composition now accept the scheduler explicitly; its ASGI lifecycle starts/stops the task and logs only finite exception type. This does not automatically instantiate provider credentials, targets, or workers. Deployment must explicitly assemble and inject both the schedule worker and a compatible publish worker (which may be separately hosted against the same SQL authority).
- The original PLAN-EXEC-01–10 matrix remains only partially covered: PLAN-EXEC-01/08 now have independent PostgreSQL/MySQL connection-pool claim/lease evidence (details below); PLAN-EXEC-04/06 have SQLite end-to-end SQL-workflow evidence with controlled provider conflicts, and PLAN-EXEC-06 additionally proves persisted blocking excludes restoration claims on PostgreSQL/MySQL (details in the checklist). Scheduler loser side effects, real provider CAS/unknown outcomes, a second external-write race between restoration read and CAS, cancellation races, and multiple ASGI workers still require dedicated tests/acceptance.
- SQLite ignores row-level `FOR UPDATE`; it cannot prove supported PostgreSQL/MySQL row-locking, unique-origin races, or deployment restart behavior. The focused Consul SQL-outbox acceptance now proves that one real provider publication path on both production SQL dialects; it does not prove plan recovery against a real provider. Nacos, browser, and full E2E acceptance remain open. Full E2E remains the final acceptance milestone.

## Execution acceptance matrix (remaining B0.3 gate)

The scheduler must reuse the existing publication outbox/CAS/read-back path.
It must not publish from an in-memory timer or treat provider write acceptance as
activation. The implementation is not ready to claim B0.3 until these cases are
covered:

| ID | Risk / trigger | Required assertion | Current evidence |
| --- | --- | --- | --- |
| PLAN-EXEC-01 (P0) | Two independent workers claim one due plan | Exactly one current fenced claim; the losing worker emits no publish command. | **Verified on real PostgreSQL/MySQL 2026-10-10:** independent queue pools first prove one current fenced claim; then two `RunRuleActivationPlanWorker` instances race a second due plan while the winner is gated inside the publication port. The loser returns no outcome and emits no command; the winner creates exactly one real SQL operation/publication and associates it with the plan. PostgreSQL 16 and MySQL 8.4.11 each pass the acceptance. This uses independent database pools in one process, not separate OS processes. |
| PLAN-EXEC-02 (P0) | Worker exits after enqueueing activation but before recording its publication link; outbox finishes before plan recovery | Recovery reuses one deterministic phase key/publication and advances only after the persisted publication is fully verified; no duplicate operation/publication/phase audit. | **Partial, stronger SQLite evidence:** `test_activation_recovers_completed_publication_after_lost_plan_association` now leaves the durable plan unassociated, completes the SQL outbox facts, then constructs a new scheduler after claim expiry. It verifies one operation, publication, accepted audit, and completed audit, and the plan links that same publication. This simulates loss of worker memory, not an OS process crash or real provider write. |
| PLAN-EXEC-03 (P0) | Activation write/read-back is awaiting or unknown | Plan remains non-active and is reconciled from the same publication; it is never blindly republished. | **Partial, full SQLite SQL path now covers provider-unknown recovery:** a controlled provider applies the candidate then raises outcome-unknown; publication persists `unknown`, plan remains `activating`, lease recovery reuses the same publication, provider read confirms the candidate without a second write, and scheduler advances the plan only after read-back completes (checklist §15.466). This does not prove behavior against real Nacos/Consul transport or process kill/restart. |
| PLAN-EXEC-04 (P0) | Provider baseline changes between plan creation/read and CAS | CAS conflict becomes `blocked`; external configuration is not overwritten and restore is not attempted. | **Partial:** SQLite full SQL plan/outbox/publication-worker path with controlled read/CAS race verifies external bytes remain unchanged, publication rejection and blocked-plan/no-restoration operation (checklist §15.462). PostgreSQL/MySQL independently verifies persisted claim recovery, `block_claim`, lease clearing and no subsequent restoration claim (checklist §15.464). A separate real Consul SQL-outbox success path now passes on PostgreSQL/MySQL (§15.485); real provider CAS-conflict during scheduled activation/restoration and Nacos remain open. |
| PLAN-EXEC-05 (P0) | Activation succeeds, then deactivation time arrives | Explicit immutable restore version is enqueued once against the observed activated content; plan completes only after exact read-back succeeds. | **Partial:** SQL orchestration verifies explicit restore target/baseline and completed state after successful read-back facts; no real provider application. |
| PLAN-EXEC-06 (P0) | External actor changes configuration after activation but before restoration | Restore baseline/CAS conflict blocks the plan; the worker does not overwrite the external change. | **Partial:** SQLite SQL plan/outbox/publication-worker test verifies an external pre-read change causes preflight rejection and zero writes after a persisted activation (checklist §15.463); PostgreSQL/MySQL queue acceptance verifies a blocked plan has no live lease and neither independent scheduler can claim it in the later restoration window (checklist §15.464). This does not simulate a true external write racing between restoration read and provider CAS, nor real provider writes. |
| PLAN-EXEC-07 (P1) | Cancellation races with activation claim | Exactly one transition wins; accepted/started publication is never presented as if it had not run. | **Verified on real PostgreSQL/MySQL:** both controlled interleavings are tested. Claim-wins: cancellation pauses between its read transactions, queue claims, cancellation conflicts, then the pending publication is durably associated and the plan remains `activating`. Cancellation-wins: hold the due plan row while the in-flight cancel waits, verify `SKIP LOCKED` scheduler returns no claim, release the row, then cancellation commits and a later claim still returns empty (checklist §15.465). Neither outcome allows a started claim to appear cancelled or a committed cancellation to activate. |
| PLAN-EXEC-08 (P1) | Lease expires and another worker takes over | Stale claim token cannot advance plan/publication state; stable phase key preserves idempotency. | **Partial:** PostgreSQL 16/MySQL 8.4.11 queue tests prove unique attempt-2 takeover, new token, stale-token renewal rejection, and millisecond lease persistence. The SQLite SQL publication outbox test now proves exact same-phase replay is idempotent while the claim remains current, and that after takeover the old token cannot advance the phase (§15.472). Independent OS-process takeover and cross-process publication execution remain open. |
| PLAN-EXEC-09 (P1) | Scheduled execution creates audit/publication facts | Audit identifies both the plan initiator and system execution without inventing a browser session or exposing credentials/rule bodies. | **Partial:** SQLite verifies null actor/session, phase action, plan target, and one audit on replay; production audit-query end-to-end pending. |
| PLAN-EXEC-10 (P1) | Multiple ASGI workers restart/poll together | Persisted claims and phase facts recover across process restart; no process-local election or timer is required. | **Partial, expanded 2026-10-10:** isolated PostgreSQL 16 and MySQL 8.4.11 acceptance starts two real `build_app` lifespans in separate spawned processes, gates both until active, then releases them to poll one due plan. Exactly one reaches SQL publication enqueue; one operation/publication is associated with one attempt. The existing spawned-process lease-expiry recovery also passes. Process termination during provider side effect and real provider phase recovery remain open. |

### ASGI lifespan concurrency test design

- Start two spawned child processes; each constructs its own SQLAlchemy engine,
  publication command store, scheduled worker, and real `build_app` ASGI lifespan.
- Hold both workers immediately before `claim_due()` until both lifespans report
  started, then release one shared process-safe gate. This proves the race is
  between two active ASGI lifecycle tasks, not merely two queue objects.
- Seed one due synthetic plan and assert exactly one child reaches the existing
  SQL scheduled-publication command; after both processes stop, assert one
  claim attempt, one operation/publication, and the same publication associated
  with the plan.
- Use only the existing isolated PostgreSQL/MySQL acceptance databases and
  UUID-scoped rows; the test publication stops at the durable outbox boundary
  and must not contact Nacos/Consul. Full provider/React E2E remains separate.

### Spawned-process lease recovery (2026-10-10)

The provider-independent queue acceptance now includes an OS-process boundary in
addition to the existing independent-pool race. Each child uses Python's
`spawn` context and creates its SQLAlchemy async engine inside the child, so no
parent connection pool is inherited. The first process claims a due activation
and exits; two newly spawned processes then race after the persisted lease
expires. The result must contain exactly one attempt-2 claim with a different
claim token. Unrelated due plans fail the test, and child errors/timeouts are
reported to the parent rather than treated as an empty claim.

This check was run against isolated disposable databases only:

```text
SENTINEL_CONSOLE_TEST_POSTGRES_URL=postgresql+psycopg://.../sentinel_console_test_plan_process \
  PYTHONPATH=src .venv/bin/pytest -q tests/test_postgresql_acceptance.py \
  -k independent_activation_plan_workers_fence_and_recover
# 1 passed, 7 deselected (PostgreSQL 16)

SENTINEL_CONSOLE_TEST_MYSQL_URL=mysql+asyncmy://.../sentinel_console_test_plan_process \
  PYTHONPATH=src .venv/bin/pytest -q tests/test_mysql_migration_acceptance.py \
  -k independent_activation_plan_workers_fence_and_recover
# 1 passed, 8 deselected (MySQL 8.4.11)
```

The temporary database containers were stopped after the checks. This proves
persisted queue claim recovery across spawned processes, not process termination
during a provider side effect or full provider phase recovery across OS
processes. PLAN-EXEC-10 remains partial and B0.3 remains open.

### Two active ASGI lifespans (2026-10-10)

The acceptance helper now starts two spawned child processes. Each process
creates its own SQLAlchemy engine, publication command store, scheduled worker,
and actual `build_app` lifespan. A process-safe barrier holds both workers before
the first SQL claim until the parent has observed both lifespans started. After
release, both poll the same due plan against PostgreSQL/MySQL. The test requires
exactly one scheduled publication enqueue, one durable operation/publication,
one persisted claim attempt, and that exact publication ID associated with the
plan before either app is shut down. This verifies active ASGI lifecycle
competition rather than only separately constructed queues. The controlled
publication ends at the existing durable outbox boundary and makes no Nacos or
Consul request.

Commands and results:

```text
SENTINEL_CONSOLE_TEST_POSTGRES_URL=postgresql+psycopg://.../sentinel_console_test_asgi \
  PYTHONPATH=src .venv/bin/pytest -q tests/test_postgresql_acceptance.py \
  -k independent_activation_plan_workers_fence_and_recover
# 1 passed, 8 deselected (PostgreSQL 16)

SENTINEL_CONSOLE_TEST_MYSQL_URL=mysql+asyncmy://.../sentinel_console_test_asgi \
  PYTHONPATH=src .venv/bin/pytest -q tests/test_mysql_migration_acceptance.py \
  -k independent_activation_plan_workers_fence_and_recover
# 1 passed, 9 deselected (MySQL 8.4.11)
```

Both tests used newly created loopback-only disposable containers, stopped after
the run. Existing databases and configuration centers were not used. The test
does not kill a process mid-provider effect and is not real-provider or full
Dashboard E2E evidence.

### Narrow recovery test (implemented)

An isolated-SQLite fault-window test for PLAN-EXEC-02 persists the scheduled
publication, completes its validation/write/read-back facts through the
existing outbox, then simulates process loss before the activation plan records its
publication link. After the plan lease expires, a newly constructed scheduler
must recover the same deterministic operation/publication, link it, and advance
the plan without adding a second publication or scheduled audit. This proves
the SQL recovery path across a lost in-memory worker, not an OS-process crash,
provider behavior, or multi-database locking.

Command and result:

```text
.venv/bin/pytest -q tests/test_rule_mutation_store.py tests/test_run_rule_activation_plan_worker.py
# 30 passed
.venv/bin/python -m compileall -q src/atlas_richie/sentinel_console
```

The full two-module run passed after the focused fault-window test. Its outbox
phase success values are controlled SQL facts; no provider network call occurs.
The changed Python and Markdown files also had a targeted trailing-whitespace
scan with no matches.

## Execution identity decision

Scheduled publication reuses the existing durable publish operation/outbox and
provider worker, but records its origin as the exact `origin_plan_id` plus the
finite `origin_phase` (`activation` or `restoration`). The scheduled operation
has no account actor and no session hash; it must never synthesize or retain a
browser session. The database constraint permits a sessionless publish only
when it is linked to a persisted plan and one of those phases. A unique
plan/phase key makes enqueue recovery converge on the same operation.

The plan's immutable `created_by_account_id` remains the human initiator. The
plan-creation audit event records that admin; scheduled completion/rejection
uses a null account actor, a phase-specific system action, and the same plan as
its audit target. These records correlate by `plan_id`, so initiator and
executor are distinct without a synthetic identity. User operation lookup
remains actor/session-bound and cannot read system work. This extends the
existing persisted command and finite-state contracts; it does not add a new
GoF pattern or a second provider execution path.

Migration `0017_scheduled_rule_publication_origin` and its SQLite tests establish
the sessionless-origin constraint. The current scheduler enqueues the
operation/outbox and audit transactionally and reconciles by deterministic
plan/phase identity after claim recovery. The full execution matrix below is
still open.

The system-audit projection now recognizes scheduled activation and restoration
as finite `plan-activate` / `plan-restore` actions mapped to the persisted
`rules.activation_plan.activate` / `rules.activation_plan.restore` facts. These
actions may have a null account actor; user-originated audit actions still
require an account actor. The API and UI render the executor as the localized
system actor, while the original plan-creation audit retains the initiating
admin. The scheduler now emits these phase audit rows transactionally;
API/UI and query-level lifecycle verification remains incomplete.

## Real-dialect claim race and MySQL lease precision (2026-10-10)

### Test design

- **PLAN-EXEC-01:** seed one due synthetic plan in a dedicated test database;
  call `claim_due()` concurrently through two separately constructed queue
  instances and two independent SQLAlchemy connection pools; assert exactly one
  current owner and persisted attempt count 1.
- **PLAN-EXEC-08:** move the test clock beyond the persisted lease; race both
  queues again; assert exactly one attempt-2 owner with a new token, stale-token
  renewal is rejected, and persisted expiry retains its millisecond value.
- Fixture IDs, account, validation receipts, and versions are UUID-scoped and
  removed in `finally`. Only newly created loopback-only disposable databases
  were used. No pre-existing database or configuration center was contacted.

### Defect found and correction

The first MySQL run failed because MySQL's default `DATETIME` has zero fractional
digits: a lease ending at `.001` was stored at the preceding whole second. The
test was deliberately kept at millisecond precision rather than weakened.
Migration `0020_millisecond_worker_leases` changes both durable worker lease
columns (`console_rule_operation.work_lease_expires_at` and
`console_rule_activation_plan.claim_lease_expires_at`) to MySQL `DATETIME(3)`;
the SQLAlchemy model uses the same MySQL type variant. PostgreSQL retains its
native timestamp precision. Downgrade refuses while either lease owner is
active, preventing an in-flight lease from losing precision.

### Verification

- Disposable PostgreSQL 16 acceptance: `tests/test_postgresql_acceptance.py`
  **7 passed**.
- Disposable MySQL 8.4 acceptance: `tests/test_mysql_migration_acceptance.py`
  **8 passed**, including `information_schema.datetime_precision == 3` for
  both worker lease columns and the exact-millisecond claim recovery assertion.
- SQLite SQL mutation/scheduler/provider worker regression:
  **38 passed**.
- `compileall` and `git diff --check` passed. Ruff was unavailable in the
  component virtual environment.
- One repeat of the PostgreSQL suite against the already-used disposable DB
  failed five existing “must be uninitialized” preconditions because an earlier
  successful first-run test had intentionally initialized it. Re-running the
  complete suite once against a fresh, separately named disposable DB passed
  **7/7**. Both test containers were stopped and auto-removed afterward.

### Remaining boundary

This proves row-lock/lease queue behavior across two independent connection
pools in each supported SQL dialect, not separate OS processes or multiple
ASGI deployments. It does not prove the losing scheduler emits no command,
provider unknown-outcome recovery, a real provider CAS race, or runtime instance
receipts. PLAN-EXEC-01 is verified at the database/scheduler boundary but still lacks separate OS-process evidence; PLAN-EXEC-08 remains partial/open; B0.3 remains open; final frontend E2E remains
deferred until all implementation items are complete.

## Cancellation versus activation claim (2026-10-10)

### Test design

- **PLAN-EXEC-07:** use a migrated disposable database with one synthetic admin,
  session, due activation plan, two immutable versions, and validation receipts.
  Start the real `SqlAlchemyRuleMutationStore.mutate(CancelRuleActivationPlan)`
  command and gate its binding read, which occurs after its first authorization /
  idempotency transaction but before the final plan-state transaction.
- While the command is in flight, an independently pooled
  `SqlAlchemyRuleActivationPlanWorkQueue` claims the due plan. Resume cancellation
  and require it to reject the stale expected revision with `conflict`.
- Continue the winning claim through the real SQL scheduled-publication enqueue
  and plan/publication association window. Require one pending publication, an
  `activating` plan with that publication identity and current claim token, and
  a persisted rejected cancellation receipt. This proves an already-started
  phase is not represented as cancelled.
- Also exercise the cancellation-wins ordering with a second due plan: hold its
  row in an independent transaction, let cancellation reach its final plan
  transaction, and run the scheduler while the row remains locked. The queue
  must skip the locked row; after releasing the lock, cancellation commits and
  later scheduler queries remain empty.
- All identifiers are unique synthetic values and cleanup deletes only rows
  belonging to this acceptance run.

### Verification

- Disposable PostgreSQL 16: focused `test_cancel_racing_activation_claim_preserves_started_publication` **1 passed**.
- Disposable MySQL 8.4.11: same focused acceptance **1 passed**.
- The existing SQLite activation-plan command/scheduler selection: **5 passed**.
- Python `compileall` and `git diff --check` passed. No production implementation
  changed; no real database, Nacos/Consul deployment, browser, or full E2E was used.

### Remaining boundary

These controlled interleavings prove both claim-wins and cancellation-wins
database outcomes on both supported SQL dialects. They do not cover an OS
process crash after claim, real provider effects, or multiple ASGI deployments;
those remain separate B0.3 acceptance requirements.
