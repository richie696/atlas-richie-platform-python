# T05.3 Monitoring Source API delta proposal

Status: **PARTIALLY IMPLEMENTED — additive API 0.11.0/0.12.0/0.13.0 slices and API 0.18.0 source-reference rejection are frozen and wired; real Prometheus history/query acceptance and SQL dialect matrix remain open.**
Console API 0.8.0 and the already frozen 0.9.0/0.10.0 operations remain
unchanged. Version 0.10.0 is reserved for loopback-only bootstrap
authorization; this proposal therefore targets 0.11.0. The product owner has
delegated implementation choices to the documented recommended defaults in
`R-DASHBOARD-single-node-install-runtime-monitoring-e2e-plan.md`. As of
2026-10-17, the bounded candidate check and exact-session receipt read are
implemented in 0.11.0; safe directory/detail reads in 0.12.0; and source
create/update/set-enabled/delete commands plus same-session operation readback
in 0.13.0. API 0.18.0 adds the durable `source_in_use` delete outcome when a
persisted host association still references a monitoring source. The frozen
OpenAPI snapshots and backend/React HTTP contracts are the wire authority.
These implementation slices do not establish real
Prometheus time-series/history rendering, SQLite/PostgreSQL/MySQL parity, or
browser/live-service E2E acceptance.

The product/test basis is [T05.3 monitoring source acceptance design](R-DASHBOARD-T05.3-monitoring-source.md)
and UI-S01/S02 in `DASHBOARD_INTEGRATION_DESIGN.md`.

## 1. Resource boundary

Monitoring sources are not Nacos/Consul rule sources. They are independent
Console SQL records that describe how to query a Prometheus-compatible backend
and map its observed label sets to Sentinel environment/host identities. The
Console never stores time series. The Sentinel Runtime Collector URL is not a
monitoring query URL and cannot be substituted for it.

Proposed finite provider/profile identifiers:

| Identifier | Meaning |
|---|---|
| `prometheus-compatible` | Read-only Prometheus HTTP API query backend; no vendor-specific API is implied |
| `node-exporter-v1` | Candidate host metric profile; exact metric names/units must be frozen with T05.4 before production use |

The profile identifier is a proposal, not evidence that a target currently has
the profile's required samples.

## 2. Proposed HTTP operations

All paths are additive under `/api/v2/monitoring/sources`; none modifies the
frozen `/api/v1/system/sources` or Console API 0.8.0 rule-source union.

| Operation | Access | Behavior |
|---|---|---|
| `GET /api/v2/monitoring/sources` | authenticated `admin` and `view` | Bounded safe directory: id, revision, display name, environment, provider/profile, enabled, auth mode/configured, finite latest connection/sample status and timestamp. No endpoint, user info, credential, credential reference, SQL ciphertext, raw PromQL, or exception text. |
| `GET /api/v2/monitoring/sources/{sourceId}` | `admin` only | Configuration detail; base URL is sanitized/redacted, mapping/profile/scope are readable, direct secrets and reference values are absent. |
| `POST /api/v2/monitoring/sources/check` | `admin` + exact Origin + CSRF | Read-only candidate probe; does not create/update the source, alter Prometheus, or change the registered-source revision. It records only a short-lived, secret-free check receipt in Console SQL so a later save can bind to exactly the checked candidate. |
| `POST /api/v2/monitoring/sources/commands` | `admin` + exact Origin + CSRF + idempotency | Create/update/set-enabled/delete command; update/delete/set-enabled require `expectedRevision`. Secrets are write-only. Create/update may explicitly skip the check and save as unverified; otherwise the receipt must belong to the same actor/session, be unexpired, and match the canonical non-secret candidate fingerprint. Set-enabled is a minimal CAS command and does not require resending source configuration or credentials. |
| `GET /api/v2/monitoring/sources/operations/{requestKey}` | authenticated initiating `admin` session | Read the original command receipt; no secret or provider payload is returned. A missing/unknown outcome is checked using the same request key; clients must not invent a new key to retry an ambiguous command. |

