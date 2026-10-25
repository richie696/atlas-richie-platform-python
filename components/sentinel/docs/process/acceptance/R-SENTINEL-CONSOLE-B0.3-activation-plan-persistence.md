# B0.3 — Activation plan SQL persistence

Status: **scheduled activation/restoration now enqueue and reconcile through the durable publish outbox; SQL receipt storage/query exists; direct Consul publication and scheduled Consul activation/restoration pass on PostgreSQL and MySQL (see `R-SENTINEL-CONSOLE-B0.3-real-consul-sql-dialects.md`); Reporter ingress, authoritative inventory, deeper provider-failure recovery, and full B0.3 remain open**.

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
- The original PLAN-EXEC-01–10 matrix remains only partially covered: PLAN-EXEC-01/08 have independent PostgreSQL/MySQL claim/lease evidence; PLAN-EXEC-04 covers real Nacos conflicts after scheduled activation and restoration preflight (§15.525–§15.526), plus the real Consul activation CAS conflict in §15.570; PLAN-EXEC-06 has SQLite workflow evidence, PostgreSQL/MySQL persisted blocking, and real Nacos + Consul scheduled-restoration preflight acceptance on PostgreSQL/MySQL (§15.1062–§15.1063). Scheduler loser side effects, provider RPC in-flight process loss/unknown transport outcome, production auth/TLS and multi-cluster consistency remain separate acceptance boundaries. See the individual matrix rows below for exact scope.
- SQLite ignores row-level `FOR UPDATE`; it cannot prove supported PostgreSQL/MySQL row-locking, unique-origin races, or deployment restart behavior. The focused Consul SQL-outbox and scheduled activation/restoration acceptances prove real provider paths on both production SQL dialects, including controlled post-write unknown-ack recovery and the committed-write/response-drop/process-termination window (§15.717, §15.948); they do not prove an unknown Consul server commit or failure before the proxy receives the response. Nacos, browser, and full E2E acceptance remain separate. Full E2E remains the final acceptance milestone.

### Runtime receipt authenticated SQL → ASGI GET composition (2026-10-13)

The PostgreSQL/MySQL receipt acceptance now continues beyond direct store invocation. It creates a synthetic account/session plus publication/version facts, records and advances one receipt in the production SQL store, assembles the standard `build_sql_identity_app` (including the production SQL current-session, publication-detail, and receipt readers), then queries the protected receipt GET through `ASGITransport`. It asserts exact binding/publication/instance/version/checksum projection, page counters, `Cache-Control: no-store`, `Vary: Cookie`, and anonymous-session rejection.

- PostgreSQL 16: `tools/with_disposable_postgresql_acceptance.sh uv run --no-sync --extra test --extra postgres pytest -q --tb=short tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_rule_publication_receipt_store_round_trip` — **1 passed**.
- MySQL 8.4.11: `tools/with_disposable_e2e_dependencies.sh uv run --no-sync --extra test --extra mysql pytest -q --tb=short tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_rule_publication_receipt_store_round_trip` — **1 passed**.
- Both runners completed cleanup; a post-run container query found no `sentinel-e2e-mysql-*`, `sentinel-e2e-consul-*`, or Nacos acceptance leftovers.

This closes only the database-store → standard Console composition → authenticated read-route slice. It does **not** create a Reporter/Collector writer or prove how a runtime agent is identified and correlated to one immutable publication; the explicit correlation-contract blocker in tracker §15.1072 and the draft in [`../../protocol/RULE_PUBLICATION_RECEIPT_PROJECTION_DECISION.md`](../../protocol/RULE_PUBLICATION_RECEIPT_PROJECTION_DECISION.md) remain. B0.3 and final browser E2E remain open.

### Viewer-role receipt read authorization (2026-10-13)

The same PostgreSQL/MySQL SQL → standard `build_sql_identity_app` → protected ASGI receipt GET acceptance now authenticates as an active `view` account instead of `admin`. Both SQL dialects still return the exact persisted publication/instance/version projection and no-store headers, while clearing the session cookie still yields `401 unauthenticated`. This proves the read-only receipt endpoint works for the Dashboard viewer role without weakening the anonymous boundary; it does not authorize receipt writes or close the Reporter identity/publication correlation blocker.

