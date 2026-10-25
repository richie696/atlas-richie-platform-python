# B0.1 — Installed Console CLI and SQL first-run acceptance

Status: **focused acceptance passed; this does not close B0.1 or replace full E2E**.

## Scope

This acceptance verifies the separately installed `atlas-richie-sentinel-console`
wheel and its `sentinel-console serve` entry point against disposable MySQL 8.4
and PostgreSQL 16 instances. It exercises the production
`build_first_run_sql_identity_app` composition and SQL lifespan; it does not
call a real configuration center or perform browser E2E.

## Evidence

Command, run from `components/sentinel/sentinel-console`:

```text
tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -q \
  tests/test_installed_cli_bootstrap_acceptance.py
```

Result: **1 passed**. The repository runner created the uniquely labelled
MySQL/Consul pair for run ID
`88950d7ff38c1a16d19e01657b8fed5d`; Docker inspection after completion found
neither exact container name, confirming runner cleanup.

The test:

1. Builds one wheel into a temporary `wheelhouse` (not the repository `dist/`).
2. Installs the wheel and its `mysql,server` extras into a temporary virtual
   environment, then verifies the imported module resolves inside that venv.
3. Leaves the encrypted runtime database locator absent before startup; only
   deployment-owned key material, allowed database target policy, and the
   disposable server certificate are configured.
4. Starts the installed `sentinel-console serve` executable in a separate
   process, explicitly bound to `127.0.0.1` and an ephemeral port. With no
   locator and a closed setup window, the bootstrap read returns
   `initialized=false`, `setupAvailable=false`, and `operatorAuthorized=false`.
5. Opens the one-time setup window with the installed CLI, authorizes the
   synthetic operator over HTTP, and submits the MySQL credentials, built-in
   administrator, and Consul source via the installed service's initialization
   endpoint.
6. Confirms the completed/idempotent operation receipt, encrypted runtime
   locator creation, migrated schema, initialized guard, administrator and
   source persistence, and setup-window closure. The submitted passwords and
   operator code are absent from receipts and persisted state.
7. Re-reads the bootstrap endpoint and confirms it returns only
   `{"initialized": true}` after setup.

### Installed Dashboard asset follow-up (2026-10-13)

The installed CLI test now also requests `/` from the live two-worker service,
extracts a fingerprinted JavaScript or CSS asset URL from the returned HTML,
fetches that asset, and checks the HTML revalidation and immutable asset cache
headers. It requests an unknown `/api/v1/*` path and verifies a JSON
`404 not_found` rather than an SPA fallback.

Verification:

```text
uv run --no-sync pytest -q tests/test_static_web.py tests/test_installed_cli_bootstrap_acceptance.py
# 4 passed, 2 skipped (database-backed installed-wheel cases require disposable runners)

tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -q \
  tests/test_installed_cli_bootstrap_acceptance.py
# 1 passed, 1 skipped (PostgreSQL case requires its separate runner)
```

The disposable MySQL/Consul runner exited successfully; a follow-up container
name check found no containers owned by the run.
This closes only the installed-wheel static asset delivery check; B0.1 and
full browser-to-Python E2E remain open.

### PostgreSQL behind local Apache (2026-10-13)

The same installed-wheel, no-locator first-run path was repeated against the
disposable PostgreSQL 16 TLS runner with the opt-in loopback Apache proxy:

```text
SENTINEL_CONSOLE_RUN_APACHE_PROXY_ACCEPTANCE=1 \
  tools/with_disposable_postgresql_acceptance.sh uv run --no-sync pytest -vv -s \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_postgresql_first_run_with_two_workers
# 1 passed in 21.05s
```

This covers the installed CLI's two Uvicorn workers, setup from an absent
runtime locator, PostgreSQL TLS/migrations, bootstrap authorization and
initialization through HTTP, and the local Apache prefix/static/API proxy. The
same six login attempts carrying distinct spoofed `X-Forwarded-For` values are
bounded by the shared PostgreSQL-backed attempt authority (five `401`, then
`429`), confirming that caller-supplied addresses do not create independent
throttle identities. The disposable PostgreSQL runner completed cleanup; a
post-run query found no owner-labelled acceptance containers.