List is bounded and sorted by stable `(environmentId, displayName, sourceId)`;
unknown/duplicate query parameters reject. Pagination shape and maximum are to
match the project's current Console strict DTO conventions when frozen. Read
responses use `Cache-Control: no-store` and `Vary: Cookie`.

## 3. Candidate and persisted configuration

Proposed configuration fields (wire casing is camelCase):

| Field | Rule |
|---|---|
| `displayName` | Required bounded operator label; not a provider or host identity |
| `endpoint` | Required URL base. HTTPS is the default and is mandatory when any credential is configured. Plain HTTP is allowed only when the deployment explicitly enables `allow_private_http_monitoring` and configures a destination CIDR/port allowlist, the target resolves exclusively inside that allowlist, and authentication is `none`; loopback HTTP is limited to explicit local acceptance. Reject URL user-info, query/fragment, redirects, loopback/link-local/metadata/multicast/unspecified ranges, and mixed allowed/disallowed DNS answers. Pin the validated resolution for each request to prevent DNS rebinding. No browser-provided CA file or certificate bypass. |
| `authentication` | Strict discriminated union: `none`, `direct-basic`, `direct-bearer`, `credential-reference`, or update-only `keep`; direct values and reference IDs are write-only and excluded from every response/log/receipt. `keep` requires exact current source id/revision. |
| `tlsTrust` | `system` by default or deployment-owned `caReference`; never a `verify=false` option. |
| `environmentId` | Explicit bounded identity; never inferred from endpoint or host labels |
| `profileId` | Finite supported profile, initially the proposed `node-exporter-v1`; unsupported profiles fail closed |
| `identityLabels` | Ordered, unique, profile-validated non-empty label-name tuple used to form a stable host identity |
| `selectorLabels` | Bounded list of exact key/value selectors; not arbitrary PromQL or regex |
| `scrapeIntervalSeconds` | Explicit measured/source-owned scrape cadence, distinct from browser refresh frequency |
| `staleAfterSeconds` | Explicit freshness policy; must exceed the configured scrape interval and stay inside frozen bounds |

These fields are **candidates only**. Metric profile required metrics, identity
label requirements, numeric bounds, stable sanitization of endpoint path, and
whether label selectors permit regex remain approval items. Do not invent
defaults in the UI. If a field is not available from a selected profile, show
unknown/unavailable instead of a guessed value.

## 4. Probe result and check receipt

Candidate check response is an immutable sanitized fact bound to a canonical
fingerprint of every non-secret input plus the current source revision (for an
edit). It contains:

- random `checkId`, `candidateFingerprint`, `checkedAt`, and `expiresAt`;
- finite connection result: `reachable` / `unreachable` and finite reason;
- query API capability: `available` / `denied` / `unsupported` / `unknown`;
- profile result: `supported` / `missing_samples` / `unsupported` / `unknown`;
- identity preview counts: bounded `observed`, `unique`, `missing`, and
  `conflicting` counts; never an unbounded label-value dump;
- result `verified` only if endpoint, query permission, profile samples, and
  identity mapping each pass. A reachable API with no samples is not verified.

The receipt table is short-lived, contains no endpoint or secrets, is owned by
the initiating session/account, and is consumed only when the command's
candidate fingerprint and expected revision match exactly. Candidate check
does not persist source metadata or mutate Prometheus. Any edit causes the UI
to discard the old `checkId`. Expired/mismatched receipts produce a finite
`check_expired` or `check_mismatch` rejection; the operator can explicitly
recheck or save unverified.

## 5. Command shape and state semantics

Frozen command discriminant values: `create`, `update`, `set-enabled`,
`delete`. All commands carry a unique `requestKey`; `Idempotency-Key` equals
`requestKey` exactly. `update`/`set-enabled`/`delete` include
`sourceId`+`expectedRevision`; create does not. `set-enabled` carries only
`sourceId`, `expectedRevision`, and the desired boolean, preserving encrypted
credentials and all non-enable configuration. State change increments the
source revision atomically with its audit/receipt. Disabling prevents new
monitoring queries but preserves source history/audit. `delete` is rejected
when a persisted monitoring view/query references it; no implicit cascade.

