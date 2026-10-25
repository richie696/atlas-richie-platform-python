# Managed Rule Publication Envelope V1 — Design Draft

> **Status: APPROVED FOR IMPLEMENTATION; conformance and production acceptance
> remain open.** Product owner decisions D1-D7 are approved for this design.
> This does not mark T03.3 complete or authorize claiming that the HTTP demo is
> a production Sentinel Runtime adapter. Console API 0.5.0 and Agent Reporting
> V1 remain unchanged.

## 1. Purpose and scope

The Console publishes one immutable rule version to one configuration-center
target. Native Sentinel consumers expect a JSON array and do not know the
Console's binding/publication/version identities. T03.3 needs a runtime to
report the exact publication it loaded, including when two publications contain
identical rule bytes. V1 therefore wraps the unchanged native array text in a
versioned, opt-in managed envelope written atomically as one provider value.

The envelope is a source-side propagation format, not an authentication token.
Runtime identity and authorization come from the independently authenticated
Reporter enrollment/transport. Never trust an envelope's tuple as proof that
the publishing Console or reporting Runtime is authorized.

The Product owner selected Python and Java loopback HTTP demos as the
cross-language transport check: both peers return a fixed response and expose
a separate bounded-delay endpoint. This verifies request reachability and
timeout behavior only; envelope fixtures and the production Python
source/receipt path provide the rule-propagation evidence. The demo is not a
Java Sentinel Runtime source adapter.

Out of scope: Collector receipt transport, identity enrollment/revocation,
receipt-state taxonomy, durable ACK, SQL projection, Console API changes,
automatic source migration, or an Alibaba Sentinel protocol change.

## 2. Compatibility and profile selection

- Existing native-array targets remain byte-for-byte unchanged and continue to
  use the existing native-array source profile.
- The new `managed-envelope-v1` profile is opt-in per registered binding and
  requires a metadata-aware source adapter. It is never auto-detected by a
  legacy/native-array consumer.
- Console publication opt-in is an explicit binding-ID allowlist
  (`SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS`); the Runtime's
  `managed_bindings` map independently selects the matching exact binding and
  per-kind source targets. Both sides must be configured before the first
  managed write. The envelope's `profile_id` remains the native rule decoder
  profile, not the outer envelope protocol identifier.
- A binding may not change profile implicitly during publish, rollback, retry,
  or reconnect. Profile migration is an explicit administrative operation with
  a documented rollback path.
- The adapter verifies the complete envelope, extracts the exact UTF-8 bytes
  held in `rule_payload`, and passes only those bytes to the existing
  rule-kind decoder. The Sentinel Engine and rule value models do not depend on
  Console fields.
- Under the managed profile, an envelope containing `[]` means an authoritative
  empty rule set. A missing target, empty provider value, malformed envelope,
  or invalid checksum is not an empty rule set: reject the candidate and retain
  last-known-good. This intentionally differs from legacy native `[]` handling.
- A five-data-id Nacos snapshot may contain managed targets for multiple rule
  kinds. The source adapter must retain a bounded provenance tuple per managed
  target; it must not collapse provenance into the aggregate `RuleVersion`
  checksum or choose one arbitrary publication ID for the full snapshot.

## 3. Frozen V1 wire record

The V1 JSON object has exactly these fields; unknown fields and duplicate JSON
keys are rejected.

| Field | Wire type | Meaning |
| --- | --- | --- |
| `protocol_version` | string, exact constant | `atlas-richie.sentinel.managed-rule-publication/v1` |
| `binding_id` | bounded opaque identifier | Console rule-source binding identity |
| `publication_id` | bounded opaque identifier | One immutable publication attempt; differs on same-content republish |
| `target_version_id` | bounded opaque identifier | Immutable version selected by that publication |
| `publication_sequence` | positive safe JSON integer | Strictly increasing per binding; rollback creates a new publication with a larger sequence |
| `rule_kind` | closed string enum | `flow`, `degrade`, `system`, `authority`, or `param` |
| `profile_id` | bounded opaque identifier | Exact native decoder profile selected for this binding |
| `payload_sha256` | lowercase 64-character hex | SHA-256 over the exact UTF-8 bytes represented by `rule_payload` |
| `rule_payload` | string containing JSON array text | Exact compact native same-kind Sentinel JSON array bytes, decoded from the JSON string as UTF-8 |

