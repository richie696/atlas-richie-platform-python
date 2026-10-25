# B0.1 — Registered configuration-source check HTTP slice

Status: **admin/CSRF contract and bounded read-only Nacos/Consul checker implemented; disposable-provider acceptance is partial, production deployment acceptance remains open**.

## Contract and boundary

Implements `POST /api/v1/system/sources/check`. The route requires a valid
browser session, admin role, exact allowlisted Origin and double-submit CSRF
proof before invoking the injected `RegisteredSourceChecker`. Request parsing
is strict for Nacos/Consul provider, endpoint, namespace/datacenter,
authentication mode, source identity and expected revision. Existing
credentials may be retained only with both source ID and expected revision;
the checker receives this optimistic-concurrency context and owns secret
resolution and stale-revision rejection.

The application contract suppresses direct credentials and references from
repr/equality and requires provider-specific direct-auth fields. Responses
contain only bounded capability/reason enums and short-lived UTC check times.
The route does not register/update a source or publish a rule. A missing or
unavailable checker returns 503; rate limiting maps to 429.

`RegisteredSourceTargetPolicy` additionally requires an explicit provider +
hostname + port + CIDR deployment grant, resolves DNS once, rejects any
unapproved answer, and pins the accepted address set into the HTTP resolver.
The HTTP transport does not inherit proxy settings, follows no redirects,
verifies TLS identity, bounds response size and request time, and requires HTTPS
for authenticated requests. Nacos uses the Nacos 3 Admin API to authenticate
direct username/password credentials and perform a read-only namespace config
list. Consul uses a read-only KV key-list request with a short blocking query;
it reports WATCH only when the response includes `X-Consul-Index`. Neither
adapter publishes configuration or claims conditional-write capability.
Opaque credential references resolve only through an explicitly injected
deployment-owned `SourceCredentialReferenceResolver` Port. The application
resolves a reference before invoking the provider checker, verifies the
resolved provider/credential shape, and converts the ephemeral result into the
existing direct-auth input. A missing resolver, missing reference, resolver
failure, or provider mismatch fails closed as checker unavailability; it must
never retry anonymously. The core does not choose KMS, Kubernetes Secrets,
environment variables, or a particular vault, and never persists or returns
resolved secret material. The stored-credential `KEEP` resolver remains a
separate exact-source-revision path.

Deployment wiring is available through
`build_sql_identity_app(registered_source_target_rules=...)` plus explicit
bootstrap checker and credential-reference resolver injection, or by injecting
the checker/resolver directly into `build_app`. No default allowlist is
created. This code has not contacted a real
Nacos/Consul deployment; actual provider version/auth/ACL behavior and
production allowlist configuration remain a milestone acceptance boundary.

## Focused test matrix

| Risk | Evidence | Expected proof |
| --- | --- | --- |
| DNS rebinding / mixed answers | Target-policy unit test | Every resolved address must match an explicit provider/host/port CIDR grant; one denied address rejects the target. |
| Explicit invalid port | Target-policy unit test | An omitted port uses the scheme default, but an explicitly supplied port `0` remains invalid and cannot be normalized to the default allowlisted port. |
| Credential transport safety | Target-policy + adapter tests | Authenticated HTTP is rejected; credentials are absent from repr; provider secrets are sent only in provider-required request fields/headers. |
| External credential references | Application service tests | References are resolved before a provider probe; Nacos/Consul credential shape is enforced; missing/failing/mismatched resolution fails closed without invoking checker; direct/none/keep paths retain their contracts. |
| Nacos read-only behavior | Adapter test with controlled request seam | Login then GET config-list; no mutating HTTP method is invoked; only READ is reported. |
| Consul read/watch behavior | Adapter test with controlled request seam | KV keys request uses GET; READ is reported and WATCH requires `X-Consul-Index`. |
| Actual HTTP client composition | Local loopback integration test | Exercise `PinnedAioHttpJsonClient` against a synthetic `127.0.0.1` server; preserve the `/nacos` context path and prove a provider redirect is not followed. |
| Pinned resolver enforcement | Resolver unit test | Only previously policy-approved addresses are returned; host/port mismatch errors. |
| Real provider compatibility | Deferred milestone acceptance | Nacos 3 and Consul controlled environments, valid/invalid auth and ACL outcomes; no production credentials or data. |