Command response contains only `requestKey`, finite operation status, stable
error code if rejected, timestamps, and an allowlisted safe source summary.
Cross-kind reuse of an idempotency key with different input rejects as
`idempotency_conflict`; stale revisions reject as `conflict`; active references
reject as `source_in_use`. On an ambiguous timeout, clients poll the original
operation key, never replay with a new key.

## 6. Error and privacy candidates

| HTTP | Stable code | Meaning |
|---|---|---|
| 400 | `invalid_request` | Strict schema, URL, profile, labels, or bounds invalid |
| 401 / 403 | `unauthenticated` / `forbidden` | Session/role/Origin/CSRF rejection |
| 404 | `not_found` | Source/operation absent within caller's permitted scope |
| 409 | `conflict`, `source_in_use`, `idempotency_conflict`, `check_mismatch`, `check_expired` | Stable command/read conflict |
| 413 | `request_too_large` | Body bound exceeded |
| 429 | `rate_limited` + bounded `retryAfterMs` | Check or command throttling |
| 503 | `service_unavailable` | SQL/persistence or required safe adapter unavailable |

Prometheus API failures map to a finite check result only when the probe itself
completed authoritatively; Console SQL or adapter failure returns 503. Raw
provider body, URL, PromQL, exception text, credentials, certificate material,
and response labels are not returned or logged. Audit records source identity,
actor, operation, revision transition, and finite outcome only.

## 7. SQL and composition candidates

Console SQL owns source metadata, encrypted direct credentials/reference handle,
revision, enabled state, identity mapping, candidate-check receipt, last
registered-source probe, operation idempotency receipt, and audit. Prometheus
retains all time-series data. Mappings should use bounded normalized rows or a
strict typed encoding with dialect tests; no unconstrained `dict[str, object]`
is a public/domain contract. SQLite/PostgreSQL/MySQL must share one application
contract suite and dialect-specific migrations/indexes.

The application owns the monitoring-source/check consumer contract. The
Prometheus HTTP Adapter owns URL path/query construction, authorization,
timeouts, redirect policy, finite response parsing, label/sample capability
mapping, and error normalization. SQL persistence owns durable metadata. The
API route owns wire validation/authentication/response mapping. This proposal
does not add a second database abstraction or couple monitoring facts to the
existing Nacos/Consul source store.

## 8. Freeze decisions and remaining acceptance

1. **Frozen/implemented:** Adapter remains an internal infrastructure boundary;
   the application owns monitoring source/probe Ports. React consumes only the
   versioned Console API.
2. **Frozen/implemented:** check/receipt uses 0.11.0, safe directory/detail
   reads use 0.12.0, and management commands/readback use 0.13.0. Prior
   snapshots are immutable.
3. **Frozen/implemented:** `admin` manages/checks and reads detail; `admin` and
   `view` may read the safe directory; mutation and detail remain forbidden to
   `view`.
4. **Implemented slice:** authentication is write-only and deployment-resolved
   for references; TLS uses deployment-owned trust. Production credentials and
   resolver boot configuration still require final E2E.
5. **Still open under T05.4:** production profile queries/metric meaning,
   freshness, identity-label behavior, aggregation/conflict rules, and durable
   historical query semantics.
6. **Frozen/implemented:** session-bound check receipts, idempotency key equal
   to `requestKey`, revision CAS, safe operation readback, and atomic
   source/receipt/audit writes. Cross-dialect and multi-worker acceptance is
   still open.
7. **Implemented:** finite command rejection codes and unknown-outcome recovery
   by polling the original request key; the frontend does not invent a new key
   for an ambiguous result.
8. **Implemented:** runtime DTOs, three immutable OpenAPI versions, strict
   Python validation, React wire contracts, and HTTP Mock behavior have focused
   contract tests. These checks do not imply real Prometheus, SQL-dialect, or
   browser acceptance.