The `rule_payload` string boundary is intentional: both languages hash the same
bytes without reserializing parsed JSON. Outer JSON whitespace/property order
does not affect the payload digest. The digest does not authenticate the
publisher and is not a signature.

V1 bounds: outer envelope at most 512 KiB; inner payload at most 500 KiB;
identifiers are non-empty printable ASCII `[A-Za-z0-9][A-Za-z0-9._:-]{0,199}`;
`publication_sequence` is in `1..9007199254740991`; the rule array may be empty,
otherwise every item must be an object accepted by the selected existing
rule-kind decoder. Limits are deliberately aligned with current Console target
and JavaScript-safe-integer boundaries where possible; the publisher rejects
oversize values before contacting a provider.

Wire example:

```json
{"protocol_version":"atlas-richie.sentinel.managed-rule-publication/v1","binding_id":"binding-01","publication_id":"publication-42","target_version_id":"version-42","publication_sequence":42,"rule_kind":"flow","profile_id":"sentinel-nacos-flow-v1","payload_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","rule_payload":"[]"}
```

## 4. Publisher and source-adapter obligations

### Publisher

1. Resolve the binding, immutable version, profile, and target from persisted
   Console authority; never accept caller-supplied envelope identity fields.
2. Encode the native array exactly once using the existing profile encoder.
3. Allocate a durable, monotonic per-binding sequence in the same transactional
   boundary as publication creation. Concurrent publications must not receive
   the same sequence. Provider CAS still fences writes; sequence is not a
   substitute for provider revision.
4. Hash the exact encoder bytes, place those bytes as a UTF-8 JSON string in
   the envelope, then atomically publish the envelope using the existing
   provider conditional-write/read-back flow.
5. Never include credentials, endpoints containing secrets, user identity,
   source access tokens, or rule-management-only fields in the provider value.
6. A deployment removes a binding from the managed writer allowlist only after
   switching every Runtime source adapter to the native-array profile and
   publishing a new native-array value. A native-array Runtime must not be
   pointed at an envelope value during rollback.

### Metadata-aware source adapter

1. Be enabled only by an explicit `managed-envelope-v1` profile configuration;
   do not infer the format by inspecting arbitrary JSON.
2. Strictly validate exact fields, UTF-8, duplicate keys, trailing data, all
   bounds, closed enums, and the inner JSON array before exposing a candidate.
3. Hash the decoded inner string's UTF-8 bytes and compare in constant-time
   where the language/runtime provides it; do not hash a reserialized array.
4. Reject a sequence less than or equal to the last accepted sequence for the
   same binding, except an exact idempotent replay of the same tuple, sequence,
   digest, and payload. A same-sequence different tuple/payload is a conflict.
5. A lower sequence from delayed provider data must not replace a newer applied
   candidate. A rollback is a newly created publication and therefore has a
   higher sequence.
6. Apply rules and provenance atomically at the Repository boundary. If decode
   or apply fails, keep both last-known-good rules and their provenance. A
   metadata-only publication with identical rule bytes still updates provenance
   and emits its own receipt fact after successful apply/reconciliation.
7. Treat a valid managed envelope containing `[]` as a successful empty
   snapshot; preserve legacy-native empty semantics outside this profile.

## 5. Checksum and receipt mapping

The envelope's `payload_sha256` is a fourth checksum domain, distinct from:

- Console `target_checksum` over normalized management records;
- aggregate source `RuleVersion.checksum` over source key/value facts;
- configuration-provider CAS revision (for example Nacos MD5).

