# Rule Publication Runtime Receipt Projection — Decision Draft

> **Status: DRAFT — Option A and the managed-envelope propagation path are
> approved by Product/API owner; the wire schema, runtime integration, and
> remaining owner approvals still require review.**
> This document does not authorize a new network route, change frozen Console
> API 0.5.0, extend Agent Reporting V1, or enable receipt writes from a runtime.

## 1. Decision to make

The Dashboard needs to show whether each runtime instance applied a particular
immutable rule publication. The Console already owns the exact
`binding_id`/`publication_id`/`target_version_id` facts and has a SQL receipt
writer and protected read API. A runtime report is not sufficient unless it can
be authenticated and correlated to those exact facts without guessing.

The decision is how a trusted Collector or equivalent runtime-reporting
authority projects an authenticated instance observation into the existing
`RulePublicationReceiptWriter`, while keeping the browser-facing Console API
and frozen Reporting V1 unchanged.

## 2. Confirmed facts and constraints

- The SQL receipt store validates and persists an exact receipt, and the
  Console exposes a session-protected paginated GET. Current production SQL
  composition installs the reader only; no production call site writes runtime
  receipts.
- The existing V1 `RULE_SOURCE_ACTIVATED` payload identifies a source and
  source version. It does not identify a Console binding, publication, or
  target version. A repeated checksum is not a unique publication identity.
- Reporter identity must come from authenticated enrollment/transport context;
  a payload-supplied instance or reporter ID is not proof of identity.
- The V1 Collector boundary is separately constrained and must not be silently
  exposed as a browser-facing Console route.
- A missing, stale, or ambiguous correlation must never be resolved by choosing
  the newest publication or by matching checksum alone.
- The metric owner’s approval of Metrics V2 §4.1 semantics is independent of
  this rule-publication receipt decision.

## 3. Design-pattern and responsibility assessment

The applicable candidate is **Adapter**, not Observer or Mediator:

- **Business capability:** record an authenticated runtime's observed
  application of one exact published rule version.
- **Data ownership:** Console publication records remain authoritative for
  binding/publication/version identity; a trusted Collector or enrollment
  authority owns authenticated runtime identity; the SQL receipt store owns
  durable receipt state.
- **Synchronous capability:** the projection needs the existing narrow
  `RulePublicationReceiptWriter` contract to persist a validated fact.
- **Independent event response:** no current requirement calls for multiple
  subscribers. Do not add a generic event bus, Observer fan-out, Mediator, or
  broad reporting service to solve this one projection.
- **Candidate Adapter:** translate a separately authenticated, versioned
  receipt contract into the Console-owned receipt writer contract. The Adapter
  validates the exact publication relationship before persistence and keeps
  Collector SDK/wire types out of Console application/domain contracts.

This is a candidate boundary only. Implementation requires explicit owner
approval of the contract and deployment transport. Existing ports and stores
should be reused; no second receipt repository or speculative public API should
be added.

## 4. Correlation options

| Option | Description | Assessment |
| --- | --- | --- |
| **A. Explicit receipt reference (recommended for review)** | A versioned trusted receipt carries exact `binding_id`, `publication_id`, and `target_version_id`, plus the observed source/version and result. The server derives reporter/instance identity from authenticated enrollment, then verifies that the publication belongs to that binding and exact target version before writing. | Unambiguous even when identical content is published more than once. Requires a new independently governed receipt contract and a way for the runtime to learn the opaque publication reference. Does not extend Reporting V1 implicitly. |
| **B. Server-side lookup from source/version tuple** | Resolve a publication from authenticated instance + `source_id` + source epoch/revision/checksum. | **Reject as default:** existing facts do not guarantee a unique mapping; equal content/checksum can be republished, and Console version IDs are not the V1 source revision tuple. Only consider if a separately frozen authoritative assignment ledger proves uniqueness and lifetime. |
| **C. Reuse V1 activation/execution events as-is** | Infer the receipt from `RULE_SOURCE_ACTIVATED` or `RULE_APPLIED`. | **Reject:** missing exact Console publication identity and authenticated instance-to-binding assignment; event meaning is not sufficient to claim a specific publication was applied. |

No payload field names, enum values, timestamps, or encoding are frozen here.

