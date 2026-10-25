# Rule Publication Receipt V1

> **Status: Approved for implementation (2026-10-15).** This protocol is
> separate from Agent Reporting V1 and Metrics V2. Console API 0.5.0 remains
> read-only for publication receipts; only the authenticated Collector and
> internal Console projection worker may write receipt facts.

## 1. Purpose and boundaries

The Runtime reports the exact managed publication target it has applied or
reconciled. The Collector authenticates the Runtime certificate using the
existing Reporter enrollment authority, validates the scope and exact
publication tuple, then commits the receipt and an outbox item before ACK.
A Console worker consumes the Collector-owned outbox and idempotently projects
the receipt into the existing Console SQL read model. No receipt is inferred
from a latest-publication query, checksum-only match, provider write, Agent
Reporting event, Metrics snapshot, browser request, or unauthenticated claim.

The frozen correlation identity is
`{binding_id, publication_id, target_version_id}`. Runtime identity comes
only from the verified mTLS principal and active enrollment. The envelope is
not authentication.

## 2. Runtime receipt envelope

One UTF-8 JSON object is accepted per request, with exactly these fields.
Unknown or duplicate fields, trailing data, invalid UTF-8, and values outside
the declared bounds reject the whole request.

| Field | Type | Meaning |
|---|---|---|
| `protocol_version` | exact string | `atlas-richie.sentinel.rule-publication-receipt/v1` |
| `receipt_id` | UUID v4 string | Stable idempotency identity for an exact report body. |
| `process_epoch` | UUID string | Must equal the active enrolled process epoch. |
| `sequence` | positive safe JSON integer | Monotonic per authenticated enrollment and process epoch; starts at 1. |
| `binding_id` | bounded identifier | Exact Console binding being reported. |
| `publication_id` | bounded identifier | Exact immutable publication attempt. |
| `target_version_id` | bounded identifier | Exact immutable version selected by that publication. |
| `target_payload_sha256` | lowercase SHA-256 hex | Exact native target payload bytes from the managed envelope, not a reserialized array or aggregate source checksum. |
| `state` | closed enum | `applied`, `pending`, `failed`, `unknown`, `restart_required`. |
| `reason` | closed enum or null | Stable sanitized reason; required for `failed` and `restart_required`, null for all other states. |
| `source_revision` | bounded opaque string or null | Provider revision observed by the adapter; diagnostic only, never an identity or checksum substitute. |
| `observed_at` | UTC RFC 3339 millisecond instant | Runtime observation time; diagnostic and not authoritative ordering. |

Maximum request body is 16 KiB. Identifiers use the managed envelope identifier
grammar and maximum. `source_revision`, when present, is 1–200 printable ASCII
characters. `reason` values are `decode_rejected`, `digest_mismatch`,
`apply_failed`, `source_unavailable`, `stale_sequence`, and
`restart_required`. Error responses carry stable codes only; never echo the
request body, rule payload, SQL details, certificate path, or credentials.

### 2.1 HTTP transport and acknowledgement

- Collector accepts one receipt at `POST /api/reporting/v1/rule-publication-receipts` over HTTPS with mutual TLS and exactly one `application/json` content type (parameters are allowed).
- The verified TLS client certificate fingerprint is resolved through the active Reporter enrollment directory. Forwarded identity headers and body fields are not authentication.
- `204 No Content` means the exact receipt and one pending Collector outbox item committed atomically. An exact retry also returns `204` without inserting another outbox item.
- A failed transaction never returns success. The Runtime may retry the exact same receipt bytes and `receipt_id`.
- Stable error responses use `{"error":{"code":"..."}}` with `Cache-Control: no-store`; they do not include request or infrastructure details. Invalid framing/contract is a client error, absent or revoked identity is unauthorized, stale/conflicting sequence or tuple is a conflict, and unavailable durable storage is retryable `503`.

## 3. State and correlation rules

- `applied`: the rules and per-target provenance were atomically applied, or
  the Runtime verified that the exact current rules equal the target bytes.
  The Collector verifies tuple, authorized scope, and digest before projection.
- `pending`: Runtime has accepted the candidate but has not completed apply.
- `failed`: an apply attempt terminated without applying the target; `reason`
  is required. It does not mean the provider write failed.
- `unknown`: Runtime cannot establish whether the target is active.
- `restart_required`: the profile/runtime cannot apply the exact target until
  restart; `reason` must be `restart_required`.
- `failed` requires one of `decode_rejected`, `digest_mismatch`,
  `apply_failed`, `source_unavailable`, or `stale_sequence`; it cannot use
  `restart_required` as a reason. All other states require `reason: null`.
- `observed_at` is retained as the runtime-reported observation. Collector
  `received_at` is its own UTC clock and is authoritative for ingestion and
  outbox ordering. Existing Console `applied_at` is populated only for
  `applied`; `last_report_at` comes from Collector receipt time.
