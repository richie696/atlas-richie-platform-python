# Runtime Rule Load Observation V1

> **Status: implementation draft.** This protocol is independent from Agent Reporting V1, Metrics V2, Incident Events V1, and Rule Publication Receipt V1. The Python contract/strict codec, Collector mTLS durable inbox/outbox, authenticated protocol negotiation, leased SQL current-state projection, and test-only Go/Java shared-fixture consumers are implemented. Production Runtime SDK execution, authenticated Console load-observation read API, and PostgreSQL/MySQL acceptance are not complete yet.

## 1. Purpose and authority

This protocol reports the **current runtime-applied rule snapshot** for one enrolled process and one Console rule binding. It covers both native provider JSON and Console-managed rules. It answers “what rules did this runtime actually apply?” without requiring business traffic or a Console publication ID.

It does not replace or extend Rule Publication Receipt V1. Receipt V1 remains the evidence that a particular managed publication tuple reached a runtime. Rule Load Observation V1 is the current-state/liveness fact used to compare an active runtime snapshot with the current provider snapshot. Native rules never receive an invented publication identity.

Collector owns authenticated receipt time, identity/scope validation, durable acceptance, replay ordering, and current-state projection. Console owns its SQL read model and exposes it only through the authenticated Dashboard API. Configuration centers remain authoritative for rule bodies; this protocol never carries rule bodies or user data.

## 2. Transport identity and negotiation

- Runtime sends observations only over the authenticated mTLS Collector channel.
- The Collector endpoint is `POST /api/reporting/v1/rule-load-observations`, accepts at most 512 KiB of `application/json`, and returns `204 No Content` only after the exact request bytes, authenticated facts, ordering baseline, and durable projection-outbox row commit atomically. A retry with the same observation ID and exact bytes is idempotent; the same ID with different bytes is rejected as an idempotency conflict.
- The Collector resolves the verified certificate fingerprint to one active enrollment. Environment, application, instance, process, and current process epoch come only from enrollment; request body fields cannot override them.
- The Collector validates `binding_id` and `profile_id` against the active enrollment scope and registered Console binding. Unknown, revoked, expired, stale-epoch, or cross-scope identities are rejected without persistence.
- The runtime and Collector negotiate `atlas-richie.sentinel.rule-load-observation/v1` over the authenticated Runtime↔Collector protocol negotiation path. Compatibility remains `unknown` until that actual exchange is persisted. An installed package, configured URL, or Dashboard-side version guess is not evidence of compatibility.

## 3. Event body

The body is one UTF-8 JSON object, at most 512 KiB, with exact fields. Duplicate, missing, unknown, or wrongly typed fields reject the whole body. IDs are canonical UUID v4 strings; `sequence` is a positive safe JSON integer. `observed_at` is a diagnostic UTC RFC 3339 millisecond instant.

| Field | Type | Meaning |
|---|---|---|
| `protocol_version` | exact string | `atlas-richie.sentinel.rule-load-observation/v1` |
| `observation_id` | UUID v4 | Stable idempotency identity for exact body bytes |
| `process_epoch` | UUID v4 | Must equal the active enrolled process epoch |
| `sequence` | positive safe integer | Strictly increasing per enrolled process epoch and binding |
| `binding_id` | bounded identifier | Exact registered rule binding; not authentication |
| `profile_id` | bounded identifier | Frozen runtime rule profile/canonicalization profile |
| `event_kind` | enum | `snapshot_applied`, `snapshot_failed`, or `heartbeat` |
| `active_snapshot` | object or null | Last snapshot the runtime actually has active after successful SDK apply |
| `attempt` | object or null | Sanitized facts about the latest failed candidate; never changes active state |
| `observed_at` | UTC millisecond instant | Runtime diagnostic time; Collector `received_at` is authoritative for freshness |

`active_snapshot` contains:

| Field | Type | Meaning |
|---|---|---|
| `source_revision` | bounded opaque string or null | Provider-owned revision when available; never substituted with a checksum |
| `source_bytes_sha256` | lowercase SHA-256 or null | Exact provider bytes only when the runtime can establish them |
| `canonical_rules_sha256` | lowercase SHA-256 | Canonical normalized full rule snapshot checksum |
| `membership_complete` | boolean | Whether every exact snapshot member is represented below |
| `members` | sorted unique bounded array | `(rule_kind, fingerprint_sha256)` values using the profile's frozen canonical member algorithm |

