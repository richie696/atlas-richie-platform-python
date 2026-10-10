# atlas-richie-sentinel-console

Independent ASGI service for the Sentinel control plane. It is deliberately
separate from `atlas-richie-sentinel-dashboard`, which remains the optional
per-process diagnostics UI/API embedded beside one Sentinel engine.

This package is an implementation in progress. Current vertical slices include
the public bootstrap status, authenticated session and identity commands,
admin-managed registered configuration-source operations, rule workflow HTTP
contracts, operational read contracts, and package-local React assets. Several
registered-source and identity paths have SQLAlchemy persistence adapters
verified with isolated SQLite. It is not yet a production-complete Console or
deployment.

The app composition requires separate initialization-state, deployment
setup-window, and request-scoped operator-session ports; no in-memory production
provider or default administrator is selected implicitly. SQLAlchemy adapters
read the initialized flag, account-directory facts, and login credentials from
the Console database. The login route is registered only when an explicit
`Login` application service is composed. It applies exact Origin and double-
submit CSRF checks, generic credential rejection, opaque cookie rotation, and
hashed session/CSRF persistence. `SqlAlchemyLoginAttemptLimiter` implements the
attempt-limiter Port with shared relational state; its threshold, window, and
block duration must be supplied explicitly. The route also requires a deployment-owned
32-byte HMAC key to derive rate-limit identities. Login rate-limit identity
defaults to the ASGI peer and ignores forwarding headers. Deployments behind a
reverse proxy may inject `ClientAddressResolver.from_cidrs(...)`; only peers in
those strict, non-global CIDRs may supply an `X-Forwarded-For` chain. Proxies
must append each observed peer to the right side of the chain. Invalid chains
fall back to the immediate peer. The package CLI and environment-backed
first-run composition are implemented, but trusted-proxy wiring has not yet been
accepted behind a real ingress. Local limiter integration evidence uses
isolated SQLite only; PostgreSQL/MySQL runtime and multi-worker behavior remain
unverified.

This is not yet a complete Console or production deployment. Explicit first-run
ASGI composition, the `serve`/`setup-window` CLI commands, environment parsing,
and local durable authorities are implemented. Operator secret delivery and
setup-window operation in the deployment, real Nacos/Consul acceptance, rule
write/read-back, PostgreSQL/MySQL concurrency, trusted-proxy ingress acceptance,
and React-to-Python browser E2E remain tracked in the Sentinel Dashboard plan.

## Registered-source key provisioning

The registered-source SQL adapter can be composed with deployment-owned key
rings through `RegisteredSourceKeyConfiguration.from_environment()` and
`compose_registered_source_store(engine, key_configuration)`. It reads:

| Variable | Meaning |
| --- | --- |
| `SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID` | Key ID used for new AES-256-GCM credential envelopes |
| `SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING` | Semicolon-separated `key-id=base64` values; every decoded key must be exactly 32 bytes |
| `SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID` | Key ID used for new idempotency fingerprints |
| `SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING` | Semicolon-separated `key-id=base64` values; every decoded key must be at least 32 bytes |

For rotation, provide the active key and every still-needed prior key in the
corresponding ring; changing the active ID selects the key for new writes while
retained keys remain available for decryption or original-operation recovery.
Supply these values through the deployment's secret injection mechanism (for
example, a Kubernetes Secret), never commit them to application configuration
or logs. Losing an encryption key makes credentials encrypted with that key
unrecoverable. This configuration does not require a KMS. It only configures
the registered-source SQL store; network checking and opaque credential
reference resolution are composed separately through explicit deployment-owned
ports.

## Account-command fingerprint keys

Account mutations use a separate HMAC key ring for idempotency fingerprints.
`AccountCommandKeyConfiguration.from_environment()` reads:

| Variable | Meaning |
| --- | --- |
| `SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_ACTIVE_KEY_ID` | Key ID used to fingerprint new account commands |
| `SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_KEY_RING` | Semicolon-separated `key-id=base64` values; every decoded key must be at least 32 bytes |