- PostgreSQL 16: `tools/with_disposable_postgresql_acceptance.sh uv run --no-sync --extra test --extra postgres pytest -q --tb=short tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_rule_publication_receipt_store_round_trip` — **1 passed**.
- MySQL 8.4.11: `tools/with_disposable_e2e_dependencies.sh uv run --no-sync --extra test --extra mysql pytest -q --tb=short tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_rule_publication_receipt_store_round_trip` — **1 passed**.
- Ruff check/format, Python compileall, and `git diff --check` passed; disposable MySQL/Consul containers were removed by the owner runner and no matching containers remained.

## Execution acceptance matrix (remaining B0.3 gate)

The scheduler must reuse the existing publication outbox/CAS/read-back path.
It must not publish from an in-memory timer or treat provider write acceptance as
activation. The implementation is not ready to claim B0.3 until these cases are
covered:

| ID | Risk / trigger | Required assertion | Current evidence |
| --- | --- | --- | --- |
| PLAN-EXEC-01 (P0) | Two independent workers claim one due plan | Exactly one current fenced claim; the losing worker emits no publish command. | **Verified on real PostgreSQL/MySQL (2026-10-10, §15.467/§15.481):** independent queue pools prove one current fenced claim; two scheduler workers racing behind a gated publication port prove the loser emits no command; and §15.481 starts two separate spawned processes, each with its own SQL engine and real `build_app` ASGI lifespan, then releases both schedulers against the same due plan and asserts exactly one outbox enqueue/operation/publication and winner association. PostgreSQL 16 and MySQL 8.4.11 pass. This closes the two-worker scheduler race, not provider-side-effect crash recovery or the remaining PLAN-EXEC/B0.3 cases. |
| PLAN-EXEC-02 (P0) | Worker exits after enqueueing activation but before recording its publication link; outbox finishes before plan recovery | Recovery reuses one deterministic phase key/publication and advances only after the persisted publication is fully verified; no duplicate operation/publication/phase audit. | **Verified for SQL recovery and real Consul/Nacos provider paths on PostgreSQL 16 and MySQL 8.4.11 (2026-10-13, §15.1042/§15.1058/§15.1060):** §15.1042 proves spawned-process loss and deterministic SQL recovery; §15.1058 pauses the production scheduler before association, completes a real ACL/TLS Consul CAS plus exact read-back, kills the scheduler, then proves a fresh lease owner links the same publication without another provider CAS; §15.1060 verifies the equivalent Nacos path. In each provider case the persisted operation/publication and accepted/completed phase audits remain unique. The in-flight provider boundary is covered for these two providers only; runtime instance receipt, deployment topology, and remaining B0.3 cases remain separate. |
| PLAN-EXEC-03 (P0) | Activation write/read-back is awaiting or unknown | Plan remains non-active and is reconciled from the same publication; replay is allowed only after an authoritative unchanged-baseline read and remains fenced by provider CAS. | **Partial, real Nacos plus Consul recovery:** §15.522 covers a spawned scheduled worker exiting after Nacos returns success but before the SQL receipt (PostgreSQL/MySQL + Nacos 3.2.4). §15.523 applies the real Nacos write, then injects `RulePublicationProviderOutcomeUnknown` at the provider Port; the SQL outbox persists `unknown`, and a new worker exact-reads the candidate with zero additional writes (PostgreSQL 16 + Nacos 3.2.4). §15.551 executes the create-only HTTP client-ack loss seam (PostgreSQL 16/MySQL 8.4.11 + Nacos 3.2.4): the real Admin Import succeeds, its response is discarded before the writer observes it, SQL persists `unknown`, and recovery exact-reads with no second Import. §15.553 applies the scheduled activation gRPC CAS to Nacos, discards the successful response before the writer observes it, and proves SQL `unknown` → exact read-only recovery → active plan only after confirmed read-back (PostgreSQL/MySQL + Nacos 3.2.4). §15.574 additionally kills a spawned scheduled Consul publication worker after real CAS/read-back and before SQL receipt; PostgreSQL/MySQL recovery exact-reads without another provider write, then restores the explicit baseline. §15.717 adds TLS response-path loss and spawned-process termination during scheduled activation on MySQL; §15.948 proves the same network-fault window on PostgreSQL 16. Both dialects recover after Consul commits CAS and the proxy drops the caller response, with zero second writes; the scheduled plan advances only after exact read-back and completes restoration. §15.1029 proves the complementary provider boundary: the HTTPS proxy receives one CAS and resets the client connection before forwarding to Consul; the production writer conservatively reports `unknown`, the original exact baseline remains, and no retry occurs. §15.1043 proves a direct SQL outbox can recover this specific Consul liveness gap using a strong `consistent=true` exact read and a CAS against the observed ModifyIndex. §15.1044 extends the same fault to a real scheduled activation: PostgreSQL 16 and MySQL 8.4.11 each preserve the plan as non-active while unknown, then activate only after lease takeover, one recovery CAS and exact read-back. **§15.1046 verifies the competing-writer window after the strong recovery read on PostgreSQL 16 and MySQL 8.4.11: the stale recovery CAS is rejected, the plan is durably blocked, and external Consul bytes are preserved. §15.1059 adds the Nacos complement: after the real activation CAS commits but its gRPC ACK is dropped, a controlled proxy replays one byte-exact, previously observed Nacos baseline on the first recovery GET; publication remains `unknown/awaiting`, the plan stays non-active, and no second write occurs. Once the fault is exhausted, a real exact GET observes the candidate and the same publication completes, followed by plan activation (PostgreSQL 16/MySQL 8.4.11). §15.1064 adds the in-flight process-loss complement: the real Nacos publish commits but the successful gRPC response is held before client delivery; the spawned scheduled worker is terminated with SQL still `running/awaiting`, and the next lease owner confirms the candidate through exact read without a second publish before activating the plan (PostgreSQL 16/MySQL 8.4.11).** Nacos and providers without the explicit strong-read guarantee remain read-only during unknown reconciliation. These local controlled stale-read/response-hold faults are not evidence of native Nacos multi-node consistency. Unknown Consul server commit, failure before the proxy receives the request, provider-specific cluster behavior and deployment auth/TLS remain open. |
| PLAN-EXEC-04 (P0) | Provider baseline changes between plan creation/read and CAS | CAS conflict becomes `blocked`; external configuration is not overwritten and restore is not attempted. | **Partial across real Nacos and Consul:** §15.525/§15.526 race both scheduled phases against Nacos 3.2.4; §15.570/§15.571 race scheduled activation and restoration against disposable ACL-enabled Consul 1.21.1. PostgreSQL 16/MySQL 8.4.11 prove stale CAS rejection, exact external bytes retained, plan persisted `blocked`, and no subsequent phase. §15.719/§15.720 run Consul management writes from spawned OS processes during MySQL-backed scheduled activation and restoration CAS; §15.949 adds both independent-process races on PostgreSQL 16. All four stale CAS attempts are rejected and plans are blocked without overwriting external bytes. Production provider auth/TLS/token lifecycle and multi-cluster behavior remain open. Earlier SQLite/provider evidence is in §15.462/§15.464/§15.485. |
| PLAN-EXEC-05 (P0) | Activation succeeds, then deactivation time arrives | Explicit immutable restore version is enqueued once against the observed activated content; plan completes only after exact read-back succeeds. | **Partial, real Nacos restoration and Consul recursive recovery:** §15.522 verifies normal exact restoration after scheduled activation. §15.524 applies the restoration write to Nacos 3.2.4, injects `RulePublicationProviderOutcomeUnknown` at the provider Port, and verifies the SQL plan remains `restoring`; after lease expiry, the new worker exact-reads the immutable daily version with zero additional writes, and only then can the plan become `completed` (PostgreSQL 16/MySQL 8.4.11). §15.552 additionally applies the real restoration gRPC CAS, discards its successful response at the `NacosGrpcTransport` caller boundary, and verifies unknown persistence followed by read-only exact reconciliation with no second CAS in both SQL dialects. §15.525 verifies a real external Nacos update racing restoration CAS blocks the scheduled plan without overwriting external bytes. **§15.1056 closes the recursive Consul restore-ACK-loss window on PostgreSQL 16 and MySQL 8.4.11:** the recovery CAS commits the immutable baseline but its response is dropped; SQL remains `unknown/awaiting` and the plan `restoring`; a later lease owner performs a `consistent=true` exact read, sends no further CAS, and only then permits `completed`. **§15.1068 adds Nacos's complementary process-loss window:** the scheduled restoration CAS commits the exact baseline, its successful gRPC acknowledgement is held, and the spawned worker is terminated while SQL is `running/awaiting`; on both SQL dialects a new worker confirms the baseline with a read-only exact GET (zero second publish), then the scheduler completes the plan. **§15.1070 verifies Nacos's conservative complement for a publish accepted by the local proxy but never forwarded upstream:** PostgreSQL 16/MySQL 8.4.11 keep the restoration publication `unknown/awaiting` and plan `restoring`; the replacement worker performs reconciliation but never replays CAS or marks completion based on the injected pre-dispatch fault. These deterministic seams do not simulate an unknown server commit or production multi-cluster behavior. Production auth/TLS remains open. |
| PLAN-EXEC-06 (P0) | External configuration changes after activation and before the restoration worker's first read | Restoration preflight detects the changed baseline, issues zero provider writes, preserves external bytes, and durably blocks the plan without creating another restore phase. | **Verified on real Nacos 3.2.4 + PostgreSQL 16/MySQL 8.4.11 (§15.1063) and ACL/TLS Consul + PostgreSQL 16/MySQL 8.4.11 (§15.1062):** each disposable SQL/provider run performs scheduled activation and exact read-back, enqueues restoration, then changes the provider key through its management plane before the restoration worker starts. Both production provider workers reject during preflight; Consul observed CAS count does not increase and Nacos gRPC publish count remains at the successful activation only; external bytes stay exact, SQL records the validation conflict and `blocked` plan, and subsequent polls do not create or replay a phase. Existing SQLite workflow and PG/MySQL blocked-queue evidence remain in §15.463–§15.464. This does not cover a second external write racing after preflight (see PLAN-EXEC-04), production topology/auth lifecycle, or close B0.3. |
| PLAN-EXEC-07 (P1) | Cancellation races with activation claim | Exactly one transition wins; accepted/started publication is never presented as if it had not run. | **Verified on real PostgreSQL/MySQL:** both controlled interleavings are tested. Claim-wins: cancellation pauses between its read transactions, queue claims, cancellation conflicts, then the pending publication is durably associated and the plan remains `activating`. Cancellation-wins: hold the due plan row while the in-flight cancel waits, verify `SKIP LOCKED` scheduler returns no claim, release the row, then cancellation commits and a later claim still returns empty (checklist §15.465). Neither outcome allows a started claim to appear cancelled or a committed cancellation to activate. |
| PLAN-EXEC-08 (P1) | Lease expires and another worker takes over | Stale claim token cannot advance plan/publication state; stable phase key preserves idempotency. | **Verified at SQL/process boundary on PostgreSQL 16 and MySQL 8.4.11 (2026-10-13):** a spawned OS process claims the plan, enqueues one deterministic publication, and commits all three successful stage receipts while leaving the outbox operation pending; it is forcibly terminated before outbox completion and plan association. After expiry, a new outbox owner takes attempt 2; the exact successful read-back receipt replay is accepted for that current owner, while the old publication claim token is rejected by SQL CAS. The new owner completes the same publication; an explicit attempt-1 plan claim is then rejected, and a fresh scheduler takes plan attempt 2, links that publication and activates the plan. Both dialect tests assert one operation/publication/accepted+completed audit and a second scheduler pass is a no-op. Stage receipts are controlled SQL outbox facts, not provider calls; the provider and runtime/instance boundaries remain separate. Earlier same-phase replay and fencing evidence is in §15.472. |
| PLAN-EXEC-09 (P1) | Scheduled execution creates audit/publication facts | Audit identifies both the plan initiator and system execution without inventing a browser session or exposing credentials/rule bodies. | **Partial:** SQLite evidence remains in §15.612. PostgreSQL 16 and MySQL 8.4.11 now verify the real scheduler write through the production SQLAlchemy audit reader and authenticated admin ASGI route: null system actor, no session on scheduled operation, initiating account retained on the plan, phase action, plan target, `requestId`, unknown result, and no rule-version IDs in the response (§15.1028). Browser E2E and the broader schedule/publication failure matrix remain pending. |
| PLAN-EXEC-10 (P1) | Multiple ASGI workers restart/poll together | Persisted claims and phase facts recover across process restart; no process-local election or timer is required. | **Partial, expanded 2026-10-13:** isolated PostgreSQL 16 and MySQL 8.4.11 acceptance starts two real `build_app` lifespans in separate spawned processes, gates both until active, then releases them to poll one due plan. Exactly one reaches SQL publication enqueue; one operation/publication is associated with one attempt. The existing spawned-process lease-expiry recovery also passes. Provider-side-effect termination has real scheduled activation evidence: Consul TLS response-path hold/termination on PostgreSQL/MySQL (§15.717/948) and Nacos successful gRPC response hold/termination on PostgreSQL/MySQL (§15.1064); §15.1066 proves the matching Consul scheduled-restoration path, while §15.1068 now proves Nacos scheduled-restoration ACK-in-flight termination and read-only lease takeover on both SQL dialects. Production deployment and browser journeys remain open. |

