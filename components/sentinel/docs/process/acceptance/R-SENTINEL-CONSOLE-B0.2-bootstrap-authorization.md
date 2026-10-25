# B0.2 — Bootstrap authorization HTTP slice

Status: **HTTP contract, local authorities and installed-wheel CLI→HTTP first-run acceptance on disposable TLS MySQL and PostgreSQL implemented; production deployment acceptance remains open**.

## Contract and boundary

Implements `POST /api/v1/system/bootstrap/authorize`. The HTTP adapter
validates request ID, exact allowlisted Origin, and a strict write-only
`operatorCode` body before calling `BootstrapAuthorizationAuthority`. The
authority is responsible for atomically verifying the deployment setup window
and code, rate limiting by the resolved client address, and creating an opaque
grant; the HTTP layer has no local or per-process fallback.

Successful exchange returns only `{"authorized": true}` and sets short-lived
(`1..900` seconds), Secure, HttpOnly, SameSite=Strict bootstrap and CSRF
cookies. The opaque token is restricted to URL-safe random-looking material
and excluded from dataclass repr/equality. Rejected code, closed setup, rate
limit and authority outage map to finite 403/409/429/503 responses. The route
does not authenticate an administrator. Missing authority fails closed.

`BootstrapAuthorizationConfiguration` now reads the operator code and an
independent HMAC fingerprint key from required deployment environment values;
the code is write-only and neither secret appears in configuration `repr`.
`LocalBootstrapAuthorizationAuthority` implements both authorization and
opaque-session verification Ports. It stores only keyed fingerprints, a
bounded per-address failure window and the expiring grant fingerprint. A
separate local POSIX workflow lock serializes exchanges across workers sharing
that host filesystem. Changing the configured operator code invalidates
previous grants and opens a new one-time generation. The ASGI route now checks
the CSRF double-submit cookie/header pair in addition to exact Origin before
calling the authority.

This is not a general distributed/multi-host authority: no NFS or cross-host
lock guarantee is claimed. Operator-code generation/rotation remains the
deployment's secret-management action, and a real worker topology/mount must
be accepted before production use.

`build_sql_identity_app()` can construct this same adapter for both
authorization Ports from an explicit configuration object and rejects mixing
that configuration with separately supplied authority Ports.
`build_first_run_sql_identity_app()` now wires the setup-window and encrypted
runtime-locator stores, local authority and initialization lock, cross-store
coordinator, lazy runtime engine, read-only database checker, SQL identity
adapters and ASGI lifespan from one immutable explicit configuration. It does
not read the process environment, open the setup window, choose a permissive
database target policy, create secrets, or configure production proxy trust.
One provider-checker instance can serve both first-run source verification and
registered-source verification; direct setup credentials are adapted only for
the bounded read-only probe and never persisted.

## Deployment authority adapter — test design before implementation

The selected implementation is a local POSIX file-backed adapter for the
existing application ports. The code itself is deployment-provided through a
secret environment input and is never persisted; the authority file stores
only keyed fingerprints, bounded rate-limit state, and expiring opaque-grant
fingerprints. Every read/modify/write exchange is serialized by the existing
`LocalAtomicFileStore` lock, and the independent setup-window reader remains
the authority for whether code exchange is currently allowed.

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| BOOT-AUTH-01 | Missing/closed setup window issues a grant | Authority | Closed or missing window returns `SETUP_CLOSED`; code is not evaluated and no grant state is written |
| BOOT-AUTH-02 | Wrong code is accepted or stored in clear text | Authority + file adapter | Wrong code returns `REJECTED`; raw code is absent from file, repr, and surfaced errors |
| BOOT-AUTH-03 | Retry limits reset on worker restart | Two authority objects + shared file | Failures from one authority cause the second to return bounded `RATE_LIMITED` for the same resolved client address |
| BOOT-AUTH-04 | Two workers both consume one operator code | Concurrent adapter test | Exactly one request receives a grant; persisted state contains no raw session token |
| BOOT-AUTH-05 | Worker restart loses a valid grant or expiry is ignored | Adapter reconstruction + clock control | Valid opaque grant verifies after reconstruction until expiry and fails at/after expiry |
| BOOT-AUTH-06 | Malformed/unsafe authority file opens setup | File-adapter failure | Corrupt, symlinked, overly permissive or unavailable state fails closed as `BootstrapAuthorityUnavailable` |
| BOOT-AUTH-07 | Initialization closure blocks original receipt recovery | Use-case contract | Exchange is closed; an unexpired grant can only reach the existing original-request receipt reader, not a new initialize operation |
| BOOT-AUTH-08 | Rotation retains stale grants/consumed code | Authority + configuration | Changing the provisioned code fingerprint invalidates prior grants and starts a fresh one-time-code generation; secrets never appear in config repr |
| BOOT-AUTH-09 | Cross-site authorize request reaches the authority | ASGI route | Missing/mismatched bootstrap CSRF cookie/header rejects before code parsing or authority invocation |