Keep each prior key in the ring while an operation receipt may still need to be
replayed; changing the active ID only affects new operations. Inject the values
through the deployment secret manager, never source control or logs. Missing,
malformed, short, duplicate, or unknown-active-key settings fail closed. The
SQL composition is available as `compose_sql_account_commands(engine,
key_configuration)` and is used by `build_sql_identity_app(...)`.

Rule-command mutation uses its own HMAC ring, separate from account and
registered-source keys. `RuleCommandKeyConfiguration.from_environment()` reads
`SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID` and
`SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING`; the latter is a
semicolon-separated `key-id=base64` ring with keys of at least 32 bytes. Keep
all keys needed to replay retained operation receipts. For SQL composition,
provide both this configuration and the deployment-owned exact binding reader
to `build_sql_identity_app(...)`; the builder rejects partial configuration or
mixing these inputs with a separately supplied mutation authority. The Console
does not infer binding facts from request data. `GET /api/v1/rulesets` is
backed by `SqlAlchemyRuleBindingDirectoryReader`, which joins Console-owned
binding metadata with the registered source and exact publication target;
configuration-center rule arrays remain outside the Console database.

Login throttling also pseudonymizes the direct or trusted-proxy client address
with a separate deployment key. `ClientIdentityKeyConfiguration` reads
`SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY` as base64 and requires at least 32
decoded bytes. Keep it stable across workers and restarts; replacing it changes
the HMAC identity for every client and effectively starts fresh throttle
buckets. It is distinct from the account-command fingerprint ring and must also
come from secret injection.

For first-run mode, `build_first_run_sql_identity_app(...)` composes the
explicit setup-window and encrypted locator stores, operator authority,
initialization coordinator, lazy runtime engine, SQL identity routes, and ASGI
lifespan. Its immutable `FirstRunSqlIdentityConfiguration` requires deployment
network policy, TLS trust, key rings, state paths, and exact browser origins;
construction does not open setup or create the state files. The packaged CLI
loads this explicit configuration from the environment for `sentinel-console
serve`; the composition function remains directly available to deployments
that own their application server lifecycle.

Rule-command SQL wiring in first-run mode remains opt-in through the dedicated
rule-command HMAC key ring. The standard first-run composition binds
`SqlAlchemyRuleBindingDirectoryReader` to the same lazy runtime SQL authority
when that key ring is present; a host may override it through
`FirstRunSqlIdentityConfiguration.from_environment(...,
rule_mutation_binding_reader=host_reader)`. Supplying a custom reader without
the key ring fails closed, and a prebuilt mutation authority cannot be mixed
with SQL composition inputs. The reader joins Console-owned binding metadata,
registered-source identity, and the exact publication target; the Console never
infers binding facts from a browser identifier. The standalone `serve` ASGI
composition now includes the admin binding-registration API and SQL authority,
but serving the React UI from the wheel remains a separate packaging gate; rule
publication and activation-plan workers still require explicit deployment
composition and are not implied by enabling the command key ring.

For a database whose schema and first-admin state are already provisioned,
`build_sql_identity_app(...)` composes the SQL identity routes into `build_app`.
When passed `registered_source_keys`, it also wires the SQL registered-source
directory, mutation receipts, credential encryption and `keep`-credential
resolver. The Nacos/Consul checker may be injected directly or composed with
`registered_source_target_rules`; each rule explicitly grants a provider,
hostname, port set and resolved IP CIDR set. The checker pins all DNS answers,
rejects mixed or unapproved answers, disables proxy environment inheritance and
redirects, verifies HTTPS server identity, applies bounded request/response
limits, and performs read-only requests only. An optional verified
`registered_source_ssl_context` can add deployment-owned CA roots without
disabling certificate/hostname checks. Authenticated probes require HTTPS.
Nacos is checked with the Nacos 3 Admin API's namespace config-list read;
Consul is checked with a KV key-list query and blocking-query index. The probe
does not claim conditional-write support, perform a write, or resolve opaque
credential references. Those references remain fail-closed until a deployment
secret-reference resolver is explicitly supplied. The caller still owns engine
lifecycle/migrations and must supply durable setup-window, operator
verification, and bootstrap initialization authorities in this pre-provisioned
mode; it is separate from the first-run composition API and is not a CLI.