**Consul pre-dispatch recovery addendum (2026-10-13):** §15.1044 covers a real scheduled activation whose CAS is received by the HTTPS proxy but dropped before Consul; §15.1045 covers both scheduled activation and scheduled restoration under the same fault. In each phase, the SQL publication remains unknown and the plan does not advance until lease takeover, exact strong-consistency read, one CAS against the observed ModifyIndex, and exact read-back. PostgreSQL 16 and MySQL 8.4.11 both pass. This does not cover a multi-node Consul cluster or an unknown outcome after the Consul server itself commits.

**Consul scheduled restoration process-loss addendum (2026-10-13):** §15.1066 covers the complementary post-commit window for the restoration phase. Consul commits the exact immutable baseline while a spawned scheduled worker's successful response is held; SQL remains `running/awaiting`, the plan remains `restoring`, and the worker is terminated. On lease takeover, the replacement worker proves the baseline with a strong exact read and performs zero additional CAS writes; only after the publication is complete does the scheduler mark the plan `completed`. PostgreSQL 16 and MySQL 8.4.11 pass. This closes only the local Consul scheduled-restoration ACK-in-flight process-loss slice, not PLAN-EXEC-03/05, B0.3, deployment security/multi-node behavior, or final browser-to-Python E2E.

**Consul recursive post-commit ACK-loss addendum (2026-10-13):** §15.1052 covers activation recovery; §15.1056 covers the restoration counterpart. In each case the recovery CAS commits at the real ACL/TLS Consul server but the client response is dropped. The SQL publication remains `unknown/awaiting`, the plan remains in its nonterminal phase, and the next lease owner uses a `consistent=true` exact read to confirm the candidate without another CAS. PostgreSQL 16 and MySQL 8.4.11 both pass. This does not resolve server-side unknown commit, multi-node consistency, production credentials, or deployment topology.