### 4.1 Product/API decision — 2026-10-14

The Product/API owner approved **Option A: explicit receipt reference**. This
selects the correlation model: a trusted receipt must identify the exact
binding, publication, and immutable target version it reports. On 2026-10-15,
the Product owner also approved implementation decisions D1-D7: freeze the
managed envelope schema/bounds; persist a per-binding sequence and exact
target-payload checksum; require explicit profile migration; use Python and
Java HTTP demos for cross-language transport/timeout checks; atomically apply
rules with per-target provenance; derive identity from enrollment and enforce
revocation/replay rules; and use a Collector-owned durable outbox consumed by
a Console worker. The HTTP demos do not claim to be Java Sentinel Runtime
source adapters. Console API 0.5.0 and Agent Reporting V1 remain unchanged.

The existing receipt states are retained. `APPLIED` means the exact target
was applied or reconciled and its payload digest verified; it cannot be
inferred from a successful provider write. Other states must be backed by an
explicit runtime outcome, not guessed from the latest publication.

The existing Dashboard read model remains the intended projection: the receipt
is shown under its exact publication and binding, with the runtime identity,
process incarnation, loaded/target version, checksum, timestamps, and
`PublicationReceiptState` supplied by the existing Console contract. The
approved correlation tuple is input validation for that projection, not a
replacement for its existing receipt fields.

### 4.2 Selected propagation design — wire contract still unresolved

Selecting Option A does **not** yet explain how the runtime learns the tuple.
The current `SentinelRuleVersionJsonEncoder` emits only the native same-kind
Sentinel JSON array; its contract explicitly excludes Console record IDs and
management discriminators. The Sentinel runtime's source snapshot carries its
source/version/checksum facts, not a Console `publication_id`. Therefore the
current publisher + native rule payload cannot produce an Option A receipt.

Before implementation, the Sentinel runtime and Collector/protocol owners must
freeze and prove the selected propagation contract across publish, apply,
restart, rollback, and duplicate-content republish. The original candidate
families reviewed were:

1. **Versioned envelope with a compatibility adapter:** carry publication
   metadata beside rule values, with an explicit decoder that unwraps the
   native rule array for the Engine. This requires a separately governed
   source contract and coordinated Java/Python support. A wrapped value is not
   a native same-kind array: existing consumers cannot keep reading the same
   key unchanged. Preserve legacy mode on its existing target profile or
   require an explicit migration; never silently switch formats.
2. **Authoritative assignment/control record:** deliver the exact tuple through
   an independently authenticated, durable channel and bind it to the precise
   provider revision observed by the runtime. If this is reconstructed only by
   looking up source/version/checksum after the fact, it collapses back into
   rejected Option B and is insufficient.
3. **Immutable versioned provider object plus an authoritative pointer:**
   make the immutable object identify its publication and ensure the runtime
   reports which exact object was loaded. The pointer transition, rollback,
   and consumer behavior must be specified; two unrelated writes without a
   transactional or reconciliation contract are not enough.

The Product/API owner has since selected the managed-envelope candidate in
§4.3. The other propagation families remain rejected/deferred. The selected
path is not a frozen wire contract. No runtime receipt implementation may
claim Option A until owner review freezes the envelope and tests prove exact
propagation, including two different publications with identical rule
bytes/checksum.

### 4.3 Product decisions — managed publication and receipt path approved, 2026-10-15

The Product/API owner approved D1–D7 for implementation: freeze Managed
Publication Envelope V1 and its bounds; persist a monotonic per-binding
publication sequence and the exact encoded target payload checksum internally;
keep Console API 0.5.0 and Agent Reporting V1 unchanged; select the managed
profile explicitly per binding while preserving native-array bindings; apply
managed rule data and target provenance atomically; derive receipt identity
from authenticated enrollment with revocation/replay protection; and have the
Collector durably enqueue accepted receipts before ACK for idempotent Console
worker projection. Python/Java standard-library HTTP demos are limited to the
fixed-response and bounded-delay transport smoke specified in the envelope
document; they are not production Sentinel Runtime adapters.