These are local POSIX semantics, not a claim about NFS or multi-host locking.
The final deployment acceptance must still verify the actual configured mount,
worker topology, secret injection/rotation and trusted-proxy address policy.

## First-run deployment composition — focused test design

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| BOOT-COMPOSE-01 | Missing env silently selects insecure defaults | Config | Missing any required file path, HMAC/encryption key, target allowlist, browser origin, or rate limit rejects with a generic error that contains no secret |
| BOOT-COMPOSE-02 | Target policy accepts broad/unintended network access | Config | Empty, wildcard, SQLite, malformed CIDR/port/provider and duplicate syntax reject; supported explicit CIDRs produce only their declared kind/host/port grants |
| BOOT-COMPOSE-03 | Arbitrary X-Forwarded-For changes login throttle identity | API composition | Only configured trusted proxy CIDRs enable forwarding; untrusted immediate peers ignore forged forwarding headers |
| BOOT-COMPOSE-04 | App construction opens setup or writes deployment state | Composition | Environment-to-app construction is side-effect free; absent setup-window file stays closed and no locator/grant file is created |
| BOOT-COMPOSE-05 | Environment config leaks credentials in repr/error | Config | Database trust paths and operator/account/source/idempotency keys are omitted from repr and parse errors |

These are parser/composition guarantees. They do not replace a deployment run
with a real secret source, ingress chain, database, or filesystem mount.

## Kubernetes shared-volume test design

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| BOOT-K8S-01 (P1) | Two Console replicas sharing a deployment PVC do not share the file authority's advisory lock | Disposable local Kubernetes integration | Two indexed worker Pods mount one PVC and import the production `LocalAtomicFileStore`; one Pod holds the actual exclusive lock while the other attempts CAS; the waiter must block, exactly one CAS wins, the other gets conflict, and a verifier Pod reads the persisted winner |

This test is scoped to a disposable single-node Docker Desktop cluster and its
`hostpath` StorageClass. It is not proof for NFS/RWX, multi-node scheduling,
cloud CSI, production ingress, or a secret manager. The runner must refuse any
non-`docker-desktop` current context and delete only its unique namespace.

## Installed Console reverse-proxy test design

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| BOOT-PROXY-01 (P1) | Prefix-stripping ingress breaks the installed app shell, fingerprinted assets, or API/SPA boundary | Installed wheel + live CLI + local Apache + disposable MySQL | A loopback-only CLI behind Apache serves a prefixed deep link and built assets, while an unknown API remains JSON `404 not_found` |
| BOOT-PROXY-02 (P1) | Client-supplied `X-Forwarded-For` values choose distinct SQL login-throttle identities through the trusted proxy | Real local HTTP proxy + installed CLI + disposable MySQL | Apache removes the untrusted incoming header and appends the observed loopback peer; several distinct spoof values still share one throttle bucket and the threshold produces `429` |

The test requires the explicit `SENTINEL_CONSOLE_RUN_APACHE_PROXY_ACCEPTANCE=1`
opt-in, local Apache proxy/header modules, and the disposable MySQL runner.
Apache is loopback-bound with a private temporary configuration; the CLI
remains loopback-bound, proxy trust is limited to `127.0.0.1/32`, and both
processes/configuration are removed on exit. This does not validate production
TLS, cloud ingress, or a user's network policy.