**Nacos pre-dispatch uncertainty addendum (2026-10-13):** §15.1061 exercises the complementary boundary where the gRPC publish reaches the local fault proxy but is rejected before the real Nacos server receives it. The real server remains at the exact baseline, while the worker correctly records the provider result as `unknown` because the client cannot prove how far a production network failure progressed. A later lease owner performs read-only reconciliation; because Nacos does not provide the required strong-read guarantee, it must not retry the CAS from the observed baseline. The publication remains `unknown/awaiting` and the scheduled plan remains `activating`. PostgreSQL 16 and MySQL 8.4.11 both pass. This controlled proxy test does not simulate a Nacos server commit or establish native Nacos cluster consistency.

**Consul rejected-CAS response-loss addendum (2026-10-13):** §15.1065 composes PLAN-EXEC-03/04: an independent management-plane update advances the real Consul key after activation preflight; the stale CAS is rejected by Consul, but the local proxy hides the `false` response so the first worker persists `unknown`. After lease takeover, a `consistent=true` exact read proves the external value is neither baseline nor candidate. The worker now persists `failed/conflict`, the activation plan becomes `blocked`, the external bytes remain unchanged, and no second CAS/restoration phase is created. PostgreSQL 16 and MySQL 8.4.11 pass. Nacos remains conservative because it does not claim the equivalent strong-read contract. This closes only this local conflict-response-loss slice, not PLAN-EXEC-03/04 or full B0.3.

