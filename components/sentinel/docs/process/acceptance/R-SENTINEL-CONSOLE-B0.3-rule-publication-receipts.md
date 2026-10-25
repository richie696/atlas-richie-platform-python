# B0.3 Rule Publication Receipt Acceptance Plan

> Status: implementation plan aligned with the approved Rule Publication Receipt V1 protocol and decisions D1–D7 (2026-10-15).
> Scope: authenticated Runtime receipt ingress and Collector durability, followed by Console projection. T03.3 acceptance evidence is recorded in the execution tracker §15.1230–§15.1235; this document remains the functional contract and repeatable acceptance matrix.

## 1. Frozen decisions

| Decision | Frozen behavior |
|---|---|
| D1 | Managed Rule Publication Envelope V1 is explicit opt-in per binding; every publication attempt has its own durable per-binding sequence. |
| D2 | Persist SHA-256 of the exact native target payload bytes separately from the API/source checksum. |
| D3 | Existing native-array profile remains the default. Managed profile activation and rollback are explicit. |
| D4 | Cross-language validation includes minimal Python and Java HTTP demos: a fixed-string success endpoint and an independent bounded-delay endpoint. These demos are transport evidence only. |
| D5 | Rule snapshot and per-target provenance are applied atomically. |
| D6 | Receipt identity, scope, epoch, revocation, ordering, and replay checks derive from authenticated enrollment; body identity is not authoritative. |
| D7 | Collector commits receipt inbox and durable outbox together; a Console worker consumes the outbox and projects idempotently. |

## 2. Functional closure and evidence

| Slice | Required behavior | Focused evidence | Closure condition |
|---|---|---|---|
| Contract | Strict Receipt V1 JSON; exact keys, closed enums, bounded IDs, UUID/time/digest validation, 16 KiB limit | Shared Python/Java fixtures and validator tests | Both implementations accept/reject the same fixture corpus |
| Runtime publication | Managed envelope preserves exact provider bytes and binding/publication/version tuple; atomic rules+provenance apply; explicit legacy behavior | Python runtime adapter tests; provider read-back for Nacos and Consul; fixed/delayed Python↔Java HTTP demos | No checksum-only inference; rollback/new publication and stale-update cases verified |
| Runtime receipt reporting | Successful application facts become one Receipt V1 per managed target and reach Collector using the active mTLS enrollment; retries preserve exact receipt identity/body | Production Python reporter subscribed to the rule-application event; loopback Runtime→real Collector socket acceptance; Python↔Java demo remains transport-only | A network outage cannot block rule application; queue/overflow, cancellation, close, exact retry and durable Collector ACK semantics are explicit and tested |
| Collector ingress | Verified mTLS certificate resolves to one active enrollment; enrollment scope and epoch are authoritative | ASGI route/SQL tests plus real loopback mTLS socket acceptance with enrollment rows | Missing/untrusted certificate is rejected at TLS; revoked/stale-epoch/ambiguous/unauthorized peer creates no receipt/outbox |
| Replay control | Per-receipt exact-body idempotency; per-principal+epoch monotonic sequence; conflicting ID/sequence and old epoch rejected | SQLite transaction tests and concurrent duplicate test | Exact retry produces one inbox/outbox fact; conflicts produce none |
| Collector durability | Receipt and outbox commit atomically before HTTP 204 | Failure injection around SQL transaction and route ACK | Commit failure never returns success; restart retains pending outbox |
| Console projection | Bounded leased claim; verify tuple/scope/digest from publication authority; idempotent projection; mark delivered only after projection commit | Worker tests including commit-before-ack retry and lease expiry | Redelivery creates one visible receipt and does not lose pending work |
| SQL portability | Migrations and end-to-end persistence behavior for PostgreSQL and MySQL | Disposable real PostgreSQL/MySQL acceptance | Receipt accepted, projected, and read back through protected GET on both |
| External provider path | Managed publish/read-back through Nacos and Consul | Disposable real Nacos/Consul acceptance | Exact target bytes and target tuple verified, independent of mocked HTTP demo |

## 3. Collector ingress transaction