The frozen implementation contracts are maintained separately in
[`MANAGED_RULE_PUBLICATION_ENVELOPE_V1.md`](../protocols/MANAGED_RULE_PUBLICATION_ENVELOPE_V1.md).
The shared Python/Java conformance fixtures are under
`foundation/contracts/tests/rules/managed_publication_v1/`; current results
are recorded in the Dashboard progress tracker. Those validators are
test-only and do not constitute production Java Runtime interoperability.

#### Implementation implications confirmed by source inspection

- Console currently emits a native rule array; Nacos Python currently decodes
  native arrays, and the Java platform repository contains Alibaba Sentinel
  integrations but no Atlas-managed RuleSource adapter.
- The opt-in adapter must retain provenance per target/rule kind because the
  current Nacos source combines up to five data IDs into an aggregate
  `RuleSnapshot`; one publication ID cannot represent that aggregate.
- Managed `rule_payload: "[]"` must represent an authoritative empty snapshot,
  while a missing/empty/malformed provider value remains a rejected candidate
  that preserves last-known-good. The existing legacy-native `[]` policy must
  remain unchanged.
- Production enablement requires the durable per-binding sequence, persisted
  exact target-payload checksum, atomic rules-plus-provenance apply, and the
  separately authenticated receipt path specified by the approved V1
  contracts. Their code and full acceptance remain in progress.

#### Existing conformance evidence

The fixture harness validates a shared two-valid/ten-invalid envelope set in
Python and Java/Jackson. It covers duplicate fields, unknown fields/version,
fractional/unsafe sequence, checksum mismatch, unsupported kind, malformed
inner shape, and trailing outer tokens; valid vectors cover empty arrays and
non-ASCII UTF-8 payload hashing. This remains validator conformance evidence,
not proof that the production Java Sentinel Runtime source adapter exists.

#### Remaining implementation acceptance gates

The contract decisions are approved for implementation. Production managed
profile writes remain gated on provider publish/read-back, authenticated
receipt ingestion, durable Collector outbox/Console projection, and the
PostgreSQL/MySQL plus protected-GET acceptance matrix. Keep Console API 0.5.0
and Agent Reporting V1 unchanged.

### 4.4 Checksum-domain reconciliation and persistence implications

The approved architecture uses an **opt-in managed publication envelope**
stored atomically as the value for a Console-managed rule target. A source
adapter validates and unwraps the envelope, then passes only the native rule
array to the existing rule codec. This avoids a two-key update window between
rule bytes and a metadata sidecar, and works with the current provider
CAS/read-back boundary. It does **not** keep the same key directly consumable
by an old client; those bindings must remain on the legacy-native profile until
explicitly migrated to a metadata-aware source adapter.

The envelope candidate needs, at minimum, a contract/version discriminator,
the approved exact correlation tuple, a monotonically increasing per-binding
publication sequence (so rollback is a new, higher sequence, and stale reads
cannot silently replace a newer publication), the rule kind/profile, a
content-integrity checksum, and the native same-kind rule array. The
content-integrity checksum must exclude envelope metadata and be independently
recomputed by the source adapter. It is not automatically the Console target
version checksum or the source provider revision.