If the profile cannot provide complete membership, `membership_complete=false` and `members=[]`; consumers must display per-rule membership as unknown, never zero or “not loaded.” `profile_id` is the authority for interpreting fingerprint canonicalization. A source revision, exact source-byte digest, canonical snapshot digest, and member digest are separate values and cannot be substituted for one another.

`attempt` contains nullable provider revision, nullable exact source-byte digest, nullable canonical candidate digest, and a closed `failure_reason`: `source_unavailable`, `decode_rejected`, `profile_unsupported`, `validation_rejected`, or `apply_failed`. It contains no exception text, raw JSON, credentials, or business payload.

## 4. State transitions and acknowledgement

- `snapshot_applied` requires `active_snapshot` and forbids `attempt`. Emit only after the SDK/engine atomically applies the snapshot. A successful fetch or decode alone is not “applied.”
- `snapshot_failed` requires `attempt`; `active_snapshot` may carry the previous last-known-good snapshot or be null before the first successful load. Collector records the failure but does not replace the current active snapshot with the candidate.
- `heartbeat` forbids `attempt` and may repeat the exact active snapshot (or null when none has been applied). It is sent independently of business requests.
- An exact retry with the same `observation_id` and body digest is idempotent. Reuse of the ID with different bytes is rejected. Lower or conflicting sequence values cannot roll current state backward. `received_at` is the server UTC clock and wins over runtime `observed_at` for current ordering and freshness.
- A failed provider/application event never erases last-known-good. New epochs, revocation, enrollment expiry, and freshness expiry remove a process from the **current online** view; retained history may still show older observations.
- Provisional freshness candidate (not frozen by this draft): runtime heartbeat cadence at most 30 seconds; Collector marks the process observation stale after 90 seconds without an accepted heartbeat/event. It uses Collector receive time, not browser focus or the runtime wall clock. The product/protocol owners must approve cadence and expiry before this becomes a V1 implementation constraint.

## 5. Persistence, query, and UI mapping

Collector validates identity, binding/profile authorization, sequence, idempotency and contract before committing one immutable inbox fact plus one pending outbox item in a single durable transaction. It ACKs only after commit. Console consumes the outbox with a lease, performs an idempotent current-state/history projection, and ACKs delivery only after commit. Runtime certificates cannot consume/acknowledge the outbox.

The Dashboard query read model is bounded and scoped by environment, app, binding, and optional instance. It returns the confirmed registered-target denominator separately from observed workers; unknown inventory must stay unknown. For each worker it returns authenticated instance/process identity, current epoch, profile, active canonical checksum, provider revision when available, exact/incomplete membership capability, load result, last failure classification, Collector receive time, and freshness. Raw content and credentials are never returned.

For one rule, the UI may say “loaded/matches” only when a complete profile-compatible member set proves exact membership. A different active checksum is “another version,” not a fabricated rule-level failure. An incomplete membership set, unsupported profile, absent observation, unknown denominator, or incompatible/unobserved protocol is explicitly unknown. Request blocked counts are not copied to each rule.

## 6. Required verification before T03.5 closes

- Python, Java, and Go validate the same shared positive/negative fixture set; unknown fields/enums, duplicate JSON keys, invalid UUID/epoch/sequence/checksum/profile/time, incomplete-member contradictions, and body-size overflow fail closed.
- mTLS missing/untrusted/revoked peers, wrong epoch/scope/binding/profile, replay, conflicting IDs, duplicate sequence, out-of-order observations, and database failure produce no incorrect current state or success ACK.
- Durable collector commit/ACK loss, worker lease expiry, console commit/outbox ACK loss, restart, revocation, and stale expiry prove replay safety and liveness.
- SQLite focused contract plus disposable PostgreSQL and MySQL persistence read-back prove durable current-state/history projections. No production or user-owned database is used for acceptance.
- T03.5 validates transport and projection. Official Java/Go SDK actually loading/applying rules is T00.4; Rust is T00.5; React rule detail is T06.7; full browser workflow is T07.1.