1. Reject non-HTTPS, absent verified peer certificate, invalid media type, malformed framing, oversized or invalid Receipt V1 body.
2. Resolve certificate fingerprint against active reporter enrollment. Take a row-level serialization lock shared with revocation; then re-check revocation, current process epoch, scope, and sequence within the same transaction.
3. Resolve `(binding_id, publication_id, target_version_id)` against the persisted publication authority; require binding environment/application to equal enrollment and compare exact target payload digest.
4. For exact prior `receipt_id` plus exact body hash, return the prior durable acceptance without inserting another outbox item. Reject receipt-ID/body conflicts, duplicate/conflicting sequence, lower sequence, and stale epoch.
5. Insert immutable inbox fact and one pending outbox item in the same transaction. Update the receipt-specific sequence baseline in that transaction; do not reuse Metrics V2 `last_sequence`.
6. Return HTTP 204 only after transaction commit. Storage errors return a stable retryable error with no success ACK.

## 4. Console worker transaction

1. Claim a bounded batch with a lease token/expiry so concurrent workers cannot own the same active claim.
2. Revalidate exact publication tuple, binding scope, target version, and target-payload digest against Console SQL authority.
3. Project to the existing receipt read model with ordering by enrolled process epoch and receipt sequence. `applied_at` is populated only for `applied`; `last_report_at` uses Collector `received_at`.
4. Commit projection before asking Collector to mark the outbox row delivered. If that acknowledgement is lost, repeat projection safely.
5. Park permanently invalid records with a stable sanitized code; never project them or expose raw payload, credentials, certificate metadata, or SQL details.

## 5. Security and negative-case matrix

Each rejection below must leave both the Console projection and the accepted-outbox count unchanged:

- no TLS / no peer / untrusted certificate / unknown or revoked enrollment;
- enrollment with no active epoch, stale epoch, or changed epoch during request;
- binding outside enrolled environment/application scope;
- missing publication, foreign binding, target-version mismatch, or missing managed payload digest;
- target payload digest mismatch;
- exact sequence retry with different body, same receipt ID with different body, duplicate sequence with another receipt ID, and lower sequence;
- unknown fields, duplicate JSON keys, trailing JSON, invalid UTF-8, invalid state/reason pairing, invalid UUID/time/ID/digest, oversized body, invalid content type, and malformed Content-Length.

## 6. Operational and recovery evidence

- Collector transaction fails before commit: Runtime receives non-success and retry is accepted later.
- Collector commits but response is lost: exact retry returns success without duplicate inbox/outbox.
- Console projection commits but Collector acknowledgement is lost: redelivery remains idempotent.
- Worker crashes with a claimed item: lease expires, another worker reclaims it, and it is projected once.
- Database restart preserves pending outbox rows and sequence/idempotency state.
- Read-back uses the existing protected receipt GET; browser E2E remains separately tracked as T07.1.

## 7. T03.3 close gate

T03.3 is complete only after the strict cross-language contract, Python runtime managed source behavior and production receipt reporter, real Nacos and Consul publish/read-back, authenticated Collector inbox/outbox, Console projection worker, disposable PostgreSQL and MySQL persistence, negative/replay/crash-window matrix, and protected GET read-back have all passed. A sub-slice or transport demo is not sufficient to mark the whole task complete.

## 8. Approved Runtime queue delivery semantics

- The Runtime reporter uses a bounded in-memory queue; it does not add local
  persistence or make Repository apply wait on the network.
- A queue admission is all-or-none per apply event. Capacity overflow is
  counted as `queue_full`; enqueue and counters use short local lock sections.
- Transient transport failures retry with a finite exponential backoff budget
  and resend the exact same serialized receipt bytes and identity.
- Only Collector HTTP 204, issued after inbox/outbox transaction commit,
  increments the delivered count. Permanent rejection and exhausted retry
  count as delivery failures.
- Shutdown stops admission, drains only for a configured finite interval, and
  counts pending losses as `abandoned_on_close`. A process crash can lose
  unacknowledged in-memory items; this is the explicitly approved trade-off,
  not a durable local outbox guarantee.
- The optional reporter is attached to the same `RuleRepository` that the
  selected source lifecycle uses. Its mTLS credential provider owns current
  enrollment credentials; transport refreshes the HTTP connection pool when
  credential generation changes.

The implementation and evidence for these semantics are in
`atlas-richie-sentinel-reporter-rules` and tracker §15.1235. The final React
browser journey remains reserved for T07.1.