Focused validation: source-reference application tests,
`tests/test_registered_source_checker.py` plus the existing source-check
API/store integration tests. No full Console suite or browser E2E is run for
this slice.

## Focused verification

- External-reference application/API/checker/SQL-composition suites: **31 passed**. This proves
  ordering, provider-shape validation, redacted fail-closed outcomes and
  both first-run and registered-source check flows with a test resolver; it
  does not prove a deployment secret manager implementation.
- Registered-source check, account-command, and bootstrap connectivity/auth
  ASGI suites: **27 passed**.
- Covered anonymous/view denial, CSRF/Origin rejection before connector,
  strict payload and source revision pairing, direct-secret non-disclosure,
  typed check result/error mapping, rate limit and absent/unavailable checker.
- Regression added for `http://nacos.internal:0`: endpoint parsing now
  distinguishes an omitted port from explicit zero, so the target policy rejects
  the invalid port instead of treating it as the HTTP default. The focused
  `tests/test_registered_source_checker.py` suite passes **10 tests**.
- Current `tests.test_registered_source_checker` suite: **12 passed**, including
  two real loopback HTTP transport tests. Nacos exercised the actual `aiohttp`
  client through an allowlisted literal loopback target with a `/nacos` context
  path; Consul returned a redirect and the test proved it was not followed. The
  earlier 10-test result above is historical.
- The changed Python module/tests passed `compileall`; the recorded API suites
  and OpenAPI contract checks above are from the earlier focused verification.
  `git diff --check` passed for tracked changes.
- No full Console suite, real Nacos/Consul, database, or browser E2E was run.
  Loopback servers are controlled test doubles, not provider-compatibility
  acceptance. B0.1/B0.3 remain open.

## 2026-10-09 follow-up — Consul 401 classification

The earlier 12-test result above is historical and predates the Consul 401
regression. The checker now classifies both HTTP 401 and 403 as
`authentication`; the focused provider-checker cases passed **6 tests**, and
the full source-check file excluding the loopback integration class passed
**11 tests**. `compileall` and `git diff --check` passed.

A fresh attempt to run the complete source-check file could not bind the two
loopback servers because this sandbox denies `127.0.0.1` binds
(`PermissionError: Operation not permitted`). Therefore this run is **not** a
13-test pass and does not re-verify the real-client loopback cases. No elevated
permission was requested. Real Nacos/Consul, TLS/ACL compatibility, and B0.1
acceptance remain open.

## 2026-10-09 follow-up — Nacos authentication endpoint failures

Added a regression for Nacos login endpoint responses 429, 500, 502 and 503.
The pre-fix behavior incorrectly classified these responses as invalid
credentials because no access token was present. The checker now maps only
401/403 to `authentication`, maps other non-200 statuses to `connection`, and
keeps the explicit empty-token response classified as `authentication`.
Focused Nacos/Consul auth and outage cases passed **4 tests**; the complete
source-check file excluding the sandbox-blocked loopback class passed **12
tests**. `compileall` and `git diff --check` passed. The loopback restriction,
real provider/TLS/ACL compatibility, and overall B0.1 acceptance remain open.

## 2026-10-09 follow-up — Reject HTTP header control characters in tokens

The Nacos access token is forwarded in the `accessToken` request header and a
Consul ACL token is forwarded in `X-Consul-Token`. Neither adapter previously
rejected control characters before forwarding those values. Added regressions
first failed against the old implementation: Nacos attempted the second
request with an injected header value, and Consul incorrectly reported a
reachable source. The checker now classifies a malformed Nacos response token
as `authentication` and rejects a malformed Consul ACL token as `unsupported`
without issuing the provider request.

