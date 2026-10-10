# B0.2 — Bootstrap authorization HTTP slice

Status: **HTTP contract, local authorities and explicit first-run ASGI composition implemented; executable deployment launcher and deployment acceptance remain open**.

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

## First-run ASGI-to-persistence path — focused integration test design

| ID | Risk | Layer | Required assertion |
| --- | --- | --- | --- |
| BOOT-FLOW-01 (P1) | Production first-run composition does not carry a real initialize command through its injected authorities | ASGI + temporary SQLite integration | With explicit one-time setup authorization and a disposable local SQLite target, POST initialize returns a completed safe receipt, a fresh bootstrap read reports initialized, and a grant-bound operation read returns the original receipt |
| BOOT-FLOW-02 (P1) | Initialization leaves secrets or remains repeatable after setup closes | Persisted-state/API integration | No submitted credentials/code appears in response or deployment state files; the target DB stores only password hash/encrypted source secret; after completion setup authorization is closed and no second initialize can create another admin |

The test uses the actual first-run ASGI composition, setup-window/grant file
authorities, cross-store coordinator, migrations, initialization transaction,
and real isolated SQLite file. Only the selected PostgreSQL network engine is
replaced at its factory seam with that disposable SQLite engine, so this is not
PostgreSQL/MySQL TLS, migration, locking, or production-driver evidence. Test
data is synthetic and removed with its temporary directory.

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