**Consul evidence for PLAN-EXEC-03/05 (2026-10-11):** §15.569 additionally
drives the complete SQL plan → real ACL-enabled Consul activation → exact
read-back → restoration path on PostgreSQL 16 and MySQL 8.4.11. Both activation
and restoration inject controlled acknowledgement loss after the real writer
returns; a fresh worker reconciles each by exact read with zero retry writes.
§15.717 adds real TLS response-path loss and spawned-process termination during
scheduled activation on MySQL 8.4.11; §15.948 adds the same specific fault
window on PostgreSQL 16. On both, the plan recovers only after exact read.
Consul external-writer process concurrency on PostgreSQL, production ACL/TLS,
unknown server commit, pre-proxy failure and multi-node consistency remain open.

**Consul evidence for PLAN-EXEC-04 activation/restoration CAS (2026-10-11):**
§15.570 and §15.571 inject authorized external KV writes after the scheduled
publication worker has read its baseline and immediately before the production
Consul CAS. On PostgreSQL 16 and MySQL 8.4.11, both stale CAS attempts are
rejected, external bytes remain exact, SQL persists each publication as
`failed/conflict` and each plan as `blocked`; the activation conflict creates
no restoration publication and the restoration conflict is not retried. The
Both activation and restoration races now have separate spawned management
writer processes on MySQL (§15.719/§15.720). PostgreSQL independent-process
parity is verified by §15.949: the same real PostgreSQL 16 + ACL-enabled
Consul acceptance runs both races, rejects each stale CAS, preserves external
bytes, and blocks the affected plan. Deployment-level multi-node writer
behavior remains unverified.