From `components/sentinel/sentinel-console/`:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_source_checker.py tests/test_registered_source_check_api.py tests/test_bootstrap_registered_source_checker.py tests/test_bootstrap_source_check_api.py -k 'not Loopback'
```

The command passed **30 tests**; **2 loopback cases were deselected** because
the sandbox does not permit local listener binding. `python -m compileall`
passed for the changed module and test. No real Nacos/Consul, TLS/ACL, database,
or browser E2E was involved. B0.1 remains open.

## Installed-wheel Nacos auth acceptance (2026-10-13)

The next deployment-level slice exercises the same trust boundary through the
installed `sentinel-console` CLI rather than an in-process checker composition:

| Risk | Acceptance proof |
| --- | --- |
| First-run setup accepts a Nacos endpoint but the installed service cannot resolve it after restart | Build/install the current Console wheel, start the standard two-worker CLI from no runtime locator, initialize against disposable auth-enabled Nacos 3.2.4 over a loopback HTTPS proxy with an explicitly provisioned CA, and verify the exact Nacos endpoint remains usable after initialization. **Passed.** |
| Direct source credentials are not protected through SQL or exposed on read | Inspect the SQL registered-source row for encrypted credential payload; source directory, initialization receipt, connection status, CLI log, and runtime files must not contain the synthetic password. **Passed.** |
| A wrong credential or stored-credential check silently succeeds | Submit an invalid direct Nacos password and require `unreachable/authentication` without changing the registered source's unknown state; then use `authentication.mode=keep` and require reachable/read capability plus persisted `available` state. **Passed.** |

Only disposable MySQL/Nacos services and synthetic credentials are allowed. The
test-owned Nacos proxy certificate must include loopback IP SAN so standard CLI
DNS/target-policy code is exercised without modifying host resolver state. This
acceptance proves the local installed deployment path, not a production Nacos
cluster, external Secret Manager, native Nacos TLS listener, or browser E2E.
The installed-wheel path is run independently against disposable MySQL and
PostgreSQL databases so SQL dialect parity is observed without sharing a
database between acceptance cases.

Command (from the repository root):

```bash
SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE=1 \
SENTINEL_CONSOLE_RUN_INSTALLED_NACOS_AUTH_ACCEPTANCE=1 \
SENTINEL_CONSOLE_RUN_APACHE_PROXY_ACCEPTANCE=0 \
components/sentinel/sentinel-console/tools/with_disposable_e2e_dependencies.sh \
uv run --project components/sentinel/sentinel-console --extra test --extra mysql \
--extra server --extra nacos-grpc pytest -q --tb=short \
components/sentinel/sentinel-console/tests/test_registered_source_nacos_auth_acceptance.py \
-k installed_cli
```

MySQL command result: **1 passed in 29.32s** using disposable MySQL 8.4.11
with TLS and auth-enabled Nacos 3.2.4. PostgreSQL command (same opt-in Nacos
fixture, run with the separate disposable PostgreSQL runner):

```bash
SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE=1 \
SENTINEL_CONSOLE_RUN_INSTALLED_NACOS_POSTGRES_AUTH_ACCEPTANCE=1 \
components/sentinel/sentinel-console/tools/with_disposable_postgresql_acceptance.sh \
uv run --project components/sentinel/sentinel-console --extra test --extra postgres \
--extra server --extra nacos-grpc pytest -q --tb=short \
components/sentinel/sentinel-console/tests/test_registered_source_nacos_auth_acceptance.py \
-k installed_cli_postgresql
```

PostgreSQL result: **1 passed in 26.57s** on disposable TLS PostgreSQL 16 with
`sslmode=verify-full`. The MySQL shared-helper regression rerun passed **1 in
21.38s**. In both dialects the installed CLI ran two workers, began without a
runtime database locator, initialized through the setup HTTP flow, persisted
the source secret as ciphertext, rejected a bad password without changing
probe state, then authenticated with the stored credential and reported
`available`/`read`. Ruff check/format, `compileall`, and `git diff --check`
passed. Owner-run MySQL/Consul/PostgreSQL containers and the test-owned Nacos
container were removed on exit; a post-run name check found no matching
containers.

PostgreSQL installed-CLI/Nacos authentication case re-run on 2026-10-13:
**1 passed in 28.16s** with the isolated PostgreSQL runner. The post-run
container-name check was empty; this refresh confirms only the same local
acceptance slice and does not broaden its deployment or E2E claims.

This is an installed-wheel/local-provider acceptance slice. It does not close
B0.1: user-specific DNS, native TLS, ingress, production target allowlists,
external Secret delivery/rotation, rule publication, and React-to-Python
browser E2E remain unverified.

## Installed-wheel PostgreSQL Consul ACL source-read acceptance (2026-10-13)

The registered-source directory and saved-credential probe path was also
verified through the installed Console wheel on disposable TLS PostgreSQL 16
and a test-owned ACL/TLS Consul server. The test initialized the SQL database
through the two-worker CLI setup flow, authenticated as admin, read the saved
Consul source through `GET /api/v1/system/sources`, and verified provider,
endpoint, authentication mode, revision, and token redaction. It then checked
the exact saved source revision and required a successful Consul read; invalid
credentials were rejected without changing the source's `unknown` state.

Command (from `components/sentinel/sentinel-console/`):

```bash
SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE=1 \
tools/with_disposable_postgresql_acceptance.sh \
uv run --no-sync --extra test --extra postgres pytest -q --tb=short \
tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliConsulAclAcceptanceTests::test_installed_cli_postgresql_reads_and_checks_persisted_acl_source
```

Result: **1 passed in 17.06s**. The PostgreSQL runner and test-owned Consul
server were cleaned up. This complements the MySQL installed-CLI source-list
slice but does not establish production Consul topology/secret delivery or
React-to-Python browser E2E; B0.1 remains open.

## 2026-10-09 follow-up — Strict Nacos JSON success-code validation

The checker previously used Python set membership against `{0, "0"}`. Since
`bool` is a subclass of `int`, a malformed provider response with
`{"code": false}` compared equal to success code `0` and was reported as a
reachable source. A regression first failed against that behavior. The checker
now accepts only an exact integer zero or the documented string form `"0"`;
boolean and other response values map to the stable `connection` failure.

From `components/sentinel/sentinel-console/`:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_source_checker.py -k 'not Loopback'
.venv/bin/python -m compileall -q src/atlas_richie/sentinel_console/infrastructure/registered_source_checker.py tests/test_registered_source_checker.py
```