This is local disposable infrastructure evidence only. It does not establish
the user's production ingress, TLS termination policy, cloud network or
Secret Manager delivery, nor does it exercise a browser.

### Installed CLI behind local Apache (2026-10-13)

The opt-in `SENTINEL_CONSOLE_RUN_APACHE_PROXY_ACCEPTANCE=1` path runs the
installed two-worker CLI behind a private, loopback-only Apache 2.4.67 config.
The proxy strips `/ops/sentinel/`, proxies `/assets/` and `/api/` separately,
and removes caller-supplied `X-Forwarded-For` before Apache adds the observed
peer. The application trusts only `127.0.0.1/32` for this run.

```text
SENTINEL_CONSOLE_RUN_APACHE_PROXY_ACCEPTANCE=1 \
  tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -vv -s \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_migrates_and_serves_safe_first_run_state
# 1 passed in 13.16s (rerun after removing pre-start locator provisioning)
```

Through Apache, the prefixed login route and fingerprinted asset returned 200;
an unknown API returned JSON `404 not_found`. Six login attempts supplied six
different forged XFF addresses: the first five returned 401 and the sixth
returned 429, demonstrating that the untrusted values did not split the SQL
throttle identity. Initial runs ended with runner exit 143 because Apache and
its workers shared the parent process group; both launched services now use
isolated sessions, and the final run exited 0. This rerun started without a
runtime locator and completed the HTTP first-run initialization before testing
the proxy. Disposable MySQL/Consul containers and Apache temporary config were
cleaned up. This is local proxy + installed CLI + MySQL evidence, not acceptance
of production ingress, TLS, cloud networking, or the complete Dashboard E2E.

### PostgreSQL no-locator first-run and worker-health timeout (2026-10-13)

The PostgreSQL installed-wheel case uses the same no-prewritten-locator path.
Its initial two-worker run exposed a deployment defect: Uvicorn's default
5-second worker health check killed the worker handling first-run setup while
fresh PostgreSQL schema migrations were in progress, dropping the HTTP
connection. One-worker diagnostic runs succeeded. The CLI now configures a
bounded 30-second worker health-check timeout so a worker doing first-run
migrations is not mistaken for a hung process.

```text
tools/with_disposable_postgresql_acceptance.sh uv run --no-sync pytest -vv -s \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_postgresql_first_run_with_two_workers
# 1 passed in 15.30s
```

After the fix, the installed wheel with two Uvicorn workers started with no
runtime locator, completed the operator-authorized PostgreSQL setup via HTTP,
persisted the locator, and verified migration/initialized state. The MySQL
Apache + installed-wheel no-locator flow also passed after the timeout change
(1 passed in 18.37s). The focused CLI/bootstrap/runtime-provider regression was
**45 passed, 2 skipped**; `compileall` and `git diff --check` passed. Ruff is
not installed in this environment. PostgreSQL/MySQL disposable containers were
removed by their exact-owner runners. This does not prove production ingress,
Kubernetes Secret delivery, or browser E2E.

### Installed MySQL CLI with live Consul source probe (2026-10-13)

Risk case: first-run setup can persist a syntactically valid Consul endpoint
without proving that the installed service's real registered-source checker can
reach it. The opt-in MySQL + Consul runner now supplies its dynamically assigned
loopback Consul URL to the installed CLI test. The test must reject any endpoint
other than `http://127.0.0.1:<runner-port>` and installs a target rule limited to
`127.0.0.1/32` and that exact port; it must not widen general SSRF policy.

After first-run initialization, the test logs in as the synthetic administrator
through the installed HTTP service, reads the registered source, probes a
candidate with `authentication.mode=none`, and verifies `/system/connections`
remains `unknown` (candidate probes are non-persisting). It then probes the
registered source using `authentication.mode=keep`, verifies the real Consul
check returns `read` and `watch`, and verifies the exact registered source is
reported as `available`. The no-Consul PostgreSQL path and default unit setup
remain unchanged.

The acceptance should be run with the exact disposable MySQL/Consul runner; its
exit cleanup must remove only the run-owned containers and the post-run check
must find neither owner container. This covers installed-wheel → first-run
HTTP → SQL registered source → real Consul read-only probe → HTTP status readback;
it does not prove Consul ACL/TLS, production deployment injection, write-back,
or React browser E2E.