**Consul scheduled process-loss evidence (2026-10-11):** §15.574 extends the
same production SQL plan/outbox/worker flow. A spawned worker completes real
Consul activation CAS and exact read-back, then exits at the provider/SQL
boundary before the write receipt is persisted. The plan remains `activating`
and the publication remains `running/awaiting`; after lease expiry, a fresh
worker exact-reads the already committed value, performs zero additional
writes, advances the plan, and later restores the explicit baseline. The
activation-loss/recovery/restoration path passed on PostgreSQL 16 and MySQL
8.4.11. This is process termination after a completed provider request, not an
in-flight RPC termination or packet-loss test.

**Transport-boundary response-loss case (PLAN-EXEC-03/P0):** the disposable
Consul HTTPS test proxy now has an opt-in one-shot barrier for its exact
synthetic KV key. It forwards the request, waits for the upstream KV endpoint
to commit and answer, then withholds and resets the client response socket. A
loopback protocol-compatible endpoint test verifies that the caller remains
blocked after commit, cancellation plus proxy release loses the response, and
an independent GET still observes the one committed value (**1 passed**,
§15.716). Real recovery is exercised on disposable MySQL 8.4.11 and
ACL-enabled Consul 1.21.1 in §15.717 for both direct publication and scheduled
activation: while the production publisher is blocked on the held TLS response,
SQL remains running/pending; the spawned worker is terminated; after lease
expiry a fresh worker exact-reads and completes with zero additional writes.
The scheduled plan remains non-active until this read-back and later completes
its restoration phase. PostgreSQL parity remains open. This is narrower than
final React→Python Dashboard E2E; cleanup owns only generated test rows, proxy
certificate directory, and disposable containers.

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

### Cross-dialect recovery acceptance (2026-10-11)

Run the same deterministic recovery window on isolated PostgreSQL and MySQL:

1. Persist one due plan, then let a spawned worker process claim its activation
   and enqueue the deterministic scheduled operation/publication.
2. Through the real SQL publish outbox, persist validation, provider-write,
   and exact-read-back stages as `succeeded`; this acceptance is about SQL
   recovery and explicitly does not claim a real provider call. The child
   signals only after those transactions commit and while the plan still has no
   publication link; the parent forcibly terminates that process.
3. Confirm the process exited non-zero and the persisted plan remains
   unassociated while the outbox is complete. Construct a fresh plan
   scheduler/store after the plan lease expires; it must link the existing
   publication and complete the activation phase.
4. Assert exactly one scheduled operation, publication, accepted audit, and
   completed audit; assert no duplicate is created and the plan references the
   original publication.

The isolated SQLite test remains the local workflow proof. This increment adds
the same persisted recovery path against disposable PostgreSQL 16 and MySQL
8.4.11 databases and forcibly terminates a spawned worker after the outbox
commit but before association; actual provider acceptance remains in
PLAN-EXEC-03/05. The outbox's successful stage receipts are controlled SQL
facts, not a real provider call.

Commands and results:

```text
SENTINEL_CONSOLE_TEST_POSTGRES_URL=postgresql+psycopg://.../sentinel_console_test_plan_recovery \
  .venv/bin/pytest -q tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_activation_recovers_completed_publication_after_lost_association
# 1 passed (PostgreSQL 16)

SENTINEL_CONSOLE_TEST_MYSQL_URL=mysql+asyncmy://.../sentinel_console_test_plan_recovery \
  .venv/bin/pytest -q tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_activation_recovers_completed_publication_after_lost_association
# 1 passed (MySQL 8.4.11)
```

