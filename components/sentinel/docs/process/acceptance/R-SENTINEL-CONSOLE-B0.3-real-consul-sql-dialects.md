# B0.3 — SQL outbox to real Consul across production database dialects

Status: **verified for PostgreSQL 16 and MySQL 8.4.11; B0.3 remains open**.

## Acceptance case

| ID | Risk | Required evidence | Result |
| --- | --- | --- | --- |
| PUB-SQL-CONSUL-01 (P1) | SQL publication acceptance/claim and provider CAS/read-back behave differently across real database dialects | Against each isolated SQL dialect, accept a real `SqlAlchemyRuleMutationStore` publish command, execute the composed SQL outbox worker against a disposable Consul, compare exact persisted bytes with the frozen rule version, verify terminal operation/publication facts, and prove replay does not create a second Consul revision. | **Passed** on PostgreSQL 16 + Consul 1.21.1 and MySQL 8.4.11 + Consul 1.21.1. |

The opt-in case is `test_sql_rule_outbox_publishes_to_disposable_consul` in
`tests/test_postgresql_acceptance.py` and
`tests/test_mysql_migration_acceptance.py`; shared setup is
`tests/rule_publication_consul_database_acceptance.py`. It rejects unsupported
SQL dialects. The database acceptance fixtures validate the configured URLs
and require an isolated `sentinel_console_test_*` database on loopback. The
helper starts a uniquely named Consul container on a random loopback port, uses
a random key and synthetic identities, and removes its SQL rows/container in
`finally`.

Reproduction, with disposable loopback PostgreSQL and MySQL test URLs already
exported:

```text
SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 uv run --no-sync --extra test pytest -q \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_sql_rule_outbox_publishes_to_disposable_consul \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_rule_outbox_publishes_to_disposable_consul
```

Result: **2 passed in 5.08s**. `compileall` passed; focused SQLite worker,
composition and Consul writer regression was **32 passed, 2 skipped, 1
deselected**. No configured/shared database or Nacos/Consul service was used;
the only external endpoints were this run's disposable containers.

## Boundary

This proves the SQL outbox → worker → Consul CAS-0 → exact read-back path on
both supported production database dialects. It does not cover Consul ACL/TLS,
Nacos publication, create-only Nacos semantics, Reporter/Collector ingress,
authoritative instance inventory, deployment credentials, or Dashboard-to-
Python browser E2E. Therefore it closes one B0.3 provider/database acceptance
gap but does not close B0.3 or the final E2E gate.
