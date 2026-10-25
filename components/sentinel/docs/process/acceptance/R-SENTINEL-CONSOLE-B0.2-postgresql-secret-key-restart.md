# B0.2 — PostgreSQL bootstrap source-secret key rotation across process restart

Date: 2026-10-12; real isolated PostgreSQL verification: 2026-10-13
Status: **targeted real-PostgreSQL cross-process acceptance passed; B0.2 remains open**.

## Risk and acceptance boundary

The existing SQLite restart slice checks encryption semantics, and the
MySQL-specific acceptance checks those semantics across independent operating
system processes using a real MySQL database. This PostgreSQL-specific case
adds the missing dialect acceptance: bootstrap under `source-v1`, then restart
the Python process and decrypt the persisted envelope with `source-v2` active
while `source-v1` is retained; finally verify that dropping `source-v1` fails
closed.

The test accepts only `postgresql+psycopg` URLs whose host is loopback (or the
explicit test hostname `postgres`) and whose database name begins with
`sentinel_console_test_`. Use a dedicated disposable test database. The case
applies the Console migrations and writes synthetic bootstrap identity/source
records; remove the disposable database after the acceptance run. It does not
connect to Nacos or any other configuration center.

## Assertions

| ID | Risk | Assertion |
| --- | --- | --- |
| B0.2-PG-KEY-01 | Source secret is persisted as plaintext | Initializer process stores only the encrypted envelope and key ID; synthetic source/admin passwords do not occur in the selected SQL row or safe receipt representation |
| B0.2-PG-KEY-02 | Key rotation breaks a running-after-restart source reader | A separate Python process with active `source-v2` and retained `source-v1` resolves the exact source ID, revision and provider, returning the expected synthetic endpoint and credentials |
| B0.2-PG-KEY-03 | Removing an old key returns partial/corrupt credentials | A separate process with only `source-v2` cannot resolve the `source-v1` envelope and reports only `failedClosed` |
| B0.2-PG-KEY-04 | Test accidentally targets a normal database | Non-PostgreSQL drivers, non-loopback hosts, and database names outside `sentinel_console_test_*` are rejected before connecting |

## Command and result

Run from `components/sentinel/sentinel-console`, supplying a disposable,
loopback PostgreSQL database with a unique `sentinel_console_test_*` name:

```text
SENTINEL_CONSOLE_TEST_POSTGRES_URL='postgresql+psycopg://<user>:<password>@127.0.0.1:<port>/sentinel_console_test_<unique>' \
  uv run --project . --extra test --extra postgres pytest -q \
  tests/test_postgresql_bootstrap_secret_rotation_acceptance.py
```

The test is intentionally opt-in. The latest real run used the repository's
loopback-only disposable PostgreSQL runner:

```text
tools/with_disposable_postgresql_acceptance.sh uv run --extra test --extra postgres pytest -q --tb=short tests/test_postgresql_bootstrap_secret_rotation_acceptance.py
1 passed in 1.60s
```

The three Python worker processes shared only the isolated DSN, synthetic
fixture values, and generated key-ring configuration. Worker stdout is
constrained to source identity/key ID and finite result flags. No key material
or submitted password is written to the acceptance document.

## Current execution record

- The test was added after inspection of `RegisteredSourceKeyConfiguration`,
  `AesGcmSecretCipher`, the SQLAlchemy registered-source store, and the existing
  real-MySQL restart test.
- The real PostgreSQL run completed the encrypted bootstrap write, process
  restart with active `source-v2` plus retained `source-v1`, and fail-closed
  lookup after removing `source-v1`. It created only a runner-owned loopback
  PostgreSQL container; a post-run query found no `sentinel-e2e-postgres-*`
  containers.
- Ruff was not run in this acceptance; no lint claim is made.

## Remaining B0.2 gaps

This case only covers PostgreSQL storage/restart behavior for encrypted
registered-source credentials. B0.2 still requires the wider production
dialect, migration, locking/transaction, deployment key-injection and
rotation, setup/identity lifecycle, and browser-to-Python evidence described
in the parent persistence acceptance record. This document does not close B0.2.
