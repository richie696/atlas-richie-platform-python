# Sentinel Incident Event Protocol V1

Status: **FROZEN V1** (2026-10-15). The project owner/maintainer approved the consolidated protocol, security/identity, and persistence/operations review in this conversation; the implementation agent did not sign on the owner's behalf. The approved review covers the exact V1 fields and limits, authenticated per-worker negotiation, mTLS-derived identity and replay behavior, durable ACK/retention semantics, and shared Python/Go/Java test-fixture conformance. The product owner has confirmed that trigger policy belongs to the consuming application, not the Sentinel library; no automatic Sentinel incident policy is in scope. Focused/runtime acceptance is recorded in process checklist §15.1236. Full consumer-role browser E2E remains T07.1; the disposable local Kubernetes retention Job is not evidence for production/multi-node deployment topology (T00.3).

### Consolidated owner freeze record

The project owner approved the following review responsibilities together as the accountable maintainer. This is a consolidated single-owner approval, not a claim that separate named specialists signed:

| Owner | Required review | Current status |
|---|---|---|
| Protocol / compatibility review | Field sets, protocol identifiers, event/fact enums, timestamp and exact-decimal semantics, stable error/ACK envelopes, additive V1/V2 evolution; shared Python/Go/Java fixture consistency. | Approved by project owner/maintainer, consolidated, 2026-10-15 |
| Security / identity review | mTLS-only peer identity, enrollment-derived scope, process-epoch checks, revocation, exact-body replay, request-size limits, and credential/principal/payload leakage prohibition. | Approved by project owner/maintainer, consolidated, 2026-10-15 |
| Persistence / operations review | Commit-before-ACK and exact replay durability, SQLite/PostgreSQL/MySQL behavior, 30-day logical/physical retention semantics, and scheduler/secret/volume requirements. | Approved by project owner/maintainer, consolidated, 2026-10-15 |

The owner approval is the explicit user decision to proceed with the recommended consolidated-owner route. Test-only Go/Java validators and SQL/transport tests are conformance evidence, not production SDKs or independent human signatures. The retention CronJob was applied and observed in a disposable Docker Desktop Kubernetes namespace under the separately approved isolated-equivalent acceptance path (§15.1236); this does not claim target/production deployment acceptance or close T00.3.

## Ownership and boundaries

The consuming application owns fault classification and explicitly invokes the Sentinel Runtime-facing typed producer with its selected finite incident fact. The producer does not sample metrics or infer policy. The Collector authenticates the Runtime, validates the event, persists it durably, and only then returns an ACK. The Dashboard timeline reads Collector-owned SQL records. This protocol is independent of Agent Reporting V1 and Metrics V2: it adds no event kind to either frozen protocol and does not reinterpret metric samples as incidents.

The Console uses the enrolled Reporter certificate fingerprint as the runtime identity authority. `environmentId`, `appId`, `instanceId`, `processId`, and the certificate principal are derived from that authenticated enrollment, never trusted from the request body. `processEpoch` must match the enrollment's current epoch. A revoked, unknown, non-TLS, or stale-epoch peer is rejected.

## V1 request

`POST /api/reporting/v1/incidents`, `Content-Type: application/json`, maximum 16 KiB.

The strict UTF-8 JSON object contains exactly:

| Field | Type | Meaning |
|---|---|---|
| `protocol_version` | string | `atlas-richie.incident-events/v1` |
| `event_id` | canonical lowercase UUID | Idempotency identity within one enrolled Reporter |
| `process_epoch` | canonical lowercase UUID | Current Reporter process incarnation |
| `occurred_at` | UTC RFC 3339 timestamp with exactly six fractional digits and `Z` | Runtime occurrence instant; not used as Collector receipt time |
| `severity` | `critical`, `warning`, or `info` | Runtime classification |
| `fact` | strict tagged object | One allowlisted incident fact, below |

All JSON numeric tokens are interpreted as exact base-10 decimal values for bounds and threshold comparison before projection to the implementations' binary64 fact DTO/storage value. A value outside the exact bound is rejected even if binary64 rounding would bring it within range; a valid strict threshold crossing must remain `value > threshold` after binary64 projection, otherwise the event is rejected because durable storage would erase the crossing. Negative underflow is invalid, not zero; a positive underflow is also rejected when projection erases the crossing (for example, both value and threshold project to zero). This rule is shared by every V1 consumer and fixture validator.

V1 `fact` variants:

| `kind` | Exact fields | Category projection |
|---|---|---|
| `resource_pressure` | `metric` (`cpu_ratio` or `memory_ratio`), `value` and `threshold` finite ratios `[0,1]`; `value` must be strictly greater than `threshold` | `resource` |
| `response_time` | `p95_ms` and `threshold_ms` finite non-negative numbers no greater than `2^53−1`; `p95_ms` must be strictly greater than `threshold_ms` | `rt` |

Unknown fields, unknown variants, duplicate JSON keys, non-finite numbers, invalid timestamps, invalid UUIDs, and malformed UTF-8 are rejected. V1 has no arbitrary caption, exception, traceback, request body, user identity, host path, or business log field. Rule publication/effectiveness facts are intentionally not in V1; their receipt-bound contract depends on T03.3 and requires a future compatible protocol decision.

## Durable ACK and retry semantics

The Collector derives scope from the verified TLS certificate, verifies current epoch, validates the event, and atomically writes the incident row before ACK. The response contains exactly the protocol version, event ID, SHA-256 digest of the exact request bytes, and Collector `received_at` UTC timestamp.