The receipt contract must report and validate the payload digest separately.
The trusted Collector resolves the exact tuple against the Console publication,
compares the observed payload digest against the persisted digest for that exact
target/profile, then maps the verified immutable version identity to the
existing Console receipt projection. It must never relabel an aggregate source
checksum or provider CAS revision as `loaded_checksum`. The current SQL receipt
and API projection cannot be reused safely until this mapping and durable ACK
transaction are owner-approved.

## 6. Cross-language conformance contract

Python and Java (and any future Go runtime) must consume the same schema and
positive/negative fixtures. Required candidate checks:

- exact field set, duplicate-key rejection, trailing-token rejection, UTF-8;
- accepted valid envelope and extraction of byte-identical `rule_payload`;
- SHA-256 vector agreement, including non-ASCII payload bytes;
- legacy native array remains accepted only in the legacy profile and is not
  mistaken for an envelope;
- unknown version/field/kind/profile, invalid identifiers, booleans/fractions/
  unsafe integers, malformed inner JSON, non-array/non-object item, digest
  mismatch, and byte-limit overflow all reject;
- same tuple replay is idempotent; same payload with a different publication
  remains a distinct provenance fact; sequence rollback and delayed stale
  envelopes are rejected; failed candidate retains last-known-good rules and
  provenance.

The first conformance harness is test-only. It proves the Python and Java
candidate validators agree on shared fixtures; it does not prove a Java
Sentinel Runtime source adapter exists, integrates with the Alibaba source
adapter, or applies rules in production.

## 7. Approved decisions and implementation gates

The following Product decisions are approved for implementation:

1. Freeze this envelope schema and its stated bounds as Managed Rule
   Publication Envelope V1. `publication_sequence` is allocated durably and
   monotonically per binding in the same transaction that creates the
   publication; rollback is a new publication with a higher sequence.
2. Persist the exact encoded target payload digest as an internal
   `target_payload_checksum`; preserve the existing immutable
   `target_checksum` and Console API 0.5.0 semantics.
3. Profile selection remains explicit per binding. Existing native-array
   profiles never auto-detect or unwrap an envelope. A valid managed `[]` is
   authoritative empty rules; missing/empty/malformed values reject and retain
   last-known-good. Profile migration is explicit and has a rollback path.
4. Cross-language transport validation uses the Python and Java demo peers
   documented under `foundation/contracts/tests/rules/managed_publication_v1/`.
5. Each managed target retains its own immutable provenance; rules and
   provenance are applied atomically. Identical rule bytes under a new
   publication still produce a distinct receipt fact.
6. Runtime receipt identity is derived from active authenticated enrollment;
   exact replay is idempotent, conflicting replay is rejected, and revoked or
   stale process identities cannot replace current facts. Existing receipt
   states retain their meanings; the independent receipt V1 contract defines
   exact wire fields and transitions.
7. Collector persists accepted receipt facts and a delivery record in its
   durable outbox before ACK. A Console projection worker consumes that
   outbox; projection is idempotent, and Collector marks delivery only after
   Console commits the receipt projection.

These decisions authorize implementation, not a claim that every layer is
already complete. Remaining implementation gates are production managed
profile publish/read-back, the Python source adapter, target digest/sequence
storage, authenticated receipt ingest, Collector-owned outbox and Console
projection, and PostgreSQL/MySQL acceptance.

## 8. Owner decisions and acceptance

| Owner | Must approve before production receipt implementation |
| --- | --- |
| Product/API | **Approved:** tuple, envelope path, explicit profile migration and receipt-state family |
| Console/protocol | **Approved for implementation:** schema, sequence allocation, checksum domain and bounds |
| Sentinel Runtime | **Approved for implementation:** Python Adapter and atomic per-target provenance; Java demo is not a runtime adapter |
| Collector/protocol | **Approved for implementation:** independent authenticated receipt V1 and durable outbox delivery |
| Security/identity | **Approved for implementation:** enrollment-derived identity, scope checks, revocation and replay defense |
| Storage/deployment | **Approved for implementation:** durable payload digest/sequence and idempotent outbox projection |

Do not enable managed profile writes in production or claim T03.3 complete
until the receipt acceptance matrix passes. Do not change Agent Reporting V1
or Console API 0.5.0.