### SQL registered-source credential and Consul ACL probe (2026-10-13)

Risk case: a registered Consul ACL token must be encrypted at rest, omitted from
source/connection/check responses, resolved only for a protected probe, and
sent over verified TLS to a deployment-allowlisted endpoint. The test composes
the production SQL identity app with a random ACL-enabled Consul service, a
read-only probe token, a private test CA, and a rule limited to the helper's
loopback address and dynamically assigned TLS proxy port. It registers via the
admin/CSRF/idempotency API, asserts SQL contains only an encrypted credential
payload, checks through `authentication.mode=keep`, and verifies the connection
read model transitions from `unknown` to `available` with `read/watch`.

Run it only through the disposable MySQL/Consul wrapper with
`SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE=1`; the source-specific helper owns
and removes its separately named ACL Consul and temporary CA/proxy. This covers
the production SQL composition and API path, but not the installed wheel's CA
file injection, production Secret Manager, user ingress, or browser workflow.

Verification (`components/sentinel/sentinel-console`):

```text
SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE=1 \
  ./tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -q \
  tests/test_registered_source_store_api_integration.py \
  tests/test_consul_acl_auth_acceptance.py
# 6 passed
```

The run exercised MySQL 8.4.11, the wrapper's disposable Consul, and the
integration fixture's separately owned ACL-enabled Consul with private-CA TLS.
It included an invalid ACL token returning the stable `authentication` reason,
followed by the persisted read-only token succeeding via `keep`; SQL stored an
encrypted payload and the token was absent from API responses and the observed
request path (it was sent in the Consul header). All five exact-name outer
MySQL/Consul pairs from the failed-fixture diagnostic and successful reruns were
confirmed absent; `sentinel-consul-acl-*` had no remaining containers.
`compileall` and `git diff --check` passed. Ruff is unavailable in the current
environment. This is real local ACL/TLS and SQL composition evidence, not
production CA/secret distribution or ingress acceptance.

### Installed wheel with ACL-enabled Consul and deployment CA injection

Risk case: the SQL composition's source credential resolver and TLS context must
also work in the separately installed wheel, not only in-process ASGI tests.
Start the existing ACL Consul helper while the installed CLI test runs in a
worker thread so the helper's HTTPS proxy event loop remains live. Supply only
its dynamic `https://127.0.0.1:<port>` endpoint, scoped read token, temporary CA
file path, and matching exact-port target rule to the installed CLI environment.
First-run HTTP setup should persist direct ACL credentials; after setup, an
authenticated admin should receive only safe source metadata, get an
authentication rejection for an invalid-token candidate, then get reachable
`read/watch` for the registered source via `keep`. A no-token candidate is not
used as the ACL-denial assertion: Consul's root KV key-list endpoint returns
`200 []` anonymously, including when the test key exists, so that response does
not prove ACL authorization. Assert the token is absent
from SQL plaintext, API responses, runtime state files, and service logs. The
ACL fixture, CA file, and all disposable containers must be removed on success
and failure. This does not substitute for production Secret Manager or user
ingress validation.

Verification (`components/sentinel/sentinel-console`):

```text
SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE=1 \
  ./tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -q \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliConsulAclAcceptanceTests::test_installed_cli_uses_persisted_acl_source_over_verified_tls
# 1 passed in 19.73s

./tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -q \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_migrates_and_serves_safe_first_run_state
# 1 passed in 19.19s
```

The ACL case builds and installs a temporary wheel, starts the actual two-worker
CLI, initializes its database and source over the first-run HTTP API, then
probes the separately owned ACL Consul through verified TLS using the configured
CA file. A deliberately invalid token returns `unreachable/authentication`; the
registered token resolved by `keep` returns `reachable` with `read/watch` and
the connection read model becomes `available`. SQL contains only encrypted
credential bytes, and the token is absent from API bodies, the installed CLI
process environment, runtime files and service logs; the fixture observed it
only in the HTTPS header, never the URL.
The ordinary no-auth MySQL + Consul installed-wheel path passed separately.
Both runner invocations cleaned their exact owner-labelled containers; the
separately named ACL Consul helper also closes in `finally`. The initial combined
invocation was invalid as a regression check because the two first-run tests
shared the same runner database; final evidence uses independent runners. The
ACL case established that Consul 1.21.1 returns `200 []` for an anonymous root
KV key-list request even when a test key exists, so the contract uses an invalid
token for stable ACL-denial evidence.

