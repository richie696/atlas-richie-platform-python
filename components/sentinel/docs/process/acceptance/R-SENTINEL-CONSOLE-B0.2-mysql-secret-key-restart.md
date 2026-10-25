# B0.2 — MySQL bootstrap source-secret key rotation across process restart

Date: 2026-10-12
Status: **targeted real-MySQL cross-process acceptance passed; B0.2 remains open**.

## Risk and evidence boundary

The SQLite restart slice proves cipher behavior but does not exercise a
production SQL dialect or an OS process boundary. This acceptance uses the
Console bootstrap transaction and registered-source SQL adapter against the
repository's disposable MySQL 8.4.11 runner. Three separate Python processes
exercise initial persistence, recovery after changing the active encryption
key while retaining the old key, and fail-closed behavior after removing that
old key.

The process boundary is real: the initializer process exits before either
reader process starts. The worker receives only synthetic test credentials and
key-ring values through its isolated environment. Its stdout contains only
source identity, the TLS cipher name, and finite result flags; it never prints
credential or key material.

## Assertions

| ID | Risk | Evidence |
| --- | --- | --- |
| B0.2-KEY-01 | Bootstrap does not persist the source credential in MySQL | Real MySQL bootstrap transaction completes over verified TLS; stored key ID is `source-v1`; row repr and initialization receipt do not contain synthetic passwords |
| B0.2-KEY-02 | New process cannot decrypt the old envelope after active-key rotation | Independent process loads active `source-v2` plus retained `source-v1`, then resolves the credential only for the exact persisted source ID, revision, and Nacos provider; endpoint, username, and password match the synthetic submitted values |
| B0.2-KEY-03 | Removing the prior key silently returns partial or corrupt credentials | Independent process loads only active `source-v2`; resolving the `source-v1` envelope raises `RegisteredSourceCredentialsUnavailable` and is reported as `failedClosed` |

## Commands and result

Real cross-process key-rotation acceptance:

```text
./tools/with_disposable_e2e_dependencies.sh uv run --project . --extra test --extra mysql pytest -q tests/test_mysql_bootstrap_secret_rotation_acceptance.py
1 passed in 2.53s
```

Related MySQL bootstrap regression slice:

```text
./tools/with_disposable_e2e_dependencies.sh uv run --project . --extra test --extra mysql pytest -q \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_competing_bootstrap_initializations_are_serialized \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_bootstrap_retries_are_deduplicated_and_actor_bound \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_z_full_first_run_http_path_persists_setup
3 passed in 4.93s
```

The focused tests also passed Python bytecode compilation and `git diff --check`.

## Isolation and cleanup

The repository runner confirmed Docker 29.8.2 was available and found no
pre-existing containers with its owner label before launch. It created only
run-labelled, loopback-published dependencies; no application/user database,
configuration center, or named data volume was used. The final key-rotation run
used these exact disposable containers:

- `sentinel-e2e-mysql-17d6763584d35c367feeb6c5a93edf3d`
- `sentinel-e2e-consul-17d6763584d35c367feeb6c5a93edf3d`

Both were removed by the runner. A subsequent `docker container inspect` using
those exact names confirmed both were absent. The runner also removed its
container-associated anonymous volumes, temporary CA, and generated TLS files.
The related bootstrap regression run used separate run ID
`8e275e443f2f0b8c6ee940ac655c81f0`; its exact MySQL and Consul containers were
also confirmed absent after exit.

## Remaining boundary

This proves MySQL persistence, verified TLS for the key-rotation process path,
cross-OS-process recovery, and missing-old-key fail-closed behavior for the
registered bootstrap source credential. It does not prove deployment secret
injection/rotation orchestration, Kubernetes or shared-volume topology, real
Nacos access, multi-host locking, the full identity lifecycle, or React-to-
Python browser E2E. No central checklist status is changed by this focused
evidence.