## Runtime database URL

For an already provisioned Console database, deployment may provide
`SENTINEL_CONSOLE_DATABASE_URL` as an out-of-band secret. The runtime parser
accepts only `postgresql+psycopg://...` and `mysql+asyncmy://...` URLs with
username, password, host, and database; synchronous drivers and SQLite are
rejected rather than silently selected. `ConsoleDatabaseConfiguration` hides
the URL from its representation and creates an async SQLAlchemy engine with
parameter hiding and pre-ping enabled. Creating the engine does not connect or
run migrations; those lifecycle steps remain owned by the ASGI lifespan or
pre-provisioned deployment caller.

The setup-candidate mapper accepts complete PostgreSQL/MySQL credentials and a
valid port, then creates the corresponding async URL without opening a network
connection. It rejects SQLite and incomplete candidates. DNS pinning and TLS
policy must be applied by the deployment connector before connecting.

The first-run composition writes the encrypted runtime locator only after the
deployment-approved database target is prepared and migrations complete. Its
configuration uses
`SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH`,
`SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID`, and
`SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING`. The path must be an absolute
file inside a deployment-precreated durable writable mount; the independent
AES-256-GCM ring is `key-id=base64;...`, with exactly 32 bytes per key and
retained prior keys during rotation. Locator corruption or key loss fails
closed. The deployment-owned setup-window authority has a separate
`SetupWindowConfiguration`/`SetupWindowFileStore` adapter configured with
`SENTINEL_CONSOLE_SETUP_WINDOW_PATH`. The file lives in a deployment-precreated
local POSIX writable mount; an absent file is closed, an explicit open write is
required, and malformed/unsafe state fails closed. This is a single-host/local
filesystem contract, not an NFS or multi-host guarantee. The package CLI now
loads explicit first-run configuration and provides local setup-window
operations. External operator-grant persistence and filesystem deployment
acceptance remain outstanding; the environment URL remains for pre-provisioned
databases only.

## Development

```bash
uv sync --extra test
uv run pytest
```

Requires Python 3.12 or newer. The Console exposes composition functions that
accept explicit deployment configuration and a packaged deployment CLI; this
does not by itself constitute production database or deployment acceptance.

## First-run service entry point

The package now provides `sentinel-console serve` and `python -m
atlas_richie.sentinel_console serve`. Install the `server` extra for Uvicorn.
The default bind address is loopback (`127.0.0.1:8000`); set
`SENTINEL_CONSOLE_BIND_HOST` and `SENTINEL_CONSOLE_PORT` only when the deployment
intentionally exposes another interface. Uvicorn's implicit proxy-header
rewriting is disabled; `X-Forwarded-For` is interpreted by the app only when the
immediate peer matches `SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS`.

The first-run command requires all existing runtime-locator, setup-window,
operator-authority, account/source key rings, client-identity key, and login
throttle settings documented above, plus:

| Variable | Meaning |
| --- | --- |
| `SENTINEL_CONSOLE_BOOTSTRAP_INITIALIZATION_LOCK_PATH` | Absolute local POSIX path shared by workers for first-run serialization |
| `SENTINEL_CONSOLE_BOOTSTRAP_IDEMPOTENCY_KEY` | Base64 key, at least 32 decoded bytes, separate from all other keys |
| `SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS` | Required allowlist, e.g. `postgresql|10.20.0.0/16|5432;mysql|10.21.0.0/16|3306`; wildcard networks and SQLite are rejected |
| `SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS` | Required provider/hostname/CIDR/port allowlist, e.g. `nacos|nacos.internal|10.30.0.0/16|8848;consul|consul.internal|10.31.0.0/16|8500` |
| `SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE` | Optional absolute PEM CA bundle path for private Nacos/Consul HTTP API trust; peer-certificate and hostname verification remain required |
| `SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS` | Comma-separated exact HTTP(S) origins; paths and wildcard origins are rejected |
| `SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS` | Optional comma-separated private proxy CIDRs; absent means forwarded headers are ignored |
| `SENTINEL_CONSOLE_SESSION_TTL_SECONDS` | Optional positive session duration in seconds; defaults to 28,800 |
| `SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE` | Optional absolute CA bundle path for private PostgreSQL trust roots |
| `SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE` | Optional absolute CA bundle path for private MySQL trust roots; hostname verification remains enabled |
| `SENTINEL_CONSOLE_DASHBOARD_BASE_PATH` | Optional canonical path prefix (for example `/ops/sentinel/`) matching the frontend build; defaults to `/` |

Rule publication remains disabled unless the deployment explicitly selects one
provider and the matching rule profile. To opt in, configure
`SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDER` as `nacos` or `consul` and set
`SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID` to the exact immutable rule
profile used by the Console. This also requires the independent
`SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID` and
`SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING` settings; the selected
provider must have an explicit grant in
`SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS`. The worker reuses the SQL
registered-source store and durable publication outbox. Credential references
are still resolved only through an explicitly injected host resolver; this
environment option does not infer a KMS, provider endpoint, TLS policy, or
credentials. A deployment may run separate Console worker instances for
different providers, but one `serve` process selects at most one provider.
For private HTTPS trust roots used by the Nacos/Consul HTTP APIs, the optional
`SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE` must name an absolute,
readable PEM CA bundle. The Console keeps certificate and hostname validation
enabled and applies this context to registered-source probes and publication
HTTP read/write adapters. It does not configure Nacos gRPC TLS; that transport
has a separate trust/configuration boundary.
When selecting Nacos, install the `nacos-grpc` extra. Omitting the provider
keeps publishing off. These settings only compose the worker; they do not prove
deployed Nacos/Consul acceptance or per-instance rule activation.

Provision the parent directories and local POSIX writable mount before starting;
missing setup-window state is closed and does not get created by `serve`.
Use the local operator command to inspect/change only that state:

```bash
sentinel-console setup-window status
sentinel-console setup-window open
sentinel-console setup-window close
```

`open` requires the deployment operator code and fingerprint key to be present;
the command never prints them. It uses revision compare-and-set, so a
concurrent change fails instead of silently overwriting it. `close` is
idempotent. These commands manage setup availability only; they do not create a
database or account, and local POSIX file locking is not an NFS/multi-host
guarantee. Secret provisioning, operator code delivery to the installer, real
reverse-proxy ingress acceptance, and PostgreSQL/MySQL deployment acceptance
remain separate operational requirements.

## Dashboard assets

The React production build is copied into
`src/atlas_richie/sentinel_console/web/` by the dashboard prototype's
`npm run build:console-assets` command before building the Console wheel.
`uv_build` includes those package-local files in the wheel; the installed
Console serves `/`, `/assets/*`, and client-side GET routes from the same ASGI
application. Vite assets are fingerprinted and receive immutable cache
headers, while the HTML entry is revalidated. Missing `/api` operations remain
JSON 404 responses and never fall through to the app shell.

The default artifact targets an origin root. Set
`SENTINEL_CONSOLE_BASE_PATH=/ops/sentinel/` during the Vite production build to
emit prefixed static asset URLs. When the ASGI app serves that prefix directly,
pass the same value as `build_app(dashboard_base_path=...)`; alternatively, a
reverse proxy may strip the prefix before forwarding UI and asset requests to
the root-mounted Console. In either topology, route `/api/*` to the Console API
and never to the SPA fallback. Runtime launcher/proxy behavior is not yet
accepted. Building or installing this wheel does not mean the Console's
database-backed workflows are complete.