For the same Reporter and `event_id`, an identical body digest returns the original durable ACK; a different digest is `409 idempotency_conflict`. Events from revoked certificates or non-current epochs are rejected. Retries must reuse the same `event_id` and exact bytes. This is at-least-once delivery with idempotent persistence, not a claim of exactly-once transport.

The Collector error envelope is exactly `{"error":{"code":"<stable-code>"}}` and contains no request, identity, SQL, URL, or credential details. V1 status/code pairs are: `400` → `invalid_request`, `invalid_json`, `unsupported_protocol`, or `invalid_event`; `401` → `identity_not_enrolled`; `409` → `identity_mismatch` or `idempotency_conflict`; `413` → `payload_too_large`; `415` → `invalid_content_type`; `503` → `service_unavailable` or `storage_unavailable`. Network/TLS failures and HTTP `408`, `425`, `429`, and `5xx` are transient and may be retried with bounded backoff using the identical body/event ID. Other non-2xx responses are permanent and must not be retried. The client may expose only the allowlisted status/code classification, never raw response text.

V1 records have a 30-day logical retention limit from durable receipt. Timeline reads exclude records at or beyond `expires_at`; ingest opportunistically removes expired rows, and `SQLAlchemyIncidentEventAdapter.expire_incident_history(now)` provides an idempotent explicit maintenance operation. The one-shot `sentinel-console incident-events expire` CLI is implemented and tested, but no deployment-owned periodic CronJob/systemd timer has been configured or run in a target deployment. Operators must account for expired bytes remaining at rest until ingest or explicit maintenance. No unlimited retention is promised. `occurred_at` may be late or clock-skewed; filtering and ordering use it, while retention and receipt audit use Collector `received_at`.

## Runtime protocol negotiation fact

The `agent-reporting` system boundary is recorded only by an authenticated Runtime↔Collector hello/accept exchange. The Runtime sends exactly `{"protocol_version":"atlas-richie.reporting/v1"}` over enrolled mTLS to `POST /api/reporting/v1/protocol-negotiations/agent`. The Collector responds with `protocol_version` (`atlas-richie.protocol-negotiation/v1`), `boundary`, `runtime_version`, `collector_supported`, `compatibility`, and UTC `observed_at`; it persists the authenticated per-worker fact before returning success. The certificate enrollment supplies environment/app/instance/process/reporter identity; the request body cannot claim identity. Static package metadata or configured intent is never an active protocol fact. No successful handshake means `unknown`; an authenticated unsupported active version is `incompatible`.

An authenticated, session-protected Dashboard read is separately versioned at `GET /api/v2/system/protocol-observations/agent-reporting?page=1&pageSize=20`. One Reporter enrollment/worker is one Dashboard instance; enrollment must provide a unique `instanceId`. The paged read includes only safe worker identifiers, Collector-supported versions, Runtime version, compatibility, and observed time; it does not expose certificate principals. Revoked enrollment is excluded and therefore is not presented as a live active worker. `rule-config` and `cluster-token` remain separate authorities and stay `unknown` until each respective peer supplies its own authenticated facts. Console API `/api/v1/system/protocols` and its frozen 0.5.0 DTO are unchanged.

The incident event endpoint's own version is named by its strict `protocol_version`; it is not represented as Metrics V2 or as an Agent Reporting V1 event kind. Negotiating Agent Reporting V1 does not imply that the Runtime incident producer is installed or that Incident Event V1 was negotiated. Those are separate protocol boundaries.

### Incident Event protocol negotiation (implemented; owner freeze pending)

The Incident Event compatibility fact is negotiated independently from Agent Reporting. The mTLS hello is `POST /api/reporting/v1/protocol-negotiations/incident-events` with the exact body `{"protocol_version":"atlas-richie.incident-events/v1"}`. The Collector derives worker identity from the verified Reporter enrollment, determines compatibility against the supported Incident Event version set, durably stores the latest fact in the Incident Event-specific table before responding, and returns the bounded negotiation envelope with `boundary: "incident-events"`. An authenticated unsupported version is a durable `incompatible` fact; no hello remains `unknown`. Enrollment revocation denies subsequent negotiation and excludes the worker from the current read projection.

The matching session-authenticated Dashboard read is `GET /api/v2/system/protocol-observations/incident-events?page=1&pageSize=20`. It is additive to the Agent Reporting read and retains per-worker cardinality, paging, revoked-enrollment exclusion, and credential-principal privacy. Agent Reporting and Incident Event facts for one worker are persisted independently and never overwrite or imply one another. The additive handshake/read pair is implemented and has SQLite plus real mTLS/PostgreSQL/MySQL evidence; it is not a cross-language protocol freeze until the required protocol/security/storage owners sign the finalized contract.

## Timeline projection

The Collector SQL row maps its authenticated scope and event into the existing `ObservedIncident` DTO. `event_id` becomes the incident/source event identity; the tagged fact maps to the existing finite `IncidentFact` code. Query scope, category/severity filters, whole-scope statistics, stable `(occurred_at DESC, event_id DESC)` ordering, and bounded cursor pagination remain owned by the existing Console incident API contract. Evidence not held by this protocol remains explicitly unavailable rather than inferred.

## V2 evolution

V1 fields, event kinds, validation limits, ACK meaning, and retention are frozen after implementation sign-off. Adding event kinds or fields requires an independent V2 decision and must not alter Agent Reporting V1, Metrics V2, or frozen Console API 0.5.0.
