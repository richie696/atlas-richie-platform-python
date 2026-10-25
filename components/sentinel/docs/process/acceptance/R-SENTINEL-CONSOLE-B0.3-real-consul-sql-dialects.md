# B0.3 — SQL outbox to real Consul across production database dialects

Status: **direct publication and scheduled activation/restoration verified for PostgreSQL 16 and MySQL 8.4.11; B0.3 remains open**.

## Acceptance case

| ID | Risk | Required evidence | Result |
| --- | --- | --- | --- |
| PUB-SQL-CONSUL-01 (P1) | SQL publication acceptance/claim and provider CAS/read-back behave differently across real database dialects | Against each isolated SQL dialect, accept a real `SqlAlchemyRuleMutationStore` publish command, execute the composed SQL outbox worker against a disposable Consul, compare exact persisted bytes with the frozen rule version, verify terminal operation/publication facts, and prove replay does not create a second Consul revision. | **Passed** on PostgreSQL 16 + Consul 1.21.1 and MySQL 8.4.11 + Consul 1.21.1. |
| PLAN-EXEC-03/05-CONSUL (P1) | Scheduled plan phases may not wait for provider read-back, restore wrong bytes, or duplicate writes after uncertain acknowledgement across SQL dialects | Create a due plan with immutable promotion/restoration versions, run the SQL scheduler and composed Consul publisher, discard acknowledgement after each real Consul write/read-back, then recover via exact read and assert lifecycle state on each supported SQL dialect. | **Passed** on PostgreSQL 16 + Consul 1.21.1 and MySQL 8.4.11 + Consul 1.21.1; both phase recoveries made zero additional writes. |
| PLAN-EXEC-04-CONSUL (P1) | An independent configuration-center writer changes the provider baseline after activation or restoration preflight but before CAS | Run separate due activation and restoration plans against PostgreSQL/MySQL and disposable ACL-enabled Consul; inject an authorized external KV write immediately before each real Consul CAS; require stale CAS rejection, exact external bytes retained, SQL publication `failed/conflict`, plan `blocked`, and no restoration publication after activation conflict. | **Passed** on PostgreSQL 16 + MySQL 8.4.11 + disposable Consul 1.21.1 for both scheduled phases. |
| PUB-SQL-CONSUL-02 (P0) | Worker process exits after Consul CAS commits but before SQL records the provider receipt | A spawned SQL outbox worker performs the real CAS, pauses before returning the receipt, and is forcibly terminated; after lease expiry, a fresh worker exact-reads and completes without a second CAS on each SQL dialect. | **Passed** on PostgreSQL 16 + Consul 1.21.1 and MySQL 8.4.11 + Consul 1.21.1. |

The direct opt-in case is `test_sql_rule_outbox_publishes_to_disposable_consul`; the
scheduled case is `test_sql_activation_plan_publishes_and_restores_to_disposable_consul` in
`tests/test_postgresql_acceptance.py` and
`tests/test_mysql_migration_acceptance.py`; shared setup is
`tests/rule_publication_consul_database_acceptance.py`. It rejects unsupported
SQL dialects. The database acceptance fixtures validate the configured URLs
and require an isolated `sentinel_console_test_*` database on loopback. The
helper starts a uniquely named Consul container on a random loopback port, uses
a random key and synthetic identities, and removes its SQL rows/container in
`finally`.

## Process termination after a real Consul write

The scheduled acknowledgement-loss case covers an in-process uncertainty seam.
This P0 case covers durable SQL recovery across an OS process boundary:

1. A spawned worker claims a real SQL publication and performs the actual CAS
   against the helper's ACL-enabled disposable Consul key.
2. A test-only wrapper pauses only after the production writer receives the
   successful CAS response, before the worker can record the phase receipt.
   The parent verifies the exact remote bytes and persisted SQL write phase,
   then forcibly terminates the child.
3. After the persisted publication lease expires, a fresh composed worker must
   recover by exact read, perform zero additional provider writes, and leave
   exactly one operation/publication/audit trail.

The acceptance is implemented by
`assert_consul_process_termination_recovers_after_real_write` in
`tests/rule_publication_consul_database_acceptance.py`, with opt-in wrappers in
both SQL dialect acceptance suites. The test child receives only synthetic
ACL credentials and the test-only CA; no shared database or configured Consul
service is in scope. It reports only after the production writer has received
Consul's successful CAS response and completed exact read-back. The parent
verifies the bytes and still-running SQL write phase, terminates the worker,
advances the injected clock beyond the 60-second lease, then requires a fresh
worker to finish from an exact read without another CAS. Packet loss during an
in-flight provider request and an unknown server commit outcome remain separate
boundaries.

The final opt-in PostgreSQL 16 + MySQL 8.4.11 run returned **2 passed in 2.97s**.
It verified the initial SQL operation remained pending with write phase
`running` and read-back `awaiting`; after recovery there was one publication,
one completed operation, one accepted/completed audit pair, no extra provider
write, and no Consul `ModifyIndex` change. The publication-worker and mutation
store focused suite returned **37 passed, 2 skipped in 12.52s**. Ruff check
(excluding existing `ASYNC221` / `SIM117` findings in the disposable Consul
fixture), Ruff format, Python compilation, and `git diff --check` passed. The
disposable PostgreSQL, MySQL, and Consul containers were removed after the run.

Reproduce direct and scheduled acceptance, with disposable loopback PostgreSQL
and MySQL test URLs already exported:

```text
SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 uv run --no-sync --extra test pytest -q \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_sql_rule_outbox_publishes_to_disposable_consul \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_rule_outbox_publishes_to_disposable_consul

SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 uv run --no-sync --extra test pytest -q \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_sql_activation_plan_publishes_and_restores_to_disposable_consul \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_activation_plan_publishes_and_restores_to_disposable_consul

SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 uv run --no-sync --extra test pytest -q \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_consul_process_termination_recovers_after_real_write \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_consul_process_termination_recovers_after_real_write
```

The scheduled case with activation/restoration acknowledgement-loss recovery
returned **2 passed, 23 deselected in 5.62s**. The combined direct + scheduled
rerun returned **4 passed, 21 deselected in 5.62s**;
the focused activation/Consul worker suite returned **51 passed in 1.29s**.
Python compilation and `git diff --check` passed. No configured/shared database
or Nacos/Consul service was used; the only external endpoints were this run's
disposable containers.

## Scheduled Consul external-writer race

The scheduled acceptance runs a second, non-overlapping activation plan after
the acknowledgement-loss recovery scenario returns the binding to its
immutable daily baseline. Immediately before production
`ConsulRuleSourceWriter.write` issues CAS, the test writes a distinct valid
rule snapshot with the disposable fixture's management token. The production
writer still uses the previously read `ModifyIndex`; Consul returns CAS false,
the SQL publication records a failed `conflict`, and the plan scheduler
persists `blocked` with no restoration publication. Re-reading through the
application token returns the external snapshot byte-for-byte. Both isolated
PostgreSQL 16 and MySQL 8.4.11 runs passed (**2 passed in 3.92s**). Cleanup
removes both plans and their operations/publications/audits and stops the
disposable services. This is an in-process controlled interleaving against the
real Consul CAS service, not a multi-host deployment or packet-loss test. A
second scheduled plan covers restoration: after its immutable activation
version is applied and the plan is `active`, the test advances to restoration,
writes distinct external bytes after restoration preflight, and requires stale
CAS rejection, persisted `blocked/conflict`, no retry claim, and exact external
bytes preserved. Both phase-specific races passed on PostgreSQL 16 and MySQL
8.4.11 (**2 passed in 4.93s**). Python `compileall`, Ruff check/format and
`git diff --check` also pass for the acceptance helper.

## Boundary

This proves direct SQL outbox publication and scheduled activation/restoration
through the Consul worker, CAS and exact read-back on both supported production
database dialects. It also proves scheduled activation and restoration
conflict protection against an external Consul writer. Controlled acknowledgement loss after each actual
provider write is reconciled without another write. Consul TLS terminates at
the disposable test proxy. It does not cover Consul native HTTPS, production
ACL/token lifecycle, multi-node Consul consistency, an unknown Consul server
commit, failure before the proxy receives the request, Nacos publication,
Reporter/Collector ingress, authoritative instance inventory, or
Dashboard-to-Python browser E2E. §15.948 separately proves the narrower
committed-write/response-drop/process-termination case on PostgreSQL. These
close additional B0.3 provider/database evidence gaps but do not close B0.3 or
the final E2E gate.

## Scheduled Consul activation worker process loss

The scheduled activation/restoration acceptance now includes a second plan
whose activation publication worker runs in a spawned OS process. The child
uses its own SQLAlchemy engine and production Consul worker composition. It
executes the real ACL-scoped Consul CAS and exact read-back, then calls
`os._exit` before control returns to the publication worker that records the
SQL phase receipt. The parent keeps the local HTTPS proxy event loop running
while awaiting the child, verifies the plan is still `activating` and the SQL
publication is `write=running/read_back=awaiting`, then advances the injected
clock past the lease. A new worker reconciles the exact Consul bytes with zero
additional writes; the plan advances to `active` and the following scheduled
restoration writes and verifies the immutable baseline.

PostgreSQL 16 and MySQL 8.4.11 each passed the scheduled activation
process-loss/recovery/restoration test (**1 passed per dialect**). The direct
publication process-termination tests were also rerun on both dialects
(**2 passed**), and the publication-worker/mutation-store/composition focused
suite returned **42 passed, 2 skipped**. Ruff check/format, Python compilation,
and scoped `git diff --check` passed. The only database/Consul instances used
were uniquely named loopback containers created for these tests; all were
stopped and removed afterwards.

This extends PLAN-EXEC-03 with a real Consul scheduled activation receipt-loss
window; at the time of that test, the additional response-drop window had not
been run on PostgreSQL. §15.948 below adds that counterpart. An unknown server
commit, multi-node Consul consistency and production token/TLS lifecycle remain
outside this evidence, and B0.3 remains open.

PostgreSQL parity for the committed-write response-loss window was verified on
2026-10-12 (§15.948). The remaining transport boundary is an unknown Consul
server commit or failure before the proxy receives the request.

## PostgreSQL TLS response-loss parity (2026-10-12)

`SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 uv run --extra test --extra postgres pytest -q tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_consul_process_termination_recovers_after_real_write` returned **1 passed in 2.92s** against PostgreSQL 16 and disposable ACL Consul 1.21.1. The Consul proxy dropped the caller response after observing a successful real CAS commit; the spawned worker was terminated while the request remained unresolved. After lease expiry, a replacement worker exact-read the committed value, completed the operation and performed zero additional provider writes. Random owner-labeled PostgreSQL on tmpfs and the fixture-owned Consul were removed and verified absent. This closes PostgreSQL parity for the specific §15.717 MySQL fault window; it does not prove an unknown server commit, pre-proxy request failure, production Consul deployment or Dashboard browser E2E.
