# B0.2 — Bootstrap database connectivity-check HTTP slice

Status: **HTTP/security and driver-adapter slices implemented; the first-run SQL ASGI composition wires the checker; deployed database acceptance and B0.2 remain open**.

## Contract and boundary

Implements the existing `POST /api/v1/system/bootstrap/database-check`
operation. The route is an HTTP adapter only: it validates the request ID,
exact browser Origin, double-submit CSRF, current bootstrap operator grant,
setup-window state, and the strict SQLite/PostgreSQL/MySQL request union before
calling the consumer-owned `BootstrapDatabaseChecker` port. It returns only the
frozen `reachable` / `unreachable + reason` facts. It never migrates or writes
database state. A missing checker or typed checker outage returns a stable 503.

The application contract excludes the password from dataclass representation
and equality. A deployment-owned target-policy primitive now requires explicit
database-kind/CIDR/port rules, resolves hostnames once with a bounded lookup,
rejects the whole result when any address is outside policy, and returns the
approved address set for pinning. It also rejects universal CIDRs and
link-local/unspecified/multicast destinations. `BootstrapDatabaseConnector`
now consumes this target policy and implements one-shot read-only probes for
PostgreSQL and MySQL. Both use verified TLS, bounded connect/query/check
timeouts and a constant `SELECT 1`; driver failures map to finite reasons
without exposing raw driver messages. PostgreSQL uses `hostaddr` for the
approved IP while retaining the submitted hostname for `verify-full`. MySQL
connects to the approved IP and temporarily supplies the original hostname to
asyncmy's MySQL TLS-upgrade hook. Since that hook is a private asyncmy
implementation detail, the optional MySQL extra is pinned to `asyncmy==0.2.16`
and has a runtime compatibility test; driver upgrades require deliberate
review.

`build_first_run_sql_identity_app` wires a `BootstrapDatabaseConnector` into the
bootstrap check route, using the deployment's database target policy and TLS
configuration. This proves source-level composition, not that a particular
launcher or deployed environment has supplied valid allowlists, trust material,
database drivers, and operational connectivity. SQLite accepts an optional
absolute path supplied only when constructing the checker; the HTTP request
still has no filesystem-path field. The standard first-run SQL composition does
not configure a SQLite path, so a caller that wants this local/test mode must
explicitly inject a checker through the lower-level app composition. When a
path is configured, the probe opens only that existing database through SQLite
URI `mode=ro`, enables connection-local `query_only`, and runs constant
`SELECT 1`; a missing file returns `connection` and is never created. This
check does not initialize schema. TLS root trust must come from deployment
configuration (`postgresql_root_certificate` or a verified
`mysql_ssl_context`) or driver defaults. Synthetic driver tests and a local
asyncmy class contract do not prove real PostgreSQL/MySQL compatibility;
disposable database acceptance remains mandatory before deployed use.

## Risk-to-test matrix

| Risk | Local focused assertion | Stronger acceptance still required |
| --- | --- | --- |
| Unauthenticated or closed setup can probe private targets | initialized/closed/wrong operator returns 403 and checker is untouched | Operator authorization through the mounted browser flow |
| Cross-origin/CSRF request reaches the connector | exact-origin and double-submit checks fail before checker call | Browser to live Console over configured TLS |
| Malformed/extra input reaches connector | strict discriminator, field set, scalar types and boolean-port rejection | Consumer-generated OpenAPI and Python route contract check |
| Credentials leak through object repr or response | candidate repr and all result/error bodies omit password and raw connector details | Captured production logs plus real provider failure cases |
| Checker absence/failure appears successful | stable 503 without infrastructure message | Runtime composition must require a real checker |
| Check performs an unintended mutation | only the injected check port is called; SQLite opens the deployment path read-only and uses connection-local `query_only`; absent files are not created; this route has no migration/write port | Real disposable database verifies no schema/data mutation |
| Route and SQLite checker diverge | ASGI request through the real `BootstrapDatabaseConnector` with a disposable SQLite file; bytes remain unchanged and missing paths stay absent | Real PostgreSQL/MySQL endpoint verifies deployed driver, TLS and network policy |
| DNS rebinding or mixed answers escape destination scope | focused policy tests pin allowlisted DNS answers, reject mixed/oversized sets, and adapter tests verify pinned host/`hostaddr` plus TLS identity arguments | Real disposable PostgreSQL/MySQL acceptance must prove each driver's socket uses only the approved address while TLS verifies the original hostname |

No external PostgreSQL/MySQL, Nacos/Consul, or production credential is used in
this slice. A disposable local SQLite file is used only for the isolated
read-only API-to-connector integration test. The complete Console suite, live
connector matrix and browser-to-Python setup E2E are not claimed.

## Focused verification

- `PYTHONPATH=components/sentinel/sentinel-console/src:components/sentinel/sentinel-console/tests components/sentinel/sentinel-console/.venv/bin/pytest -q -rs components/sentinel/sentinel-console/tests/test_bootstrap_database_check_api.py components/sentinel/sentinel-console/tests/test_bootstrap_database_connector.py components/sentinel/sentinel-console/tests/test_first_run_composition.py`: **20 passed, 1 skipped**. The first-run composition test now asserts it wires a real `BootstrapDatabaseConnector`; the ASGI route test invokes that connector against a disposable deployment-owned SQLite file and asserts unchanged bytes, while a missing path is reported without creation. The run also covers fake remote-driver contracts and DNS-policy bounds. The optional MySQL driver compatibility test was skipped because the MySQL extra is unavailable in this environment.
- The run used an isolated ASGI test client, fake PostgreSQL/MySQL connections, synthetic DNS answers and the local asyncmy class only; no external browser, database, configuration center or submitted credential was used.
- The changed API test and checker sources passed Python `compileall`; a direct trailing-whitespace scan was clean. The MySQL optional extra and Ruff are unavailable in this virtual environment, so those checks are not claimed for this follow-up.
- Console-wide unittest, production startup wiring, real PostgreSQL/MySQL/SQLite integration, live connector matrix and browser-to-Python setup E2E were not run. These remain reserved for their owning milestone, consistent with `dashboard-prototype/docs/TESTING_CADENCE.md`.