For the checksum candidate to be byte-verifiable without JSON parser
re-serialization, the envelope should carry the encoder output as a UTF-8 JSON
string value (the string's contents are the native JSON array text); the source
adapter hashes the decoded string's UTF-8 bytes, verifies the digest, and only
then parses those bytes as the native array. A cross-language primitive test
vector is input bytes `5b 5d` (`[]`) → SHA-256
`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. This is
an algorithm candidate, not a frozen envelope schema.

Current code has four distinct checksum/revision domains:

| Domain | Current calculation | Why it differs |
| --- | --- | --- |
| Console rule-version checksum | `candidate_checksum()` hashes normalized management records, including `recordId`, `kind`, typed values, and a `sha256:` prefix. This becomes `RulePublication.target_checksum`. | It identifies the immutable Console version, not the encoded provider bytes. |
| Sentinel Nacos source version checksum | `NacosRuleSource._load_snapshot()` hashes sorted `dataId=rawContent` lines and stores bare SHA-256 hex in `RuleVersion.checksum`. | It depends on provider key names and raw serialized content; it is not the Console candidate digest. |
| Managed target-payload checksum (candidate) | SHA-256 of the exact UTF-8 native rule-array bytes stored as the selected publication target's value, excluding envelope metadata. | It proves the bytes for one provider target. The same target bytes produce the same digest in Java/Python without re-serialization; its field encoding and receipt use are not frozen. |
| Nacos provider CAS revision | Nacos-owned MD5 of one exact config value, returned by the provider and used as the CAS token. | It identifies the current provider revision for one `namespace/group/dataId`; it is not the Console target digest or a cross-provider content checksum. |

This is not just a naming concern. The current SQL receipt writer requires an
`APPLIED` receipt's `loaded_checksum` to equal `RulePublication.target_checksum`
exactly, and the frontend's `publicationReceiptsMatch()` model validation
enforces the same equality before displaying a receipt page as consistent.
Therefore a runtime's existing source `RuleVersion.checksum` cannot simply be
copied into `loaded_checksum`; it uses a different prefix and input domain. In
particular, the current Nacos source checksum aggregates sorted
`dataId=rawContent` entries across up to five rule-kind keys, while one Console
publication writes one selected provider target. A single target-payload digest
is not the aggregate snapshot digest. The future receipt contract must define
which checksum the existing receipt field means and how the trusted adapter
proves it, or explicitly version the read contract before changing that
meaning. Never compare unlike checksum domains or claim that a matching
publication ID alone proves the loaded rule bytes.

#### Approved mapping preserving the current Console read contract

To preserve the frozen Console read contract, the current leading mapping is:

- Keep `RulePublication.target_checksum` / API `targetChecksum` as the existing
immutable Console version digest.
- At publication acceptance, compute and persist an internal
  `target_payload_checksum` as SHA-256 over the exact UTF-8 bytes returned by
  the selected profile encoder. The managed envelope must carry that exact
  payload without requiring the runtime to reserialize parsed JSON; the source
  adapter verifies the recovered raw payload bytes before decoding them. This
  per-target digest is independent of the envelope metadata, Console target
  version digest, Nacos CAS MD5, and aggregate `RuleVersion.checksum`.
- The runtime adapter recomputes that payload checksum before applying. The
  authenticated receipt reports the exact publication tuple, target version
  checksum, observed payload checksum, source revision, and process epoch.
- The trusted Collector/projection verifies the tuple against the publication,
  verifies the payload checksum against the persisted expected payload checksum,
  and only then maps the validated target version checksum to the existing
  receipt `loaded_checksum` field. The existing protected Console API 0.5.0
therefore remains unchanged; the reporting contract must retain both digest
  domains until that validation is complete.

This mapping is the approved D2/D6 mapping and is implemented by an internal
publication persistence field plus the independent authenticated receipt V1
envelope; it must not be implemented by silently relabeling
`RuleVersion.checksum`.

Identity/authentication still comes from the trusted transport, not the
envelope. The exact field names, checksum domains, sequence ownership,
byte/time bounds, and error taxonomy are frozen by the approved V1 contracts.

The Python source boundary currently combines multiple rule-kind data IDs into
one `RuleSnapshot`; publication provenance therefore cannot be a single
optional ID on that snapshot. The approved runtime model is a bounded immutable
tuple of per-target provenance facts, carried separately from `RuleVersion`
and preserved through the repository's atomic apply result. This atomic
rules-plus-provenance model is implemented; the production receipt hand-off
remains open. A metadata-only
publication with identical rule bytes must still produce an exact receipt
observation after the runtime proves the current canonical rules match; it
must not be lost by checksum-only poll coalescing. This requires an explicit
runtime fact/adapter path and the approved independent receipt contract, not a
change to frozen Agent Reporting V1.

**Design-pattern assessment:** the source-specific decoder is an **Adapter**
because it translates the managed Console envelope into the stable
`SnapshotRuleSource`/native rule-value contract. Keep it in the optional source
integration, not the Sentinel core; do not add Observer/Mediator fan-out. Any
receipt event should cross the existing reporting boundary through a narrow
Port/adapter, with bounded enqueue and no network work on Engine apply.

The path and contracts are approved for implementation. The exact operational
profile migration procedure remains explicit and must preserve a rollback to
native-array publication; it cannot be inferred from provider content.
Required executable cases include legacy-array
compatibility, malformed/foreign envelope rejection with last-known-good
retained, CAS/read-back mismatch, same-content distinct publications,
monotonic rollback, delayed stale payload after a newer apply, restart, and
Java/Python cross-language golden vectors.

## 5. Approved validation and persistence invariants

These approved D1–D7 invariants govern implementation; the exact independently
versioned receipt schema is specified in
[`RULE_PUBLICATION_RECEIPT_V1.md`](../protocols/RULE_PUBLICATION_RECEIPT_V1.md).

1. Authenticated principal resolves to one active enrolled runtime identity
   and allowed application/environment/source scope. Reject missing, revoked,
   or multiply-bound identity.
2. Receipt correlation resolves to exactly one existing publication and
   immutable target version under the same binding. Reject missing, foreign,
   superseded-without-policy, or ambiguous references; never query “latest” as
   a fallback.
3. Observed provider/source version and checksum must match the immutable
   publication's expected version semantics. Define explicitly whether a
   rejected application, stale source, or degraded runtime is a receipt or a
   different event; do not map arbitrary execution events to “applied.”
4. Duplicate delivery must be idempotent. Conflicting evidence for the same
   authenticated instance/publication is rejected or recorded as a separately
   governed state transition; arrival order alone must not erase newer
   authoritative state.
5. Runtime incarnation/epoch replacement and sequence ordering need a defined
   policy so delayed reports from a prior process cannot overwrite a newer
   instance state.
6. Persisted receipt and its idempotency/ingest acknowledgement must share a
   documented durability boundary. No success acknowledgement before durable
   commit.
7. Logs and errors exclude credentials, raw provider responses, and rule
   bodies.

## 6. Approved transport/deployment boundary

The approved path is a Collector-owned durable outbox consumed by a Console
projection worker. The Collector persists both the accepted receipt fact and
its delivery record before returning a durable ACK. The Console worker claims
outbox delivery, validates exact tuple/digest against Console publication
authority, performs an idempotent projection, and acknowledges delivery only
after the Console transaction commits. This boundary does not authorize
sharing a database between independently implemented services, adding an
unauthenticated browser API route, or changing Agent Reporting V1 transport
rules. Authentication and replay protection derive from the existing
authenticated enrollment authority, not envelope fields.

## 7. Required contract and acceptance evidence before implementation closes

- A versioned schema/contract with authenticated identity binding, exact
  publication correlation, allowed receipt states, time semantics, idempotency,
  conflict/stale behavior, bounds, and compatibility policy.
- D1–D7 implementation authority is recorded in §4.3 and the approved V1
  contracts. Console API 0.5.0 and Agent Reporting V1 remain unchanged unless
  a separate signed decision explicitly changes them.
- Unit/contract tests for unknown, revoked, foreign, ambiguous, repeated,
  stale-epoch, out-of-order, and conflicting receipt cases; assert no write on
  rejected correlation.
- PostgreSQL and MySQL acceptance through the selected trusted transport or
  projection path, proving durable write, idempotent acknowledgement, read-back
  through the existing protected Console GET, and no secret leakage.
- A running Sentinel instance → authenticated reporting authority → durable
  receipt → Dashboard read-back acceptance before B0.3 runtime receipt work can
  be closed. Mock-only or direct SQL-store tests are insufficient.

## 8. Required owner decisions

| Owner | Decision required | Status |
| --- | --- | --- |
| Product/API owner | Correlation, envelope, state family, explicit migration, transport proof boundary | **D1-D7 approved for implementation 2026-10-15** |
| Sentinel runtime owner | Python managed-profile Adapter, exact reference propagation, atomic rules/provenance apply | **Approved for implementation; code and runtime tests pending** |
| Collector/protocol owner | Independent authenticated receipt contract, Collector durable outbox and Console consumption | **Approved for implementation; code and durable acceptance pending** |
| Security/identity owner | Enrollment-derived identity/scope, revocation, replay defense | **Approved for implementation; code and negative tests pending** |
| Storage/deployment owner | Durable payload digest/sequence, idempotent projection and ACK boundaries | **Approved for implementation; migrations and PostgreSQL/MySQL acceptance pending** |

Until implementation acceptance passes, retain the current read-only Console
receipt API and do not guess or write a publication receipt from Reporting V1
events. T03.3 remains open until the exact authenticated receipt is durably
projected and read back.