The regression failed before the fix; afterward the focused source-check suite
passed **16 tests**, with **2 loopback tests deselected**. Compile and
`git diff --check` passed. No provider, database, or browser E2E was run.
B0.1 remains open.

The follow-up was also checked through the registered-source and first-run
source-check HTTP/security paths:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_source_checker.py tests/test_registered_source_check_api.py tests/test_bootstrap_registered_source_checker.py tests/test_bootstrap_source_check_api.py -k 'not Loopback'
```

Result: **32 passed, 2 deselected**. The 25 HTTPX cookie deprecation warnings
are from test setup and are unrelated to the response-code validation.

## 2026-10-09 follow-up — Reject non-ASCII provider header values

The earlier header guard rejected controls but accepted printable Unicode.
That is not a safe guarantee for HTTP header encoding: a malformed Nacos
access token could reach a second request, while a Unicode Consul ACL token
could be reported as reachable by the controlled seam and fail later in the
real transport. New regressions first failed on both paths. The shared guard
now permits only visible ASCII values; Nacos malformed response tokens map to
`authentication`, while malformed submitted Consul tokens map to
`unsupported` before DNS resolution or HTTP.

From `components/sentinel/sentinel-console/`:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_source_checker.py tests/test_registered_source_check_api.py tests/test_bootstrap_registered_source_checker.py tests/test_bootstrap_source_check_api.py -k 'not Loopback'
```

Result: **34 passed, 2 deselected**; 25 existing HTTPX per-request cookie
deprecation warnings. `compileall` and `git diff --check` passed. Real provider
and transport behavior remain unverified; B0.1 remains open.

## 2026-10-10 verification refresh

Re-ran the same controlled source-check boundary from the Console project:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_source_checker.py -k 'not Loopback' tests/test_registered_source_check_api.py tests/test_bootstrap_registered_source_checker.py tests/test_bootstrap_source_check_api.py
```

Result: **34 passed, 2 deselected**. The deselected tests bind local loopback
servers, which this sandbox has previously denied; no external Nacos, Consul,
database, or browser was contacted. The 25 HTTPX cookie deprecation warnings
remain limited to API test setup. This refresh confirms the existing controlled
checker/HTTP paths, not provider compatibility or B0.1 completion.