## First-run ASGI-to-persistence path — focused integration test design

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| BOOT-FLOW-01 (P1) | Production first-run composition does not carry a real initialize command through its injected authorities | ASGI + temporary SQLite integration | With explicit one-time setup authorization and a disposable local SQLite target, POST initialize returns a completed safe receipt, a fresh bootstrap read reports initialized, and a grant-bound operation read returns the original receipt |
| BOOT-FLOW-02 (P1) | Initialization leaves secrets or remains repeatable after setup closes | Persisted-state/API integration | No submitted credentials/code appears in response or deployment state files; the target DB stores only password hash/encrypted source secret; after completion setup authorization is closed and no second initialize can create another admin |
| BOOT-FLOW-03 (P1) | The installed deployment entry point cannot complete its real first-run lifecycle against a production SQL dialect | Installed wheel + CLI + HTTP + disposable MySQL/PostgreSQL | Install the built wheel in an isolated environment; explicitly open the setup window via the packaged CLI; exchange the one-time operator code over HTTP; initialize through the deployed endpoint; verify the durable receipt, initialized guard, admin/source/audit rows and closed window; reject a second initialization. MySQL evidence: §15.987; PostgreSQL parity: §15.991. |
| BOOT-DEPLOY-01 (P1) | Two service workers concurrently migrate an empty configured database during startup | Two independent SQL engines/processes + disposable production dialect | Start both migrations against the same empty schema; both calls must complete, the Alembic revision must be at head, and no table/column race or indefinite metadata-lock wait may remain |

The test uses the actual first-run ASGI composition, setup-window/grant file
authorities, cross-store coordinator, migrations, initialization transaction,
and real isolated SQLite file. Only the selected PostgreSQL network engine is
replaced at its factory seam with that disposable SQLite engine, so this is not
PostgreSQL/MySQL TLS, migration, locking, or production-driver evidence. Test
data is synthetic and removed with its temporary directory.

BOOT-FLOW-03 is a separate opt-in installed-wheel acceptance using the disposable
MySQL/Consul harness. It exercises the executable and live HTTP lifecycle against
the same temporary TLS MySQL database used by the installed service; the Consul
source is a synthetic uncredentialed registration and is not contacted. It does
not claim Kubernetes/shared-volume, real ingress/proxy, browser, or final
React-to-Python E2E coverage.

## Focused verification

- Bootstrap file-authority + authorize/source-check/database-check + bootstrap
  read + cross-store coordinator focused tests: **32 passed**.
- Coverage includes strict input, origin rejection before authority, grant
  cookie flags/expiry, finite rejection mapping, fail-closed missing/unavailable
  authority, CSRF rejection before authority, one-time consumption, shared
  local-file retry limit, two concurrent authority objects, code rotation,
  grant expiry, restart verification and secret non-disclosure. One test runs
  the file adapter through the actual ASGI authorize route.
- The concurrency case uses two authority objects and local POSIX file locks,
  not separate OS processes or hosts. The explicit composition smoke test
  asserts app routes and verifies app construction does not create authority
  state files; it does not start ASGI lifespan or connect to a database.
- The setup-window store now also has an independent `spawn`-process CAS test:
  two OS processes use the same local record and revision, with exactly one
  update and one conflict. This proves local process-level flock/CAS behavior
  on the test filesystem only; it is not a shared-volume, NFS, multi-host,
  Kubernetes replica, or production mount acceptance.
- Current grouped focused run: **56 passed**, including composition, lazy
  provider, login limiter, bootstrap APIs/coordinator and lifecycle checks.
  No real setup secret, remote database, browser E2E or full Console suite was
  used. B0.1/B0.2 remain open.
- `test_identity_composition`: **5 passed**, including explicit bootstrap
  configuration producing one shared authorization/verifier adapter for the
  ASGI assembly.

## First-run HTTP-to-persistence integration evidence (2026-10-09)

- Added `tests/test_first_run_http_persistence_integration.py` using the actual
  `build_first_run_sql_identity_app`, deployment-owned setup-window and
  bootstrap-grant file adapters, cross-store initialization coordinator,
  migrations, initialization transaction, and a disposable file-backed SQLite
  database. The test exchanges a synthetic operator code, posts the typed
  initialize contract with CSRF/idempotency, reads the completed operation
  receipt, then reads bootstrap again to verify setup is closed.
- Persisted assertions verify one guard marked initialized, one built-in
  account, one initialization receipt and one registered source; the admin
  password is stored as a hash and the Consul ACL token as encrypted payload.
  API responses and runtime/operator state files are checked for secret
  disclosure. Reauthorization and a repeated initialize after setup closure
  are rejected, leaving the persisted account/receipt counts unchanged.