Both checks used unique loopback-only disposable containers and synthetic
credentials; the containers were removed after each run. No shared database,
Nacos, or Consul was contacted. Targeted Ruff checks and Python compilation
passed. This closes the process-termination recovery window across both SQL
dialects, but PLAN-EXEC-02 and B0.3 remain partial until provider/runtime and
remaining acceptance boundaries are verified.

### Verification refresh — completion before forced process loss (2026-10-13)

The previous helper revision committed the three successful stage facts but
left the publication operation pending. The current test now calls
`complete_claimed_publication` in the spawned process and asserts the persisted
operation is `completed` before killing that process; the plan still has no
publication link. After the plan lease expires, recovery links that already
completed publication, rejects stale publication/plan claims, and creates no
duplicate operation or audit.

```text
tools/with_disposable_postgresql_acceptance.sh uv run --no-sync --extra test --extra postgres pytest -q --tb=short tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_activation_recovers_completed_publication_after_lost_association
# 1 passed in 2.18s (PostgreSQL 16)

tools/with_disposable_e2e_dependencies.sh uv run --no-sync --extra test --extra mysql pytest -q --tb=short tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_activation_recovers_completed_publication_after_lost_association
# 1 passed in 2.80s (MySQL 8.4.11)
```

Both disposable runners removed their owner-labeled containers. No Nacos or
Consul provider was contacted by this SQL-only refresh. The provider-in-the-loop
Consul recovery counterpart was subsequently verified across PostgreSQL and
MySQL in checklist §15.1058; runtime/instance receipts and remaining B0.3
boundaries remain open.

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

## Real scheduled activation and restoration against disposable Nacos

### Test design

| Field | Acceptance definition |
| --- | --- |
| ID / priority | `PLAN-EXEC-03/05-NACOS` / P0 |
| Source | PLAN-EXEC-03 and PLAN-EXEC-05 above; scheduled plan must use the durable SQL publication outbox, provider CAS, and exact read-back before advancing state. |
| Layer / automation | Opt-in real integration acceptance; isolated PostgreSQL or MySQL plus one disposable Nacos 3.2.4 instance. |
| Preconditions | A synthetic admin/session, one Nacos binding/target, an immutable daily version already present in Nacos, and a separately validated immutable promotion version. The plan has a due activation and later deactivation timestamp. |
| Action | Run the production `RunRuleActivationPlanWorker`, then spawn the production Nacos publication worker against the same SQL authority and Nacos key. After Nacos returns successful activation write, terminate that OS worker with `os._exit` before it can persist the SQL phase receipt. Advance injected clocks beyond the plan and publication leases; run a newly constructed scheduler and publisher to reconcile that same activation publication, then perform the scheduled restoration normally. |
| Assertions | After the child exits, exact promotion bytes are present in Nacos, the outbox write phase is still `running`, and the plan is still `activating`. Recovery reads the exact candidate and completes without another provider-write call; only a later plan-lease reclaim advances it to `active`. Restoration then reaches `completed` only after read-back equals the exact encoded daily version. The plan records distinct activation/restoration publication IDs, each phase has one stable system operation and audit fact, both outbox records complete, and replay after completion adds no provider write or duplicate operation/publication/audit. Final Nacos bytes equal the immutable restoration version. |
| Observability | Assert the persisted plan state/revision/phase publication IDs, operation and publication counts, phase audits, publication write/read-back stages, and exact provider bytes. |
| Cleanup | Delete the unique Nacos dataId, exact plan/phase operations, publication/audit rows, plan, versions/validation receipts, session, and synthetic account in `finally`; remove only the uniquely named disposable container. |

### Commands and result

Run from `components/sentinel/sentinel-console` with credentials for a newly
created disposable database only; the helper starts and removes its own Nacos
3.2.4 container. Do not substitute a shared database or configured Nacos target.

```text
SENTINEL_CONSOLE_TEST_POSTGRES_URL='postgresql+psycopg://<user>:<password>@127.0.0.1:<port>/sentinel_console_test_<unique>' \
  SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 uv run --no-sync --extra test \
  pytest -q tests/test_postgresql_acceptance.py \
  -k sql_rule_outbox_creates_config_in_disposable_nacos
# 1 passed, 10 deselected (PostgreSQL 16)

SENTINEL_CONSOLE_TEST_MYSQL_URL='mysql+asyncmy://<user>:<password>@127.0.0.1:<port>/sentinel_console_test_<unique>' \
  SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 uv run --no-sync --extra test \
  pytest -q tests/test_mysql_migration_acceptance.py \
  -k sql_rule_outbox_creates_config_in_disposable_nacos
# 1 passed, 11 deselected (MySQL 8.4.11)
```