This adds installed-wheel ACL/TLS evidence only. Production CA and Secret
injection, ingress, remote Consul topology, rule writes, and React browser E2E
remain unproven; B0.1 and B0.5 stay open.

### Installed wheel with MySQL/PostgreSQL-backed account commands

Risk case: account-command unit/ASGI tests do not prove that the installed
two-worker CLI composes the production SQL command store and account directory
with the production session/authorization routes. The opt-in installed-wheel
acceptance should initialize a fresh disposable database for each supported
SQL dialect, authenticate
the built-in administrator over HTTP, list accounts without credential
material, create one `view` account, replay the exact same idempotency key and
input without a duplicate row, then authenticate as `view` and prove both
account-directory read and account mutation are rejected with `403 forbidden`.
Promoting the viewer must update the role visible to its existing session;
disabling it must revoke that session. Attempts to disable/demote the built-in
administrator must return durable `built_in` rejections. The same installed
workflow changes the administrator's own password, proves the old session is
revoked, rejects the old password, and accepts a fresh login with the new
password.
The final SQL check must show exactly one created viewer, an active initialized
guard, and no password/token values in API responses or logs. Use a distinct
runner invocation/database for this first-run workflow; do not share a database
between installed-CLI tests. This is server/API + SQL integration evidence, not
React browser E2E or production identity-store acceptance.

Verification (`components/sentinel/sentinel-console`, each dialect uses a
separate fresh runner/database):

```text
SENTINEL_CONSOLE_RUN_IDENTITY_ACCEPTANCE=1 \
  ./tools/with_disposable_e2e_dependencies.sh uv run --no-sync pytest -q \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_persists_account_commands_and_enforces_view_role
# latest: 1 passed in 18.79s

SENTINEL_CONSOLE_RUN_IDENTITY_ACCEPTANCE=1 \
  ./tools/with_disposable_postgresql_acceptance.sh uv run --no-sync pytest -q \
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_postgresql_account_commands_and_enforces_view_role
# latest: 1 passed in 12.88s

uv run --no-sync pytest -q \
  tests/test_account_commands_api.py tests/test_account_directory_api.py \
  tests/test_account_commands.py tests/test_account_directory_persistence.py \
  tests/test_account_command_composition.py
# latest: 37 passed in 8.55s
```

Each live test builds and installs the wheel into a temporary environment and
uses the real two-worker CLI with its own fresh MySQL 8.4.11 or PostgreSQL 16.10
database. After adding password, role/status mutation, built-in protection and
query-warning and password-hash assertions, the installed workflows passed on
PostgreSQL in 12.88s and MySQL in 18.79s. The HTTP path created one
viewer and exact replay returned the same receipt; a second list-read and
create attempt under the viewer session each returned `403 forbidden`. A direct
SQL read confirmed exactly the built-in active admin and one disabled viewer
whose latest role was admin, with five durable command-operation rows.
Passwords were absent from directory/command responses
and the service log; changing the admin password revoked the old session and
credential, while a fresh session with the new credential succeeded. The disposable MySQL/Consul runner cleaned its exact
owner-labelled containers; post-run container-name inspection was empty.

This adds server/API-to-MySQL and server/API-to-PostgreSQL acceptance only. It
does not prove browser-rendered role management, account
status/role mutation and last-admin concurrency over this same installed CLI,
or final React-to-Python E2E; B0.2 and B0.5 remain open.

## Boundaries not proven

- This proves the installed service's API first-run path with a synthetic
  operator, disposable SQL databases, and the opt-in local Consul check; it does
  not prove browser rendering/interaction, production proxy configuration, or
  that public network binding is safe for a particular deployment.
- The CLI has no dedicated `/ready` endpoint in this slice; successful Uvicorn
  startup plus the live bootstrap read is the readiness evidence used here.
- No Nacos endpoint was contacted. Consul calls used only disposable loopback
  instances (including a test-only ACL/TLS proxy); no production Consul ACL/TLS
  or deployment credential injection was exercised.
- Browser-to-Python E2E, production TLS deployment policy, and full B0.1 signoff
  remain open.