- Verification: eight focused first-run/bootstrap modules — **42 passed**;
  `python -m compileall -q src/atlas_richie/sentinel_console tests/test_first_run_http_persistence_integration.py`
  passed.
- Boundary: to avoid opening a database socket, only the configured PostgreSQL
  engine factory/read-back seam is replaced with a real isolated SQLite engine;
  the actual migrations, SQL transaction and ASGI routes remain real. This is
  not PostgreSQL/MySQL driver/TLS/migration/locking evidence, browser-to-Python
  evidence, Nacos/Consul reachability, or final E2E. B0.2 remains open.

## Current workspace focused verification (2026-10-11)

- `uv run --project . --extra test pytest -q tests/test_login_api.py tests/test_logout_api.py tests/test_own_password.py tests/test_bootstrap_initialization_api.py tests/test_first_run_http_persistence_integration.py`: **41 passed** in 11.81s. These are the focused identity/bootstrap modules against their configured test authorities and isolated test database; this run did not start MySQL or Consul.
- Frontend `npm run test:logic:focused -- 'F4[.]20|F4[.]21|F4[.]22|F4[.]24|F4[.]26|F4[.]28|F4[.]29|F4[.]30|F4[.]31|F4[.]32|F4[.]33'`: **12 passed**. This is workflow logic evidence only, not mounted browser or live Python integration.
- No defect was exposed by these focused runs. Both implementation areas remain open for their outstanding mounted-browser, real-service, deployment and final E2E acceptance; no containers were created in this verification.

## Installed wheel first-run lifecycle (2026-10-13)

- Extended `tests/test_installed_cli_bootstrap_acceptance.py` with BOOT-FLOW-03:
  build/install the wheel into an isolated environment, start the installed
  `sentinel-console serve`, explicitly open setup through the installed CLI,
  exchange the operator code over HTTP with Origin/CSRF proof, initialize the
  first admin and an uncredentialed Consul source against the disposable TLS
  MySQL database, read the exact durable operation receipt, verify the
  initialized bootstrap projection and SQL guard/admin/source/operation/audit
  rows, reject a second initialize, and confirm the CLI reports setup closed.
- Verification: the project disposable dependency runner started MySQL 8.4.11
  and Consul 1.21.1; the installed-wheel acceptance passed **1/1**. Both exact
  run-named containers were absent after runner exit. SQL assertions verified
  the active built-in admin uses a password hash, the uncredentialed source has
  no credential payload, and temporary locator/operator/setup files contain
  none of the submitted database/admin/operator secrets. Ruff check/format and
  `git diff --check` passed.
- Boundary: this is installed Console CLI + real HTTP + temporary MySQL
  backend acceptance with two Uvicorn workers, not a browser test. The
  uncredentialed Consul endpoint is stored but not contacted. PostgreSQL
  installed-wheel parity was subsequently verified in §15.991 using TLS
  PostgreSQL 16.10 and the same isolated CLI/HTTP lifecycle. Shared Kubernetes
  volume/ingress, secret delivery, React-to-Python mounted flows, and final E2E
  remain open. B0.2 remains open.

## PostgreSQL/MySQL startup migration locks across workers (2026-10-13)

- A real empty-schema run with two independent worker engines reproduced a
  duplicate-table race during Alembic startup. The lock query opened an implicit
  SQLAlchemy transaction before Alembic began; startup now commits that
  transaction after acquiring the MySQL session lock and before running DDL.
  The named lock remains held on its owning connection until Alembic finishes
  and the explicit release succeeds.
- Added a live MySQL check that the generated migration lock is exclusive across
  distinct server connections, plus a concurrent fresh-schema migration test.
- Verification: MySQL 8.4.11 disposable acceptance **2 passed**; installed
  wheel → CLI → HTTP first-run acceptance with two Uvicorn workers **1 passed**.
  Disposable PostgreSQL 16.10 concurrent fresh-schema migration across two
  independent SQLAlchemy engines **1 passed**.
  The disposable runner removed its exact MySQL and Consul containers after
  exit. Focused SQLite/ASGI lifecycle and persistence tests plus static checks
  are recorded in the implementation handoff.
- The PostgreSQL runner uses a separate random container name/owner label,
  database and credentials, publishes only to a loopback ephemeral port, mounts
  no persistent volume, and removes only the exact run-owned container on exit.