### Explicit limits

This case proves scheduled activation→OS worker exit after successful real Nacos
write→SQL lease recovery/read-back→explicit restoration against real supported
SQL dialects. It does not prove a process crash while the scheduled provider RPC
is in flight, a concurrent external writer racing between restoration preflight
read and Nacos CAS, authentication/TLS deployment, multi-ASGI-worker provider
recovery, production Nacos, or React-to-Python browser E2E. Those remain
separate PLAN-EXEC acceptance rows and the final Dashboard E2E gate.

## Real scheduled activation and restoration against disposable Consul

### Test design and result

| Field | Acceptance definition |
| --- | --- |
| ID / priority | `PLAN-EXEC-03/05-CONSUL` / P1 |
| Source | PLAN-EXEC-03 and PLAN-EXEC-05 above; scheduler state must advance only after the Consul publication worker has conditionally written and exactly read back the immutable phase version. |
| Layer / automation | Opt-in real integration acceptance; isolated PostgreSQL or MySQL plus one disposable ACL-enabled Consul 1.21.1 and private-CA HTTPS test proxy. |
| Preconditions | Synthetic admin/session, two immutable flow versions, an exact-key Consul ACL token, and baseline bytes seeded under one random KV key. |
| Action | Create a persisted activation plan and run the production scheduler. For activation, first drop its CAS before Consul; after lease takeover, let the recovery CAS commit but discard its ACK, then recover from a later lease owner. Repeat a controlled post-write acknowledgement loss for restoration. |
| Assertions | The actual Consul value changes to the exact encoded activation version then back to the exact baseline. During recursive activation uncertainty the SQL publication stays `unknown` and plan stays `activating`; final recovery uses a `consistent=true` exact read and performs no additional CAS. Restoration also completes only after exact read-back. Plan states progress `activating` → `active` → `restoring` → `completed`; exactly one activation and restoration operation/publication exist; replay after completion creates no provider write or new revision; the application token is sent only in the request header. |
| Cleanup | Remove the unique plan, phase operations/publications/audits, immutable versions/validation receipts, session/account, and the uniquely named Consul container in `finally`. |

Run from `components/sentinel/sentinel-console` using isolated loopback database
URLs and the opt-in Consul flag:

```text
SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_postgresql_acceptance.py \
  tests/test_mysql_migration_acceptance.py \
  -k sql_activation_plan_publishes_and_restores_to_disposable_consul
# 2 passed, 23 deselected (PostgreSQL 16 + MySQL 8.4.11)
```

### Recursive recovery acknowledgement loss (2026-10-13)

The scheduled activation acceptance now covers two consecutive uncertain
provider outcomes on the real ACL/TLS Consul path. The initial CAS is received
by the HTTPS proxy and dropped before Consul, leaving the baseline unchanged
and the publication `unknown`. After lease takeover, the recovery CAS commits
the candidate in Consul but the proxy drops its response; SQL remains
`unknown`/`awaiting`, and the activation plan stays `activating`. After another
lease takeover, the next worker sends a `consistent=true` exact-key read,
recognizes the already committed candidate, performs no additional CAS, and
only then allows the scheduler to move the plan to `active`. The shared
acceptance passed against disposable TLS PostgreSQL 16 and MySQL 8.4.11, with
ACL/TLS Consul 1.21.1. The test explicitly counts provider CAS attempts and
checks the final recovery request sequence; each runner owns cleanup of its
containers.

This closes only the recursive recovery-ACK-loss window for scheduled
activation. It does not prove a multi-node Consul consistency model, an unknown
Consul server commit, production ingress/secret rotation, or React-to-Python
browser E2E.

### Boundary

This proves scheduled Consul activation/restoration over both SQL dialects,
including exact read-back, state transitions, replay idempotency, scoped ACL
token placement, cleanup, and controlled post-write acknowledgement-loss
recovery without a second provider write. TLS terminates at the test proxy; this
does not prove Consul's native HTTPS listener, production ACL/token lifecycle,
multi-node Consul consistency, external-writer process concurrency, PostgreSQL
parity for TLS response-loss recovery, a server commit unknown to the proxy,
instance receipts, or React-to-Python browser E2E.
