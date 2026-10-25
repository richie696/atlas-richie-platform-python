# B0.2 — MySQL login cooldown through two Uvicorn workers

Date: 2026-10-12  
Status: **targeted real-MySQL two-worker HTTP acceptance passed; B0.2 remains open**.

## Risk and acceptance boundary

The existing SQL limiter tests prove sharing between app instances and spawned
workers. This slice verifies the deployed Console CLI starts two actual Uvicorn
workers, reads the runtime database locator, and serves login requests whose
rate-limit state is persisted in one disposable MySQL 8.4.11 database.

The test uses a synthetic missing username and invalid passwords, loopback HTTP,
an isolated runtime-state directory, and a database name generated with the
`sentinel_console_test_*` prefix. It does not modify a real account or contact a
configuration center.

## Assertions

| Risk | Assertion |
| --- | --- |
| The CLI ignores the configured worker count | The started server output confirms exactly two Uvicorn worker processes. |
| Login attempts are process-local | Two failed HTTP login attempts return the generic unauthenticated response; the next attempt, served by the worker pool, returns bounded `429 rate_limited`. |
| Shared limiter state leaks raw identity | The single persisted row is keyed by the expected client HMAC digest, reaches the configured threshold, and does not expose the synthetic username in the rejection response. |
| Test changes shared state | The test deletes only its generated HMAC row and restores the singleton guard in `finally`; the disposable database is discarded with its container. |

## Command and result

Run from `components/sentinel/sentinel-console`:

```text
./tools/with_disposable_e2e_dependencies.sh uv run --project . --extra test --extra mysql pytest -q \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_two_uvicorn_workers_serve_mysql_login_cooldown_over_http
1 passed in 3.67s
```

The same real SQL-composed Console CLI was started on an ephemeral loopback
port. It served the initialized bootstrap projection and the HTTP login
sequence; the persisted limiter row had the expected failure count and block
expiry. `git diff --check` passed after the run.

## Isolation and cleanup

The repository runner generates a unique run ID and synthetic credentials,
publishes MySQL and Consul only on loopback ephemeral ports, labels each
container with that run ID, and removes only containers whose exact ID and
owner label match the current run. It also removes its anonymous volumes and
temporary TLS files. This run created:

- `sentinel-e2e-mysql-211126aefe1125057cef06355e395a5d`
- `sentinel-e2e-consul-211126aefe1125057cef06355e395a5d`

After the command, `docker container inspect` confirmed both exact container
names were absent. No pre-existing container or volume was stopped or removed.

## Remaining B0.2 boundary

This local test does not establish production ingress/proxy configuration,
multi-host or shared-volume locking, installer secret delivery/rotation,
PostgreSQL parity for this exact two-worker HTTP slice, or React-to-Python
browser E2E. It is evidence for only the MySQL two-worker login-cooldown path;
B0.2 remains open.