- Boundary: PostgreSQL evidence covers dual-engine schema migration, not its
  installed-wheel first-run path. Shared Kubernetes storage/ingress, deployment
  secret delivery, browser-to-Python interaction, and final E2E remain open.
  B0.2 remains open.

## PostgreSQL TLS first-run and multi-worker runtime (2026-10-13)

- The disposable PostgreSQL runner now creates a short-lived CA and server
  certificate, enables PostgreSQL TLS, exposes only a loopback ephemeral port,
  and removes both its owner-labeled container and temporary certificate files
  on exit. It exports the root CA and local test endpoint only to the child
  process.
- The PostgreSQL bootstrap connector now classifies a password rejection
  returned by psycopg/libpq during connection setup even when libpq exposes no
  SQLSTATE. The finite internal classifier uses a bounded diagnostic marker;
  raw driver text remains absent from the HTTP response and logs.
- Acceptance: the focused connector tests, PostgreSQL dual-engine migration,
  the formal CLI with two Uvicorn workers (TLS runtime activation and shared
  login cooldown), and first-run HTTP initialize/receipt/closed-gate/restart
  readback passed together: **17 passed**. Ruff, formatting, shell syntax, and
  `git diff --check` passed. The exact disposable PostgreSQL container and
  temporary CA/private key were removed after the run.
- The first-run test harness now patches the runtime engine factory at the
  composition boundary before the factory is captured. PostgreSQL acceptance
  cases also reset their shared disposable schema before each test. These fix
  test isolation/assembly; they do not replace a production path.
- Boundary: this validates source checkout CLI + real PostgreSQL TLS/HTTP, not
  installed-wheel PostgreSQL bootstrap, production Secret Manager delivery,
  shared Kubernetes storage/ingress, browser-to-Python flows, or final E2E.
  B0.2 remains open.

## Installed-wheel PostgreSQL bootstrap (2026-10-13)

- Extended the installed Console wheel acceptance to run against either
  PostgreSQL or MySQL. Driver extras are mapped from the database dialect
  (`postgresql` → package extra `postgres`), while the first-run wire kind stays
  `postgresql`. The PostgreSQL path uses the disposable TLS server and root CA,
  installs the built wheel into a clean virtual environment, starts the formal
  CLI with two workers, and runs migrations plus the first-run HTTP and SQL
  persistence assertions.
- Verification: PostgreSQL 16.10 installed-wheel first-run **1 passed**. The
  refactored MySQL 8.4.11 + Consul 1.21.1 installed-wheel workflow also passed
  **1/1**. Exact run-owned containers were removed after both commands.
- Boundary: these are backend package/CLI/HTTP acceptance tests, not React
  browser E2E, Kubernetes shared-volume/ingress, multi-host startup, production
  secret-manager delivery, or full B0.2 closure. B0.2 remains open.

## Disposable Kubernetes shared-volume lock acceptance (2026-10-13)

- The guarded runner `bash tools/accept_local_kubernetes_shared_volume.sh`
  refuses non-`docker-desktop` contexts and clusters with other than one node.
  It creates a uniquely named namespace, a temporary `ReadWriteOnce` PVC using
  Docker Desktop's `hostpath` StorageClass, a ConfigMap containing the actual
  production `LocalAtomicFileStore` module, two indexed Python worker Pods, and
  one verifier Pod.
- The first Pod holds the store's actual sidecar `flock`; the second Pod starts
  a CAS while that lock is held. The verifier requires the contender to block
  at least 500 ms, exactly one `stored` outcome and one `conflict`, and the
  persisted record to match the winner. Observed result: contender waited
  **1011 ms**, outcomes were `[conflict, stored]`, and the verified winner was
  `pod-1`. The disposable namespace, Pods, ConfigMap, PVC, and provisioned PV
  were absent after runner exit.
- Worker source: `tests/kubernetes_shared_volume_worker.py`; orchestration:
  `tools/accept_local_kubernetes_shared_volume.sh`. `bash -n` and Python
  `compileall` passed before launch. Ruff is not installed in this environment.
- Boundary: this is concrete evidence for two Pods on the single-node local
  Docker Desktop `hostpath` implementation only. It does not prove NFS/RWX,
  multi-node/cloud CSI locking, Console ingress/proxy behavior, or production
  Secret Manager delivery. Those remain open; B0.2 and final B0.5 stay open.