- The Collector resolves the tuple to exactly one persisted publication and
  target version. It checks the binding scope against active enrollment and
  the target digest against the persisted `target_payload_checksum`.
- Only after validation does the projection map the immutable target version's
  existing Console `target_checksum` into `loaded_checksum`. The payload digest
  is a distinct field in the Collector contract and must never be mislabeled.
- Same exact `receipt_id` and body hash is idempotent. Same ID with different
  bytes is `idempotency_conflict`. Sequence is strictly increasing per
  `(certificate_principal, process_epoch)`; exact retries are accepted without
  a second outbox item. Older epochs, lower sequences, conflicting sequence
  values, unknown publications, target/version mismatch, digest mismatch,
  revoked identity, or unauthorized binding scope produce no projection write.

## 4. Identity and revocation

1. The TLS edge validates the client certificate and exposes only its SHA-256
   fingerprint to the Collector application.
2. The Collector resolves that fingerprint to exactly one active enrollment
   and obtains environment, app, instance, process, and current epoch from the
   enrollment record. Body identity fields cannot override them.
3. A binding is authorized only when its persisted environment and application
   match the enrollment scope. Missing, revoked, stale-epoch, or ambiguous
   enrollment rejects the receipt.
4. Ingestion and revocation serialize on the same enrollment row. A receipt
   cannot commit after revocation has won that serialization point.
5. The internal Console worker uses a separate service certificate/principal;
   Runtime certificates cannot read or acknowledge the Collector outbox.

## 5. Collector durable outbox and Console projection

The Collector owns the receipt inbox/outbox tables in its selected durable SQL
store. In one transaction it validates current enrollment, sequence and
idempotency; stores the accepted immutable receipt fact; and inserts one
`pending` outbox row. The Runtime ACK is sent only after that transaction
commits. A database failure returns a retryable service error and creates no
ACK.

The Console worker uses a private authenticated service channel to claim a
bounded batch from the Collector outbox. Claim leases fence concurrent workers.
For each item, Console revalidates the exact tuple, scope, and digest against
its own publication authority, commits the existing receipt projection with
the receipt id/epoch/sequence ordering, and only then asks Collector to mark
the outbox item delivered. If Console commits and its acknowledgement is lost,
redelivery is safe: the projection is idempotent. Transient storage/transport
failure releases work after lease expiry. Permanently invalid facts are parked
with a stable sanitized rejection code and never projected.

Collector and Console do not need a shared database. The outbox transport is
not mounted on the browser/session API. Console API 0.5.0 remains read-only;
the existing protected receipt GET is the projection read-back.

## 6. Required validation

### Contract and runtime

- Shared Python/Java validator fixtures: valid applied, each allowed state,
  invalid enum/reason combinations, invalid UUID/time/sequence/ID/digest,
  duplicate/unknown/missing fields, trailing data, invalid UTF-8 and body-size
  overflow.
- Managed envelope: valid `[]`, non-ASCII payload digest, invalid checksum,
  native-array under the managed profile, malformed envelope, explicit legacy
  profile compatibility, and last-known-good preservation.
- Runtime behavior: atomic rule/provenance apply; identical payload with new
  publication still records a new fact; same tuple retry idempotent; rollback
  higher sequence; delayed lower sequence cannot replace current state; restart
  and last-known-good behavior.
- Python↔Java demo harness: fixed response, delayed response, caller timeout,
  post-timeout recovery in both request directions. It is transport evidence
  only, not a Java Runtime Adapter claim.

### Collector, persistence, and read-back

- mTLS missing/untrusted/revoked peer, stale epoch, unauthorized environment/app
  scope, unknown publication, foreign binding, mismatched target version,
  payload digest mismatch, exact replay, conflicting replay, duplicate sequence,
  and out-of-order sequence. Rejected facts create no Console projection.
- Crash/failure windows: Collector commit before Runtime ACK; Console commit
  before Collector outbox mark-delivered; worker lease expiry/reclaim; exact
  duplicate delivery. Verify liveness and no duplicate visible receipt.
- Disposable PostgreSQL and MySQL: migrate from the existing schema, publish
  managed envelopes to Nacos and Consul with provider read-back, persist a
  receipt through Collector outbox and Console worker, then read it through the
  existing protected Console GET. SQLite remains unit/contract coverage.
- Same binding, two publication IDs, identical target rule bytes: each exact
  publication remains separately queryable with its own target version and
  instance receipt. Compare persisted SQL rows and GET response; verify no
  secret or raw rule body leakage.

The Python/Java HTTP demo does not replace the production Python source adapter,
managed provider publish/read-back, authenticated receipt path, durable outbox,
or PostgreSQL/MySQL receipt read-back. T03.3 closes only after those gates pass;
full React browser E2E remains T07.1.
