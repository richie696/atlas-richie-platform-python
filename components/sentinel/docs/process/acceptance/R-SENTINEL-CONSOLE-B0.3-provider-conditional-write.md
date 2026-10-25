# B0.3 — Provider conditional-write capability gate

Status: **provider evidence reviewed; real Consul CAS and Nacos 3.x update-CAS/create-only paths now have isolated provider and PostgreSQL/MySQL outbox acceptance evidence; production TLS/auth, broader provider-stage crash windows, instance activation, and the complete publication lifecycle remain open**.

## Evidence and decision boundary

## Publication-target resolver contract — focused test design

| Risk | Focused evidence | Required assertion |
| --- | --- | --- |
| Display `location` is mistaken for a writable key | Domain/port contract tests | Worker target lookup is by exact binding identity; display-only `location` is not accepted as Nacos `group/dataId` or Consul key. |
| Provider target fields are mixed | Value-object tests | Nacos target requires namespace/group/dataId; Consul target requires an exact KV key and cannot carry Nacos fields. |
| Untrusted target identity reaches provider adapter | Value-object tests | Empty, oversized, control-character, or malformed identity values are rejected before any transport call. |
| Missing or cross-binding mapping is treated as a default | Resolver contract test | Missing exact target remains unavailable; no synthesized default path or source-wide fallback is used. |
| Target mapping changes after command acceptance | SQL outbox/mutation integration test | Pending work freezes the exact provider target and its revision in the same transaction as the publication; worker never re-resolves a newer mapping. |
| Source endpoint/credential revision changes after command acceptance | SQL outbox/mutation integration test | Pending work also freezes the exact registered-source revision; provider execution must resolve credentials/configuration using that revision and must not silently redirect to the newer source revision. |
| Frozen source has been removed/changed or provider identity differs | Application resolver test | Resolve only the outbox's exact source ID/revision/provider; stale, absent, mismatched, and unresolved identities fail closed. |
| Frozen source uses an opaque deployment credential reference | Application resolver test | Resolve the reference for the frozen provider into ephemeral direct connection input; reject missing/wrong-provider credentials and do not expose secret values in representations or errors. |

These are source-tree contract tests only. They do not establish that a production
target registry has been composed or that either external provider is reachable.

## Console rule-profile payload encoder — focused test design

| Risk | Focused evidence | Required assertion |
| --- | --- | --- |
| Console management wrappers leak into the provider's same-kind JSON array | Pure mapper/encoder unit tests | Each version encodes as an array of native rule value objects; Console record IDs and `kind/value` wrappers are absent. |
| A typed Sentinel field is lost, renamed, or enum-coded incorrectly | Five-family field fixture tests | Flow, degrade, system, authority, and parameter-flow fields use the frozen camel-case schema and numeric enum values. |
| Provider payload bytes drift nondeterministically | Repeated encode test | Same immutable version yields byte-identical compact UTF-8 JSON; array order follows the immutable version order. |
| Unknown profile is mistaken for the built-in schema | Profile mismatch test | Encoder accepts only the exact composition-bound profile ID; mismatch is a finite unsupported-profile error. |
| Non-finite or semantically inactive fields are silently published | Negative validation tests | NaN/Infinity, flow cluster data while disabled, and irrelevant degrade ratio fields fail before transport. |

This is a local pure-codec contract. It does not claim Java client decoding or
Nacos/Consul persistence; those remain provider and final milestone evidence.

The Console publication contract requires an atomic provider-side conditional
write followed by read-back. A preflight GET followed by an unconditional PUT,
an in-process lock, or the Console database revision alone cannot protect
against another Dashboard or an operator writing directly to the same source.

| Provider | Officially documented fact | Current consequence |
| --- | --- | --- |
| Nacos 3.x Admin HTTP API | `Get Config` returns `md5` and `modifyTime`; the documented Admin HTTP `Publish Config` parameters do not expose expected-revision / compare-and-set. | This HTTP endpoint alone is insufficient for provider-side CAS. Do not pre-read `md5` and then call unconditional HTTP publish. |
| Nacos 3.x SDK gRPC publish | `nacos-sdk-python` 3.x exposes `ConfigParam.cas_md5`; its gRPC publish request carries `casMd5`, which the Nacos server forwards into conditional persistence. | A supported conditional primitive exists in the SDK/gRPC path. It is a viable implementation candidate, but Console publication remains unavailable until an adapter preserves deployment target pinning/TLS identity, freezes namespace/group/dataId mapping, verifies create semantics, classifies outcomes and proves exact read-back. |
| Consul KV | `PUT /v1/kv/:key` has `cas`; index `0` creates only when absent, and non-zero index must match that key's `ModifyIndex`. | A Consul writer can implement the existing CAS contract, provided it uses the key's exact `ModifyIndex`, verifies the boolean response and performs a separate exact read-back. |

Primary documentation reviewed 2026-10-09:

- [Nacos 3.x Admin API — Get Config / Publish Config](https://nacos.io/en/docs/latest/manual/admin/admin-api/)
- [nacos-sdk-python repository](https://github.com/nacos-group/nacos-sdk-python) — SDK 3.x compatibility and `cas_md5` API.
- [Nacos Python SDK gRPC publish implementation](https://github.com/nacos-group/nacos-sdk-python/blob/master/v2/nacos/config/remote/config_grpc_client_proxy.py) — `casMd5` request field.
- [Nacos Java ConfigService](https://github.com/alibaba/nacos/blob/develop/api/src/main/java/com/alibaba/nacos/api/config/ConfigService.java) — `publishConfigCas` contract.
- [Consul KV HTTP API — Create/Update Key](https://developer.hashicorp.com/consul/api-docs/kv)

This is a documentation-based capability assessment, not a live server test.
The Nacos conclusion is deliberately scoped to the documented Admin API: it is
not a claim that no private extension or future server API could ever provide
CAS. Any such alternative must be supported, versioned, and verified before it
can satisfy the Console contract.

### Python SDK 3.2.0 implementation seam (2026-10-09)

The SDK source was inspected from the locally cached `nacos-sdk-python==3.2.0`
distribution and cross-checked against the upstream gRPC publish implementation.
The `cas_md5` publish field is real, but it does not by itself make the SDK a
suitable Console transport:

- `ConfigParam.cas_md5` is forwarded to the gRPC `ConfigPublishRequest.casMd5`.
- The public `NacosConfigService.get_config()` returns only content. Its internal
  query receives the server response MD5 but discards it, so the public surface
  cannot supply the server-authoritative CAS baseline required by the worker.
- The SDK constructs its own gRPC channel and its own auth client/background
  refresh path. There is no supported public injection seam for the Console's
  DNS-pinned transport and exact TLS identity policy. Replacing private
  transports after construction would leave part of the auth path outside that
  policy; monkeypatching SDK internals is not an acceptable production adapter.
- SDK TLS configuration supports CA/client certificate material, but the
  inspected implementation does not apply its declared TLS server-name override
  to the gRPC channel options. This matters when connecting to a deployment-pinned
  IP while validating the configured hostname.

Therefore **do not implement the Console Nacos writer by simply calling the
public SDK**, by doing Admin HTTP pre-read followed by publish, or by patching
private SDK internals. At the time of this 2026-10-09 assessment, publication
was to remain fail-closed until a maintainable, pinned transport and a verified
create path existed. That constraint was subsequently addressed without
fabricated MD5 sentinels or SDK-private patching: existing-key updates use the
Console's minimal versioned gRPC transport with provider MD5 CAS; absent-key
creation uses the one-item Admin Import `policy=ABORT` operation followed by
exact Admin read-back. The source-level warning remains valid: a non-CAS Admin
upsert or a synthetic MD5 is not an acceptable substitute.

#### Additional public-API limitations verified against SDK 3.2.0 / Server 3.2.3

The SDK's public read contract has two further constraints relevant to the
publication worker:

- `NacosConfigService.get_config()` checks the SDK failover cache before it
  queries gRPC. `disable_use_config_cache` only prevents the later fallback to
  the ordinary local cache after a server error; it does not bypass that
  initial failover-cache lookup. Therefore a returned string is not, by itself,
  proof that the baseline came from the current server response.
- The SDK maps the server's “not found” response to an empty string, while its
  public method also returns only content. The caller cannot obtain the query
  response's MD5 or an explicit existence fact through this method. It must not
  infer an authoritative absent-key state or CAS revision from `""`.
- Nacos Server 3.2.3 enters `insertOrUpdateCas` only when `casMd5` is nonblank.
  A blank value follows the non-CAS path (`updateForExist` upsert or
  create-only insert). Passing a blank `cas_md5` is therefore not a CAS call;
  exact create-only behavior must be independently established for the chosen
  SDK/server request contract.

These findings ruled out the SDK public read/cache surface as the source of
authoritative existence/content/MD5 facts. The current Console adapter instead
uses a conditional gRPC update for an existing provider revision and the
documented Admin Import `ABORT` policy for create-only, followed by exact
read-back in both paths. Disposable Nacos 3.2.3/3.2.4 reader/writer tests and
Nacos 3.2.4 SQL-outbox acceptance cover duplicate/competing creators; separate
PostgreSQL 16 and MySQL 8.4.11 outbox acceptances cover create-only completion
(see the 2026-10-10 and 2026-10-12 evidence below and tracker §§15.935/15.946).
SDK cache flags are not used as proof of provider state. Production TLS/auth,
cluster/storage consistency, and the remaining failure windows are still open.

#### Create-only CAS source review (2026-10-10)

The Nacos 3.2.3 server source adds an important implementation detail, but not
a stable client contract: `ConfigOperationService.publishConfig` routes a
nonblank `casMd5` to `insertOrUpdateCas`; the external persistence adapter
checks whether the key exists, inserts when it does not, and on the existing
key path applies the expected MD5 in the update predicate. The insert path
computes and stores the candidate content's actual MD5. This means a fabricated
nonblank value may appear to provide create-only behavior on this exact server
implementation, while a blank value is explicitly non-CAS.

The Console will **not** send a malformed or fabricated MD5 sentinel to depend
on that behavior. The public `publishConfigCas` contract describes `casMd5` as
the previous content's MD5; the documented Nacos 3 Admin Publish API is an
upsert, and its Import API only lists a policy field/default without specifying
an atomic create-only contract. The source-level `find`-then-insert behavior
and its duplicate-key handling are implementation details, not a versioned
cross-server guarantee for all supported stores. Therefore `expected_revision=None`
continues to be rejected before dispatch. An implementation may be reconsidered
only after an official/versioned create-if-absent contract is identified and
validated against the supported Nacos server/storage matrix, including
concurrent creators and exact read-back.

Sources reviewed:

- [Nacos 3.2.3 `ConfigOperationService`](https://github.com/alibaba/nacos/blob/3.2.3/config/src/main/java/com/alibaba/nacos/config/server/service/ConfigOperationService.java) — nonblank `casMd5` selects `insertOrUpdateCas`; blank selects non-CAS publish.
- [Nacos 3.2.3 `ExternalConfigInfoPersistServiceImpl`](https://github.com/alibaba/nacos/blob/3.2.3/config/src/main/java/com/alibaba/nacos/config/server/service/repository/extrnal/ExternalConfigInfoPersistServiceImpl.java) — missing-key insert and existing-key MD5 predicate.
- [Nacos Admin API](https://nacos.io/en/docs/latest/manual/admin/admin-api/) — regular Publish is documented as updating an existing config; Import lists `policy=ABORT` but does not specify the conditional-create guarantee required here.
- [Nacos Java `ConfigService`](https://github.com/alibaba/nacos/blob/develop/api/src/main/java/com/alibaba/nacos/api/config/ConfigService.java) — `publishConfigCas` takes the previous config MD5.

This is source/documentation review only. No Nacos endpoint was contacted, and
it did not close the create-only acceptance item at that point in the review.
The later disposable provider and PostgreSQL/MySQL SQL-outbox tests below
supersede this status; the source-review warning about not fabricating MD5
sentinels remains in force.

#### Follow-up: official single-item import `ABORT` candidate (2026-10-10)

Current Nacos Admin API documentation exposes `POST /nacos/v3/admin/cs/config/import`
with a `policy` request field (default `ABORT`). The official Nacos 3.2.4
`SameConfigPolicy` enum defines `ABORT` as aborting import on a duplicate. The
3.2.4 controller passes this policy into `batchInsertOrUpdate`; both the
external and embedded persistence implementations attempt an insert and treat
the uniqueness conflict as the duplicate outcome. The batch implementation is
not an all-items transaction: earlier items can remain published if a later
item conflicts. A Sentinel create command can nevertheless use a **one-item**
archive, where there is no earlier candidate item to partially publish.

This is a newly identified official-API candidate, not yet accepted as a
production contract. Before implementation is considered safe, a disposable
Nacos 3.2.4 acceptance must establish: (1) one-item `ABORT` creates the absent
exact namespace/group/dataId; (2) a second one-item import with different
bytes reports conflict and does not overwrite; (3) concurrent creates have at
most one winner; (4) success requires exact Admin API read-back; and (5) a
timeout after dispatch remains outcome-unknown with no blind retry. Nacos
version/storage coverage and any documented API contract remain explicit
limitations. The request must use the Console's pinned HTTP target, validated
TLS identity and ephemeral access-token header; ordinary publish or a
pre-read followed by upsert remains prohibited.

Sources reviewed:

- [Nacos Admin API: Import and Publish Configs](https://nacos.io/en/docs/latest/manual/admin/admin-api/) — v3 import endpoint and `policy` parameter.
- [Nacos 3.2.4 `ConfigControllerV3`](https://github.com/alibaba/nacos/blob/3.2.4/config/src/main/java/com/alibaba/nacos/config/server/controller/v3/ConfigControllerV3.java) — import parses the archive, then passes `policy` to `batchInsertOrUpdate`.
- [Nacos 3.2.4 `SameConfigPolicy`](https://github.com/alibaba/nacos/blob/3.2.4/api/src/main/java/com/alibaba/nacos/api/config/model/SameConfigPolicy.java) — `ABORT` is documented as abort-on-duplicate.
- [Nacos 3.2.4 external config persistence](https://github.com/alibaba/nacos/blob/3.2.4/config/src/main/java/com/alibaba/nacos/config/server/service/repository/extrnal/ExternalConfigInfoPersistServiceImpl.java) and embedded implementation — duplicate uniqueness failures select the `ABORT` path.

Evidence is official docs/source inspection only. No Nacos endpoint was contacted
for this follow-up.

### Nacos 3.x Console gRPC update adapter (2026-10-10)

The Console now has a minimal local Nacos gRPC transport instead of relying on
the SDK's private client/channel implementation:

- `NacosGrpcTransport` constructs the official `Payload`/`Metadata` protobuf
  wire fields locally, sends `ServerCheckRequest`, then opens the official
  `BiRequestStream/requestBiStream` and sends `ConnectionSetupRequest` before
  issuing one unary `ConfigPublishRequest`. It keeps the stream alive while the
  unary request is active and drains server responses; when capability
  negotiation is advertised it waits for `SetupAckRequest` and sends the
  matching `SetupAckResponse` with the original request ID; otherwise it uses
  the SDK's 100 ms registration-settle interval. A setup/registration failure
  is classified as unavailable before dispatch, so it cannot be mistaken for
  an uncertain config write. The protobuf message/field names and numbers were
  compared with the cached `nacos-sdk-python==3.2.0` generated descriptor and
  round-trip checked with its installed protobuf runtime. It does not import
  `v2.nacos` implementation types.
- It dials an already-resolved IP, preserves the configured hostname as gRPC
  TLS target authority, and requires a separate explicit target-policy grant
  for the standard gRPC port offset (`HTTP port + 1000`). The port conversion
  reuses the same approved DNS answer set; it does not resolve the hostname a
  second time. Standard system trust roots are used for TLS. Custom CA and
  client-certificate configuration are not yet represented by the Console
  source model and remain an integration limitation.
- Direct Nacos username/password are exchanged using the existing pinned HTTP
  login helper; the short-lived `accessToken` is passed only in the gRPC request
  headers. It is not persisted or included in adapter exception text. The
  request sends a non-empty provider MD5 in `casMd5`, and the documented Nacos
  resource-conflict error code (`20005`) maps to a publication conflict.
- Only an existing exact config with a valid provider MD5 can be updated.
  `expected_revision=None` is rejected before transport: Nacos 3.2.3 treats a
  blank `casMd5` as non-CAS publish, so this adapter does not create keys. An
  operator must pre-provision the exact namespace/group/dataId and the Console
  must read its current provider MD5 before an update is accepted. Initial
  create-only support remains open; do not interpret this update-only adapter
  as full Nacos publication support.
- A successful gRPC acknowledgement is not the receipt. The adapter performs
  the existing exact Admin HTTP read-back and accepts a receipt only when both
  candidate bytes and their MD5 match. Any dispatched transport error or
  mismatched/unavailable read-back is `outcome-unknown`; no write retry occurs.
- The `nacos-grpc` project extra declares `grpcio` and `protobuf`; the Console's
  base install remains free of these dependencies. The explicit Nacos worker
  composition is available, but deployment must inject a target policy granting
  both provider ports and install the optional extra.

Focused verification on 2026-10-10:

- Console writer/provider/reader, source policy, worker composition, and router
  tests: **43 passed, 4 skipped, 3 loopback tests deselected**. Under the cached
  Nacos SDK environment, writer + gRPC wire/connection-setup tests passed
  **12/12**; protobuf field names/numbers also matched the SDK 3.2.0 generated
  descriptor. The fake-channel test asserts ServerCheck → bidirectional setup →
  unary CAS ordering, and proves that missing setup acknowledgement blocks the
  config-write dispatch. Negotiated setup also asserts the ack response payload
  and echoed request ID.
- `compileall` and `git diff --check` passed. No live Nacos endpoint, network
  gRPC handshake, real TLS certificate, or provider persistence was exercised;
  this is local transport/contract evidence only. B0.3 remains unchecked.

Primary source evidence reviewed 2026-10-09:

- [Nacos Python SDK 3.2.0 `NacosConfigService`](https://github.com/nacos-group/nacos-sdk-python/blob/3.2.0/v2/nacos/config/nacos_config_service.py) — failover-cache-first `get_config`, local-cache fallback behavior, and content-only result.
- [Nacos Python SDK 3.2.0 `ConfigGRPCClientProxy`](https://github.com/nacos-group/nacos-sdk-python/blob/3.2.0/v2/nacos/config/remote/config_grpc_client_proxy.py) — server query response cache update, not-found-to-empty mapping, and `cas_md5` forwarding.
- [Nacos Server 3.2.3 `ConfigOperationService`](https://github.com/alibaba/nacos/blob/3.2.3/config/src/main/java/com/alibaba/nacos/config/server/service/ConfigOperationService.java) — nonblank `casMd5` selects CAS; blank value follows a non-CAS write branch.
- [Nacos remote connection lifecycle specification](https://github.com/alibaba/nacos/blob/develop/specs/zh-cn/design/foundation-remote-connection-spec.md) — unary requests require a registered gRPC connection; `ConnectionSetupRequest` is sent over the bidirectional stream and capability negotiation may return `SetupAckRequest`.
- [Nacos Python SDK 3.2.0 `GrpcClient`](https://github.com/nacos-group/nacos-sdk-python/blob/3.2.0/v2/nacos/transport/grpc_client.py) — `ServerCheckRequest` → bidirectional connection setup, negotiated setup acknowledgement, and the 100 ms registration-settle behavior.

Evidence source: cached SDK 3.2.0 source files `v2/nacos/config/model/config_param.py`,
`v2/nacos/config/remote/config_grpc_client_proxy.py`,
`v2/nacos/config/config_service.py`, `v2/nacos/transport/grpc_client.py` and
`v2/nacos/transport/nacos_server_connector.py`; upstream publish mapping is
[Nacos Python SDK ConfigGrpcClientProxy](https://github.com/nacos-group/nacos-sdk-python/blob/master/v2/nacos/config/remote/config_grpc_client_proxy.py).
This is source inspection only; no external Nacos instance was contacted.

## Implementation guardrails

- Keep candidate validation, source write, source read-back, and runtime receipt
  as separate facts.
- Do not substitute Nacos `md5` pre-read + ordinary publish for CAS; the
  read/write race remains open.
- Consul CAS must distinguish create (`cas=0` only when the key is absent) from
  update (exact non-zero `ModifyIndex`). A false response is a source conflict,
  not a retryable success.
- The current Consul adapter validates the target through the existing pinned
  source policy, sends one raw KV payload with exact `cas`/`dc`, rejects false
  acknowledgements as conflicts, and requires a metadata read-back whose exact
  key, bytes and strictly advanced `ModifyIndex` match before returning a
  receipt. Its caller must provide already-resolved direct credentials; token
  references and source-registry revisions are not interpreted as KV indices.
- A timeout or malformed response after dispatch is an unknown write outcome;
  reconcile only by the original operation identity and exact target. Never
  blindly replay the write.
- Provider tests use a controlled HTTP seam; milestone acceptance must also
  exercise supported real Consul and Nacos deployments. This record did not
  contact either service.

## Conditional-write verification matrix

| Risk | Focused evidence | Milestone-only evidence |
| --- | --- | --- |
| Lost update | Controlled Consul CAS accepts exact index and rejects stale index; false response creates no completed publication. | Two independent writers race against a disposable Consul key; at most one base revision wins. |
| Create-vs-update confusion | Absent key uses create-only CAS; existing key never uses index zero. | Repeat against each supported Consul version/profile. |
| Uncertain response | Timeout/malformed response remains unknown and keeps original request key locked; no automatic second PUT. | Fault-injected real endpoint with server-side outcome reconciliation. |
| Nacos safety | Local adapter contract verifies registered-connection setup precedes gRPC CAS; stale MD5 conflict and exact read-back are tested without blind retry. Create-only remains unsupported. | Verify create-only vs update semantics, stale-MD5 conflict, exact read-back, pinned endpoint/TLS and SDK/server version matrix against an isolated supported Nacos server. |
| Read-back | Exact key/data-id and payload checksum are verified independently of write acknowledgement. | Cross-client read-back against real provider. |

## Exact Consul snapshot read slice

- `infrastructure/consul_rule_source_reader.py` now provides an independent,
  read-only exact-key observation for future publication recovery. It returns
  absent-key separately from an existing key, preserves raw value bytes outside
  object representations, validates the returned key and `ModifyIndex`, and
  uses the same pinned target policy as writes.
- Reader and writer now share key encoding, key validation, datacenter query,
  revision bounds, and exact KV response decoding through
  `consul_rule_source_support.py`; the reader no longer imports private helpers
  from the writer and both paths enforce the same key/value/ModifyIndex rules.
- Focused reader + writer tests: **13 passed** using a controlled transport,
  including the distinction between an absent key and an existing empty value.
- Transport normalization is limited to `aiohttp.ClientError`, `OSError`, and
  `TimeoutError`. Unexpected adapter/programming exceptions propagate instead
  of being reported as ordinary provider unavailability or an unknown write.
  The two explicit propagation checks are included in the 13 focused tests.
- The SQL publication reader/phase recorder now persists complete three-phase
  publication facts, validates frozen version ownership/checksum on creation,
  and compare-and-sets one monotonic phase at a time. The reader is assembled
  for production SQL app reads. A later slice adds an atomic pending
  `PublishRuleVersion` receipt, secret-free work payload, and initial phase fact;
  the durable operation is accepted but not yet claimed or executed. B0.3
  remains open; no real Consul was contacted.

### Current local implementation evidence (2026-10-09)

- `domain/rule_publication_targets.py` now defines separate immutable Nacos and
  Consul target facts; `RulePublicationTargetReader` is a binding-scoped,
  consumer-owned port. Migration `0013_rule_publication_targets` and the SQL
  reader persist/resolve an exact mapping revision plus the registered-source
  revision, and verify that the registered source still exists at that exact
  revision with the same provider. Production SQL mutation composition now uses this reader. Publish
  schema V2 freezes both revisions and the provider target in the same
  transaction as the pending operation; a later mapping/source revision change
  does not retarget already accepted work. There is not yet an authorized
  mapping write/API flow or provider worker, so the reader cannot yet be
  provisioned through the Dashboard and the provider path remains unavailable.
  A trusted server-side SQL writer now supports create-only and expected-revision
  updates after checking the current registered-source revision/provider. It is
  deliberately not an authorization boundary and must not be mounted directly
  as an HTTP endpoint; the admin/CSRF/idempotency/audit workflow is still open.
  The focused mutation/publication/target suite passed **50 tests** after this
  slice, with Python `compileall`; no browser or provider was contacted.

- `application/resolve_registered_source_connection.py` now provides the
  exact-revision connection-resolution use case. A worker supplies only the
  frozen source ID/revision/provider from its outbox claim; stale identities
  fail closed, and an opaque credential reference is resolved ephemerally by
  the deployment-owned resolver. The resolver + source-check API focused
  command passed **12 tests**, including wrong-provider and sanitized-secret
  failures. This does not itself execute a provider request.

- `application/rule_value_projection.py` is the shared camel-case value
  projection used by both Console snapshot responses and
  `infrastructure/sentinel_rule_version_encoder.py`. The encoder emits an
  immutable version as a native same-kind JSON array without Console record IDs
  or API discriminators and rejects mismatched profile/conditional fields.
  Five-family schema, finite-number, order, and failure cases plus rule read and
  validation API regression passed **30 tests**. This is local mapping evidence,
  not Java/Nacos/Consul compatibility evidence.

- `infrastructure/consul_rule_source_writer.py` implements create-only/update CAS,
  no automatic retry, finite conflict/rejected/unknown outcomes, and exact
  metadata read-back. The raw transport reuses the existing DNS-pinned,
  redirect-disabled, TLS-validating source HTTP client.
- `tests/test_consul_rule_source_writer.py`: **7 passed**, covering create CAS
  zero, exact update index, stale conflict without retry, mismatched read-back,
  timeout after dispatch, target-policy rejection before HTTP, unexpected
  programming-error propagation, validation bounds and secret-free repr. These
  tests use a controlled in-process transport, not a real Consul server.
- SQL publication persistence now has focused coverage in
  `tests/test_rule_publication_reader.py`: create validates the exact immutable
  target version/checksum, history/detail reads are binding scoped, and phase
  writes reject stale expected state or illegal transitions. The migration,
  SQL composition, and publication API tests total **24 passed** in the latest
  phase-recorder run.
- The latest durable-command slice validates immutable target version/checksum,
  profile and publishable validation receipt; checks a supplied baseline version
  and checksum; then commits the pending operation, baseline work payload,
  initial publication record and audit fact together. Original request-key
  replay returns the same pending operation. Its focused mutation/parser/HTTP
  command/publication suites total **39 passed** after migration
  `0011_rule_publish_outbox`; this does not prove worker recovery.
- The latest outbox slice adds migration `0012_rule_publish_leases` and a SQL
  claim adapter. It atomically leases the oldest pending publish commands,
  bounds batches/lease duration, increments attempts, and replaces the claim
  token when an expired lease is recovered. A worker can CAS-renew a still-live
  lease using both the current token and prior expiry; reusing a superseded
  lease object conflicts. It does not invoke a provider or
  complete operations. Phase writes now require the current claim token and a
  non-expired lease, so a worker superseded after lease expiry cannot persist a
  late phase result; this does not fence an already-dispatched provider call.
- The same outbox now has terminal transitions under the active claim. Success
  requires all three persisted publication phases to be `succeeded`, then
  commits the completed operation snapshot, clears transient work/lease data,
  and inserts one completion audit fact in a single SQL transaction. A known
  failed phase may reject the operation only when no phase is `unknown`; it
  stores a finite rejection reason, clears transient work/lease data, preserves
  the publication phase facts, and inserts one rejection audit fact. Original
  actor/session operation lookup reconstructs the successful receipt or finite
  rejection; repeated terminal transitions conflict.
- Application orchestration now exists in `application/run_rule_publication_worker.py`.
  It verifies frozen claim/version/publication identity, encodes the candidate
  and expected baseline, resolves only the frozen source revision, compares
  exact current bytes before CAS, records the three lifecycle phases, and
  completes only after exact read-back. An ambiguous write is recorded as
  `unknown`; a later claim reads remote state and can resolve it without
  issuing a second write. `RulePublishWorkClaim` now belongs to the application
  publication Port instead of the SQL adapter. Focused worker, SQL outbox,
  publication-reader and encoder tests: **27 passed**. The worker is not yet
  composed into the running service.
- `infrastructure/consul_rule_publication_provider.py` adapts the frozen
  Consul KV key, exact value bytes and ModifyIndex CAS revision to that worker
  Port. It reuses the existing pinned/TLS-safe reader and CAS writer and maps
  provider outcomes to sanitized application errors. Worker/provider adapter,
  Consul reader/writer, SQL publication/outbox and encoder tests: **42 passed**.
  This is controlled-collaborator evidence, not a live Consul test.
- The mutation/publication API focused suite now reports **39 passed** after
  this terminal-failure transition. Tests use isolated SQLite and controlled
  facts; they do not contact a provider.
- Additional worker acceptance coverage remains required for: reject a stale
  claim or cross-binding/version/checksum/profile mismatch before any write;
  resolve only frozen source/target revisions; compare exact encoded baseline
  bytes before CAS; treat dispatched-write ambiguity as `unknown` and reconcile
  the exact remote state on reclaim instead of blindly retrying; persist
  validation/write/read-back transitions separately; allow completion only
  after exact candidate read-back under the current claim fence; and prove
  provider errors persist only finite sanitized reasons, never endpoint,
  credential, payload, or raw exception text. Current in-memory orchestration
  tests prove selected state decisions only, not SQL concurrency, HTTP
  transport, or real-provider acceptance.
- Remaining: compose the worker and Consul adapter into the service runtime;
  implement an authorized, audited target provisioning workflow; then
  reconcile process-crash/lease-expiry cases under actual SQL concurrency;
  implement the Nacos SDK gRPC CAS adapter with deployment-pinned target/TLS
  identity and confirmed create semantics; exercise the Nacos production HTTP
  read transport against a controlled local endpoint; and run two-writer/read-back
  acceptance against disposable real providers (Consul single-writer create,
  update and stale-CAS are now covered below). Nacos stays non-publishable
  until SDK gRPC CAS is integrated with the Console's transport-safety,
  key-mapping and receipt contracts.

No browser E2E was run; it remains reserved for the final acceptance milestone.

### Nacos gRPC private trust roots and mutual-TLS client credentials (2026-10-11)

The Console now accepts deployment-owned Nacos gRPC channel credentials through
`NacosGrpcTlsCredentials`. The value object is immutable, excludes key bytes
from `repr`, and requires a client certificate chain and private key together.
`NacosGrpcTransport` passes the optional trust bundle and client identity to
`grpc.ssl_channel_credentials`; an explicitly configured TLS identity cannot
be used with a plaintext target. HTTP/Admin `SSLContext` remains a separate
configuration path because aiohttp and gRPC consume different credential APIs.

First-run deployment configuration reads optional absolute PEM paths from
`SENTINEL_CONSOLE_NACOS_GRPC_ROOT_CERTIFICATE`,
`SENTINEL_CONSOLE_NACOS_GRPC_CLIENT_CERTIFICATE`, and
`SENTINEL_CONSOLE_NACOS_GRPC_CLIENT_PRIVATE_KEY`. These values are accepted
only with the Nacos publication provider and injected through the existing
worker composition into the infrastructure transport. File contents are not
included in configuration or credential representations.

Acceptance uses a generated, in-memory certificate authority and a local gRPC
TLS server bound only to `127.0.0.1`. The real gRPC channel completed an mTLS
handshake using the private root and client identity, then completed the Nacos
connection setup and unary publish envelope. A wrong CA and missing client
identity were rejected before a publish request reached the server. Focused
composition/configuration tests also verified the environment-file-to-worker
path and the no-plaintext-downgrade invariant. The focused command was:

```sh
uv run pytest \
  tests/test_nacos_grpc_transport_protocol.py \
  tests/test_nacos_grpc_tls_acceptance.py \
  tests/test_first_run_deployment_configuration.py \
  tests/test_rule_publication_worker_composition.py \
  tests/test_first_run_composition.py -q
```

Result: **32 passed**. `compileall`, Ruff `F/I` checks, Ruff format check, and
`git diff --check` passed for the changed files.

This proves local gRPC TLS/mTLS channel behavior, not Nacos 3.2.4's server-side
gRPC TLS listener configuration or a deployed Nacos TLS endpoint. A production
Nacos TLS acceptance and its deployment-specific listener/CA rotation remain
open; no shared Nacos instance was contacted.

### Nacos 3 exact Admin API read adapter (2026-10-10)

The Console now has `infrastructure/nacos_rule_source_reader.py`, a read-only
adapter for the official Nacos 3 `GET /nacos/v3/admin/cs/config` endpoint. It
uses the existing registered-source DNS allowlist and pinned HTTP transport,
shares the ephemeral direct-credential exchange with the registered-source
probe, requests exactly one frozen namespace/group/dataId, and returns only the
server's content bytes plus its MD5 revision. The adapter verifies the response
identity and recomputes MD5 over UTF-8 content before exposing that revision to
publication orchestration. Config content is excluded from object reprs; auth
tokens remain in the `accessToken` header and are size/ASCII/control-character
bounded.

The reader deliberately treats HTTP 404 and every unrecognized response as
unavailable, not as proof that the key is absent. At this reader-only slice,
it did not enable Nacos publication: it was not wired as a complete
`RulePublicationProvider`, did not issue gRPC CAS, and did not solve Nacos
create-only semantics. Later slices added update-CAS and create-only adapters
and verified them against disposable Nacos servers; this historical note is
retained to describe the reader's original boundary, not the current status.

Focused tests are in `tests/test_nacos_rule_source_reader.py` and
`tests/test_registered_source_checker.py`. The non-loopback controlled-transport
selection passed **26 tests** after this slice. Three loopback tests were
deselected because this execution sandbox denies binding local listening
sockets; no real Nacos/Consul server was contacted. The official endpoint and
response fields are documented in the [Nacos Admin API](https://nacos.io/en/docs/latest/manual/admin/admin-api/).

### Disposable Consul 1.21.1 create/update/stale-CAS acceptance (2026-10-10)

Opt-in acceptance tests start their own `hashicorp/consul:1.21.1` dev container
with a loopback-only ephemeral port and no mounted volume. They construct the
real `ConsulRuleSourceWriter` and `ConsulRuleSourceReader` with a target policy
limited to that exact loopback address and port, then:

- creates a uniquely named KV key with CAS index `0` and verifies the exact
  stored bytes and returned `ModifyIndex`;
- updates only against that returned index and confirms the provider revision
  advances;
- retries using the now-stale create revision, requires a CAS conflict, and
  confirms the newer bytes and revision remain unchanged.
- gates two independent create-only writer calls at the HTTP boundary so both
  issue CAS `0` against the same absent key; exactly one must succeed, the other
  must receive conflict, and the final read must match the accepted candidate
  and its receipt revision.

Run it with:

```sh
SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 \
  .venv/bin/python -m pytest -q tests/test_consul_rule_source_writer_acceptance.py
```

Both tests passed against isolated real Consul containers. The default test run
skips these opt-in acceptances so it never starts a provider implicitly;
teardown force-removes only each uniquely named test container and the
container's `--rm` policy leaves no persisted KV data. This verifies Consul
server-side create/update/stale-CAS and two competing create-only writers; it
does not prove ACL/TLS configuration, production deployment allowlists, the
Nacos provider, or the complete SQL publication workflow.

### Disposable Nacos 3.2.4 update-CAS acceptance (2026-10-10)

An opt-in test now exercises the production `NacosRuleSourceReader` and
`NacosRuleSourceWriter` against an isolated `nacos/nacos-server:v3.2.4`
container. The container has no mounted volume; Admin and client auth are
disabled only for this synthetic local acceptance. Its HTTP and gRPC ports are
published to loopback only (`18848` and `19848`), matching the adapter's
HTTP-port-plus-1000 policy. The test guard rejects any endpoint other than an
explicit `http://127.0.0.1:<port>` URL.

The test creates a UUID-named config through the Nacos 3 Admin API, reads its
server MD5 through the production reader, updates it through the production
gRPC CAS transport, and verifies exact content/MD5 read-back. A second writer
using the stale original MD5 must report conflict, after which the reader
confirms that the first candidate remains unchanged. The unique test key is
deleted during teardown; the exact disposable container is removed after the
run.

This run exposed a real response-contract mismatch: Nacos 3.2.4 returns a
`ConfigPublishResponse` with `resultCode=500`, `errorCode=500`, and the stable
CAS-conflict message, not the older `errorCode=20005` envelope assumed by the
adapter. The writer now recognizes both explicit forms and continues to
classify other failures as unknown. The upstream 3.2.4 source throws
`NacosApiException` with `ErrorCode.RESOURCE_CONFLICT` for a failed non-gray
CAS, using that exact message; this classification does not rely on all
status-500 responses being conflicts.

Verification:

```sh
SENTINEL_NACOS_ACCEPTANCE_URL=http://127.0.0.1:18848/nacos \
  .venv/bin/pytest -q -vv tests/test_nacos_rule_source_writer_acceptance.py
.venv/bin/pytest -q tests/test_nacos_rule_source_writer.py
```

Results: real Nacos acceptance **1 passed**; focused writer suite **10 passed**.
The test uses auth-disabled loopback HTTP and plaintext gRPC, so it does not
verify production credentials, TLS identity/custom CA, cluster consistency,
create-only CAS, SQL worker recovery, or instance-level rule activation. Those
remain open; this acceptance does not close B0.3.

Primary source: [Nacos 3.2.4 `ConfigOperationService`](https://raw.githubusercontent.com/alibaba/nacos/2c587c0/config/src/main/java/com/alibaba/nacos/config/server/service/ConfigOperationService.java), which selects `insertOrUpdateCas` for nonblank `casMd5` and returns the explicit CAS conflict error when the provider MD5 no longer matches.

### SQL outbox → Nacos 3.2.4 update-CAS worker acceptance (2026-10-10)

The opt-in `test_nacos_worker_publishes_sql_outbox_to_real_nacos` acceptance
now covers the complete local update path: persist an immutable baseline and
candidate version in the SQL mutation store, seed the exact encoder-produced
baseline bytes into a disposable Nacos config, accept a publish command against
the baseline MD5, execute the production Nacos worker composition, and verify
the completed operation/publication plus exact provider read-back. A repeated
worker run is a no-op and does not change the Nacos MD5. The test also checks
that the operator reason is not exposed in the public operation representation.

The first run correctly rejected an invalid fixture: it had inserted arbitrary
Nacos JSON while asking the worker to publish from an empty SQL baseline. The
fixture now creates a real SQL `version-nacos-baseline` and writes its exact
`SentinelRuleVersionJsonEncoder` output to Nacos before accepting the candidate.
No production behavior was weakened to make the test pass.

Verification:

```sh
SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 \
  uv run --no-sync --extra test --extra nacos-grpc pytest -q \
  tests/test_rule_mutation_store.py -k nacos_worker_publishes_sql_outbox_to_real_nacos
```

Result: **1 passed, 29 deselected** against a test-owned `nacos/nacos-server:v3.2.4`
container; the test binds only loopback, uses no volume, and removes the exact
container and unique config in teardown. The test file compiles and
`git diff --check` passes. This closes only the local SQL outbox → existing-key
Nacos CAS → exact read-back slice. It does not prove production TLS/auth,
create-only behavior, PostgreSQL/MySQL with Nacos, crash recovery during a
provider side effect, instance activation, or B0.3 as a whole.

### Nacos 3.2.3/3.2.4 create-only and SQL outbox acceptance (2026-10-10)

The create-only writer now uses the Nacos 3.x single-item Admin Import API with
`policy=ABORT`, then performs a fresh exact-content read-back. A request with
`expected_md5=None` does not resolve or call the gRPC CAS transport. An existing
key is accepted only as a strict single-item conflict; ambiguous transport
outcomes remain unknown and are not retried. The production reader classifies a
missing resource only for HTTP 404 plus the exact Nacos `code=20004` response.

Evidence includes (a) writer acceptance for create, conflicting re-create with
preservation of the original value, concurrent competing creates with one
winner, and exact missing-config classification; and (b) the opt-in SQL
mutation-store acceptance, extended to publish a new absent Nacos key through
the durable outbox and production worker, verify exact encoder bytes and the
completed read-back receipt, and confirm a repeated worker run is a no-op.
The SQL outbox acceptance uses its existing isolated SQLite store and a
test-owned disposable Nacos container; it does not establish PostgreSQL/MySQL
plus Nacos as a combined deployment matrix.

Verification performed on 2026-10-10:

```sh
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_nacos_rule_source_reader.py \
  tests/test_nacos_rule_source_writer.py \
  tests/test_nacos_rule_publication_provider.py
SENTINEL_NACOS_ACCEPTANCE_URL=http://127.0.0.1:28849/nacos \
  PYTHONPATH=src .venv/bin/pytest -q tests/test_nacos_rule_source_writer_acceptance.py
SENTINEL_NACOS_ACCEPTANCE_URL=http://127.0.0.1:28848/nacos \
  PYTHONPATH=src .venv/bin/pytest -q tests/test_nacos_rule_source_writer_acceptance.py
SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 PYTHONPATH=src \
  .venv/bin/pytest -q \
  tests/test_rule_mutation_store.py::RuleMutationStoreTests::test_nacos_worker_publishes_sql_outbox_to_real_nacos
```

Results: focused reader/writer/provider tests **29 passed**; writer acceptance
against disposable Nacos **3.2.3: 5 passed** and **3.2.4: 5 passed**; SQL
outbox + worker acceptance against disposable Nacos **3.2.4: 1 passed**. Both
standalone containers were auth-disabled, volume-free, and loopback-only; no
pre-existing Nacos instance or database was contacted. `compileall` and
`git diff --check` also passed. Ruff was unavailable in the local environment,
so no lint-pass claim is made.

The create-only endpoint is defined by the official [Nacos Admin API
documentation](https://nacos.io/en/docs/latest/manual/admin/admin-api/).
This acceptance does not prove production auth/TLS/custom CA, a clustered
Nacos consistency policy, process death during a provider side effect,
instance-level activation, or the complete React→Python Dashboard E2E.

### PostgreSQL/MySQL → Nacos create-only worker acceptance (2026-10-10)

The opt-in `rule_publication_nacos_database_acceptance.py` helper is now wired
into the real PostgreSQL and MySQL acceptance classes. For each dialect it
creates a unique SQL account/session, frozen version and validation receipt,
accepts a create-only publish operation into the SQL outbox, starts a fresh
Nacos 3.2.4 container, and executes the production Nacos publication worker.
It then verifies exact encoded bytes by reading Nacos back, confirms the SQL
operation/publication reached completed/succeeded, checks operator reason
redaction, and confirms another worker pass is a no-op. Only UUID-scoped SQL
rows and the UUID dataId are cleaned.

Both database servers were separately created for this run with the exact
names `sentinel-dash-nacos-pg-acceptance-20261010` and
`sentinel-dash-nacos-mysql-acceptance-20261010`, bound to random loopback host
ports, with no pre-existing database used. Nacos was independently created by
the helper and bound to loopback with no volume; auth was disabled for this
local protocol acceptance only. All three containers were removed after each
run. The existing `nacos-pg-3.2.3` service was observed but not contacted or
modified.

Verification:

```sh
SENTINEL_CONSOLE_TEST_POSTGRES_URL='<isolated sentinel_console_test_* PostgreSQL URL>' \
SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 PYTHONPATH=src \
  .venv/bin/pytest -q \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_sql_rule_outbox_creates_config_in_disposable_nacos

SENTINEL_CONSOLE_TEST_MYSQL_URL='<isolated sentinel_console_test_* MySQL URL>' \
SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 PYTHONPATH=src \
  .venv/bin/pytest -q \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_rule_outbox_creates_config_in_disposable_nacos
```

Results: PostgreSQL 16 + Nacos 3.2.4 **1 passed in 8.82s**; MySQL 8.4.11 +
Nacos 3.2.4 **1 passed in 9.77s**. This closes the local two-dialect SQL
outbox → Nacos create-only → exact-readback combination. It does not prove
production Nacos cluster consistency/auth/TLS/custom CA, provider-side-effect
process crash recovery, instance activation/receipt ingestion, or final
React→Python E2E; B0.3 remains open.

### Provider write committed, worker process dies before SQL receipt, replacement worker reconciles (2026-10-10)

- **Risk/requirement:** SQL publication state can remain `running/unknown` after
  Nacos has committed the candidate but before the worker records the write
  receipt. A replacement worker must discover the exact candidate in Nacos,
  finish read-back/completion, and never send a second create/update.
- **Layer:** production SQL outbox + worker composition + disposable real Nacos;
  a spawned worker process calls the real provider and exits abruptly after a
  successful Nacos response but before returning to the worker orchestrator. It
  does not replace the Nacos server or writer.
- **Preconditions:** isolated PostgreSQL or MySQL test database, unique SQL
  identities/version/request key, empty UUID Nacos `dataId`, auth-disabled
  loopback-only disposable Nacos 3.2.4.
- **Action:** run worker A in a spawned OS process; let its production provider
  perform the Nacos write, then terminate the process at the provider return
  boundary before the SQL phase can record success. The process must exit with
  the test-only marker code, not complete graceful cleanup. Advance the
  injected clock past the SQL claim lease and run a newly composed worker B.
- **Assertions:** worker A exits at the injected crash point; provider contains
  exact frozen bytes; durable SQL phase remains running after worker A; worker B completes
  the same operation/publication after exact read-back; write-call count remains
  one; an additional pass is a no-op; cleanup removes only unique rows/config.
- **Limit:** the process is terminated immediately after the provider method
  receives a successful response, not while the Nacos RPC is in flight or
  before the server commits. Network partition/ambiguous transport completion
  remains a distinct fault window.

**Observed result:** the opt-in acceptance passed against both isolated
PostgreSQL 16 + Nacos 3.2.4 and MySQL 8.4.11 + Nacos 3.2.4 (**1 passed per
dialect; PostgreSQL 8.94s, MySQL 10.05s**). The focused worker and mutation-store
suite was rerun: **37 passed, 2 skipped in 11.50s**. In each dialect, a spawned
OS worker called the real Nacos provider, received its successful write
response, and exited abruptly at the test seam before returning to the worker
orchestrator; the Nacos server held the exact candidate bytes while SQL phase
remained `running`. After lease expiry, a newly composed worker completed by
reading back those bytes. The recovery worker's provider write method was
instrumented and observed **zero** calls; a later worker pass was a no-op. The
test-owned SQL/Nacos containers and unique Nacos config were removed; no shared
database or pre-existing Nacos instance was used.

Reproduction (the database URLs must point only to isolated
`sentinel_console_test_*` databases):

```sh
SENTINEL_CONSOLE_TEST_POSTGRES_URL='<isolated PostgreSQL URL>' \
SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 PYTHONPATH=src \
  .venv/bin/pytest -q \
  tests/test_postgresql_acceptance.py::PostgreSQLConsoleAcceptanceTest::test_sql_rule_outbox_creates_config_in_disposable_nacos

SENTINEL_CONSOLE_TEST_MYSQL_URL='<isolated MySQL URL>' \
SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 PYTHONPATH=src \
  .venv/bin/pytest -q \
  tests/test_mysql_migration_acceptance.py::MySQLConsoleMigrationAcceptanceTest::test_sql_rule_outbox_creates_config_in_disposable_nacos
```

The acceptance helper is
`tests/rule_publication_nacos_database_acceptance.py`, called by the existing
PostgreSQL and MySQL Nacos acceptance cases. This proves abrupt process exit
after the provider has received success but before SQL records it; it does not
prove termination while the network RPC is still in flight, before the Nacos
server commits, or scheduled activation-plan recovery with the real provider.

### Scheduled activation competes with an independent OS writer (2026-10-11)

- **Risk:** an activation worker's preflight can read revision `R`, then an
  independent operator/process can update the same config before the worker's
  CAS. The worker must not overwrite the external update; if the plan worker
  wins instead, the external writer must not overwrite the accepted plan.
- **Layer:** PostgreSQL/MySQL-backed rule publication outbox, scheduled plan
  worker, production Nacos publication provider, and a separate spawned OS
  process running `NacosRuleSourceWriter` against a disposable Nacos 3.2.4.
- **Action:** after the target is reset to exact baseline bytes, enqueue an
  activation. The independent process and scheduled worker compete using the
  same baseline MD5 and different valid same-kind JSON. The assertion accepts
  either server-side CAS winner; it does not force a deterministic scheduling
  order.
- **Assertions:** the remote bytes equal exactly one contender's bytes. If the
  external writer wins, the worker records `conflict`, the activation plan is
  durably blocked, no restoration is enqueued, and replay does not reclaim it.
  If the plan worker wins, the external writer receives `conflict`, the exact
  candidate is read back, and the plan may advance to active. OS process exit,
  external outcome, SQL publication phase, plan state, and remote bytes must
  agree.
- **Observed result:** the focused acceptance ran against separately created
  loopback-only PostgreSQL 16 and MySQL 8.4.11 databases and helper-created
  disposable Nacos 3.2.4 instances: final rerun **2 passed in 22.52s**, one per
  SQL dialect. Containers were removed by the test command's exact-name cleanup
  trap; no existing/shared database or Nacos instance was used. Initial test
  runs caught a test-only undefined `_md5` reference and an incorrect success
  enum expectation; both were fixed before the passing final rerun. Docker
  process invocation/cleanup in the async helper now runs through
  `asyncio.to_thread` rather than blocking the event loop.
- **Limit:** this establishes a separate OS writer process contending against
  the worker's real Nacos CAS and verifies either valid winner. It does not
  prove multi-host production scheduling, Nacos cluster consistency,
  production auth/TLS/custom CA, in-flight process termination, ambiguous
  server commit, or instance Reporter receipt ingestion. B0.3 and final
  React-to-Python E2E remain open.

### Authenticated Nacos gRPC update-CAS through production writer (2026-10-13)

- **Risk/requirement:** direct credentials must authorize both token acquisition
  and the Nacos gRPC configuration update; the adapter must preserve provider
  MD5 CAS and confirm exact bytes through an authenticated read-back.
- **Layer:** production `NacosRuleSourceWriter`/`NacosRuleSourceReader`, direct
  username/password resolution, real auth-enabled Nacos 3.2.4, and the actual
  gRPC request path. The test-owned HTTPS/HTTP2 TLS proxy terminates the test
  certificate and forwards to the isolated server's loopback gRPC port.
- **Action/assertions:** create an exact disposable config using the direct
  credential path, update it using the returned MD5 through gRPC CAS, read back
  exact candidate bytes/MD5, then submit the stale MD5 and require a conflict
  without changing remote bytes. The TLS trust root is explicitly configured;
  credentials are excluded from connection and response representations.
- **Observed result:**
  `SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE=1 uv run --extra test --extra nacos-grpc pytest -q --tb=short tests/test_registered_source_nacos_auth_acceptance.py`
  **3 passed in 32.75s**; existing real Nacos mTLS transport handshake
  `uv run --extra test --extra nacos-grpc pytest -q --tb=short tests/test_nacos_grpc_tls_acceptance.py`
  **1 passed in 6.27s**. The disposable Nacos auth container was removed by
  fixture teardown and the exact `sentinel-nacos-auth-` name query returned no
  containers.
- **Limit:** the auth test's TLS terminator is test-owned and the Nacos
  container's gRPC listener is plain behind that loopback proxy. It proves the
  production gRPC auth-token payload/real Nacos behavior and separately the
  transport's mTLS capability, but not a native TLS-enabled Nacos cluster,
  deployed CA/client certificate rotation, Nacos cluster consistency, worker
  restart under production credentials, or React→Python E2E. B0.3 remains open.

### SQL-backed opaque credential-reference resolution before authenticated Nacos gRPC update-CAS (2026-10-13)

- **Risk/requirement:** deployments that store only a credential reference must resolve that exact source revision through their secret authority before the publication adapter performs Nacos token acquisition and gRPC CAS. The locator must not cross into provider requests or diagnostics.
- **Layer:** production `SqlAlchemyRegisteredSourceStore` registration/encryption and exact-revision credential resolver, production `ResolveRegisteredSourceConnection`, a deployment-owned `SourceCredentialReferenceResolver` contract fixture, `NacosRuleSourceWriter`/`NacosRuleSourceReader`, and auth-enabled disposable Nacos 3.2.4. The source is persisted using migrated SQLite by default or the owner runner's TLS-enabled MySQL 8.4.11 when `SENTINEL_CONSOLE_TEST_MYSQL_URL` is present; unsafe/non-loopback database URLs are rejected.
- **Action/assertions:** register an opaque `secret://` reference through the production SQL store, verify the reference is encrypted at rest, resolve that exact source revision into ephemeral direct credentials, create the disposable baseline, perform authenticated gRPC update-CAS, and verify exact bytes/MD5 read-back. Assert the reference resolver is called once, the locator is removed from the provider connection, and the resolved secret is absent from connection/response representations.
- **Observed result:** full auth acceptance using SQLite: **4 passed in 48.78s**; same full suite using TLS-enabled MySQL 8.4.11 plus owner-run disposable Consul/Nacos 3.2.4: `SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE=1 tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql --extra nacos-grpc pytest -q --tb=short tests/test_registered_source_nacos_auth_acceptance.py` **4 passed in 49.17s**. After test teardown/lint cleanup changes, the MySQL + Nacos credential-reference/gRPC CAS case was rerun **1 passed in 14.52s**. Adjacent registered-source resolver/store, publication worker composition, and Nacos reader/writer regression: **50 passed in 9.56s**. Ruff check/format, compileall, and `git diff --check` passed; post-run exact queries found no owner-run MySQL/Consul or `sentinel-nacos-auth-` container.
- **Limit:** this does not exercise a real KMS/Vault adapter, PostgreSQL source-secret retrieval in the same Nacos run, secret rotation during an in-flight operation, native Nacos gRPC TLS, or production cluster consistency. It closes only the SQL registry + opaque-reference + provider-auth adapter slice; B0.3 and final React→Python E2E remain open.

### Authenticated SQL outbox worker resolves the registered credential reference (2026-10-13)

- **Risk/requirement:** the direct writer acceptance and SQL outbox acceptance must not remain disconnected demonstrations. The production worker must resolve the exact SQL-registered source revision and its opaque credential reference before publishing through the real authenticated Nacos provider.
- **Layer:** `SqlAlchemyRegisteredSourceStore` → `ResolveRegisteredSourceConnection` as composed by `create_nacos_rule_publication_worker` → SQL rule/version/publication outbox → authenticated Nacos 3.2.4 over the test-owned HTTPS/HTTP2 TLS proxy.
- **Action/assertions:** persist the source credential reference encrypted at rest; seed a validated baseline and candidate immutable rule version; accept a real SQL-backed publish command; create the exact provider baseline using create-only; then execute the production Nacos worker with the SQL store and deployment-owned reference resolver. Verify completed worker outcome, completed durable operation, exact serialized rule bytes on Nacos, exact source reference resolver calls, and secret-free worker/provider representations. HTTP TLS and gRPC TLS trust are explicitly supplied to the composition.
- **Observed result:** focused SQLite/auth-enabled Nacos run **1 passed**; full acceptance against TLS-enabled disposable MySQL 8.4.11 + auth-enabled disposable Nacos 3.2.4 **4 passed in 48.68s**. Adjacent registered-source, resolver, worker composition/logic and Nacos source reader/writer regression **59 passed in 6.34s**. Ruff check/format, Python compileall and `git diff --check` passed. The test-owned Nacos fixture and exact owner-labeled MySQL/Consul runner containers were removed; post-run exact-name queries were empty.
- **Limit:** this is real SQL outbox → production worker → authenticated Nacos evidence for MySQL, not PostgreSQL or production KMS/Vault, native Nacos gRPC listener TLS, credential rotation during an active publish, multi-node provider consistency, instance activation receipts, or React→Python browser E2E. No Console wire/API change was made; B0.3 and B0.5 remain open.
- **PostgreSQL dialect follow-up:** the opt-in test now accepts only the disposable loopback `postgresql+psycopg` URL and uses libpq `sslmode=verify-full` with the runner's temporary CA. The production worker credential-reference case passed against disposable TLS PostgreSQL 16 plus auth-enabled Nacos 3.2.4 (**1 passed in 14.68s**). Two full four-test PostgreSQL auth-group attempts each had three passing cases and one fixture startup failure (`docker run` exit 125, before that test reached SQL/provider work; the failing case differed between attempts). After confirming no owned containers remained, the target PostgreSQL worker case was rerun independently and passed. Do not treat either full-group attempt as green; the successful isolated worker case establishes the SQL dialect slice only.

### Consul native HTTPS listener with production ACL reader/writer (2026-10-13)

- **Risk/requirement:** prior Consul acceptance terminated TLS in a test proxy and forwarded upstream over HTTP. It did not establish that the production provider client can use Consul's own HTTPS listener with certificate verification enabled.
- **Layer:** disposable Consul 1.21.1 with its native HTTPS API listener enabled on 8501, ACL `default_policy=deny`, a fixture-owned short-lived certificate mounted read-only outside Consul's managed config directory, the production `PinnedAioHttpJsonClient`, and production Consul reader/writer adapters.
- **Action/assertions:** retain the existing HTTP listener only for fixture ACL provisioning and fault-proxy forwarding; create an exact-host/port target policy for the native HTTPS endpoint; use the test CA in the production HTTP client; read the baseline with the scoped ACL token, CAS-write candidate bytes through native Consul HTTPS, and read back exact bytes/revision. The existing proxy-based ACL tests continue exercising request observation and ambiguous-response barriers.
- **Observed result:** direct native HTTPS case **1 passed**; full opt-in ACL acceptance **5 passed**; proxy response-drop/CAS-barrier regression **2 passed**. Ruff/format, `compileall`, and `git diff --check` results are recorded with the implementation run. The disposable Consul fixture container and its temporary certificate directory are owner-cleaned; exact-name container query is empty.
- **Limit:** this establishes server-authenticated TLS with a test CA and Consul ACL behavior on a local disposable single-node agent. It is not mTLS client-certificate enforcement, production certificate rotation, multi-node consistency, installed dual-provider deployment, or React→Python E2E. Earlier notes that the Consul fixture had no native HTTPS coverage are historical and are superseded by this section; B0.3/B0.5 remain open.

### Consul CAS connection reset before upstream dispatch (2026-10-13)

- **Risk/requirement:** a transport failure after the production writer sends a CAS request but before the provider receives it must not be retried blindly; the provider result must remain conservative even when this fixture can independently verify that no upstream write happened.
- **Layer:** production `ConsulRuleSourceWriter` and `PinnedAioHttpJsonClient` → disposable HTTPS fault proxy → real single-node ACL-enabled Consul 1.21.1.
- **Action/assertions:** seed a synthetic exact baseline through the fixture management path, read its `ModifyIndex` through the scoped application token, then arm the proxy to reset the single CAS connection after request receipt and before upstream dispatch. Assert the writer reports `ConsulRuleSourceOutcomeUnknown`, the proxy observed exactly one CAS (no automatic retry), and a subsequent exact read returns the unchanged baseline bytes. All provider requests use the scoped ACL token; the test's generated endpoint/certificate and Consul container are cleaned by the fixture owner.
- **Observed result:** opt-in targeted test **1 passed**; no SQL worker or activation-plan persistence is exercised here. Disposable Consul shutdown is owned by the test fixture.
- **Limit:** this complements the post-commit response-loss/process-kill cases but does not simulate an unknown Consul server commit, a failure before the proxy receives the request, durable SQL `unknown` persistence, scheduled-plan recovery, multi-node consistency, or React→Python E2E. B0.3 and B0.5 remain open; Console API 0.4.0 is unchanged.

### Credential-reference worker drives scheduled activation and restoration (2026-10-13)

- **Risk/requirement:** a scheduled rule plan must preserve the exact registered source revision and opaque credential resolution across both provider writes; it must advance from activating/active/restoring/completed only after the SQL outbox worker confirms exact provider read-back.
- **Layer:** production SQL registered-source store and `ResolveRegisteredSourceConnection`, `SqlAlchemyRuleMutationStore`, scheduled-plan SQL queue/reader, `RunRuleActivationPlanWorker`, production `create_nacos_rule_publication_worker`, and auth-enabled Nacos 3.2.4 through the test-owned TLS proxy.
- **Action/assertions:** after a regular SQL outbox publish, create a real scheduled plan that temporarily activates the stored baseline and restores the ordinary rule version. Run both plan scheduler and provider outbox workers against the same encrypted source reference; assert both gRPC CAS writes complete, exact native rule arrays are read back, plan transitions only after each worker completion, terminal state is `completed`, and the secret resolver is called once per worker publication.
- **Observed result:** focused real Nacos acceptance passed with SQLite (**1 passed in 16.06s**), disposable TLS MySQL 8.4.11 (**1 passed in 16.85s**), and disposable TLS PostgreSQL 16 using `sslmode=verify-full` (**1 passed in 16.78s**). Adjacent registered-source, publication-worker, activation-plan-worker, and Nacos reader/writer regression **73 passed in 6.76s**. Ruff check/format, compileall, `git diff --check` passed; exact owner-run container queries were empty after teardown.
- **Limit:** this proves one successful activation/restoration lifecycle, not ambiguous provider response recovery during either scheduled phase, cancellation races, PostgreSQL's full Nacos-auth test group (which had separate fixture-startup failures documented above), production secret rotation/KMS, Nacos cluster consistency, instance receipt ingestion, or React→Python browser E2E. The ACK-loss follow-up below narrows the first limitation to an injected post-commit response loss at the transport boundary; it is not packet-level fault injection. B0.3/B0.5 remain open and no frozen Console API wire changed.

### Scheduled activation/restoration reconcile a committed Nacos write after lost acknowledgement (2026-10-13)

- **Risk/requirement:** if Nacos commits an activation or restoration but the successful provider acknowledgement is not observed by the SQL outbox worker, the durable publication must become `unknown`, then recover by exact read-back without issuing a duplicate CAS; the plan must not advance until that recovery is durably complete.
- **Layer:** the production SQL registered-source store and credential-reference resolver, SQL publication outbox, `RunRuleActivationPlanWorker`, production Nacos publication worker, authenticated Nacos 3.2.4 and its real gRPC CAS/read path. A test seam lets the actual `NacosGrpcTransport.request` reach Nacos and then raises `NacosGrpcOutcomeUnknown` before the writer receives the successful response.
- **Action/assertions:** separately inject the post-commit acknowledgement loss for scheduled activation and restoration. Verify Nacos contains the intended exact bytes despite the unknown result; expire/reclaim the publication lease; run a new worker and prove it completes through exact read-only reconciliation with zero `ConfigPublishRequest` retries; only then let the plan advance to `active` or `completed`. The same opaque source reference is resolved against the pinned source revision for each phase.
- **Observed result:** focused auth-enabled Nacos acceptance passed on SQLite (**1 passed**), TLS MySQL 8.4.11 (**1 passed**), and TLS PostgreSQL 16 with `sslmode=verify-full` (**1 passed**). Related source resolver/store, publication and activation-plan workers, and Nacos reader/writer regression: **73 passed in 6.61s**. Ruff check and format, Python `compileall`, and `git diff --check` passed. Exact owner-run MySQL/Consul/PostgreSQL and Nacos-auth container queries were empty after cleanup.
- **Limit:** this verifies committed remote bytes followed by an injected lost-success-response seam at the real transport caller boundary; it does not simulate packet loss, an unknown Nacos server commit, a write that never reaches Nacos, cancellation/lease races, production secret rotation/KMS, Nacos cluster consistency, instance receipt ingestion, or React→Python browser E2E. It closes only this scheduled Nacos recovery slice; B0.3/B0.5 remain open and the frozen Console API wire is unchanged.

### SQL outbox worker resolves a registered Consul credential reference before ACL/TLS CAS (2026-10-13)

- **Risk/requirement:** Consul publication must use the exact registered source revision and deployment-owned credential reference, not a test-only resolver that bypasses SQL ciphertext storage. ACL material must reach Consul only in its request header, over verified TLS, and must not appear in stored ciphertext or diagnostics.
- **Layer:** production `SqlAlchemyRegisteredSourceStore` and `ResolveRegisteredSourceConnection`, registered-source AES-GCM encryption, deployment-owned `SourceCredentialReferenceResolver` fixture, SQL-backed admin HTTP publish/outbox, production `create_consul_rule_publication_worker`, and disposable ACL-enabled Consul 1.21.1 over its test-owned HTTPS proxy.
- **Action/assertions:** the existing admin/Origin/CSRF/idempotency path accepts and replays one SQL publish; the fixture persists an opaque `secret://` reference encrypted against the exact source ID, then runs the production worker. Verify SQL resolver returns the exact source/revision and opaque reference, the external resolver receives only the expected Consul reference, the worker resolves it to ephemeral credentials, ACL-protected CAS writes exact version bytes and reads them back, the completed HTTP receipt matches the accepted operation, and an empty second poll does not write again. Assert the token/reference are absent from ciphertext, path, and repr; retain the existing viewer/CSRF/Origin/idempotency denials before side effects.
- **Observed result:** MySQL 8.4.11 + Consul 1.21.1 **1 passed in 2.58s**; TLS PostgreSQL 16 (`sslmode=verify-full`) + Consul 1.21.1 **1 passed in 2.01s**. Registered-source store, source-reference application, source credential resolution, publication worker, and composition regression **40 passed in 6.18s**. Ruff check/format, Python compileall, and `git diff --check` passed. A first MySQL attempt found the new synthetic source row needed deletion before its account FK target; cleanup now removes it in FK-safe order, and the rerun passed. The initial PostgreSQL invocation was skipped by the opt-in decorator and was rerun with the correct flag; only the passing rerun is counted. Owner-run exact MySQL/Consul/PostgreSQL container names and ACL fixture prefix were absent after cleanup.
- **Limit:** this closes the Consul SQL credential-reference → production worker → ACL/TLS CAS slice for MySQL and PostgreSQL. It does not prove a real external KMS/Vault, in-flight secret rotation, native Consul TLS listener, the full installed-wheel dual-provider lifecycle with both sources authenticated, provider multi-node consistency, instance receipt ingestion, or React→Python browser E2E. B0.3/B0.5 remain open; Console API 0.4.0 wire is unchanged.

### Scheduled Consul activation and restoration resolve SQL credential references and reconcile lost acknowledgements (2026-10-13)

- **Risk/requirement:** scheduled activation and restoration must use the registered source's exact pinned revision and opaque credential reference, not a direct test resolver. If Consul commits the CAS but the worker loses its acknowledgement, SQL reconciliation must read the exact remote value without a duplicate write before the plan advances.
- **Layer:** production `SqlAlchemyRegisteredSourceStore`, `ResolveRegisteredSourceConnection`, SQL activation-plan/outbox workers, production Consul writer/reader, TLS MySQL 8.4.11 or TLS PostgreSQL 16 (`sslmode=verify-full`), and disposable ACL-enabled Consul 1.21.1.
- **Action/assertions:** persist the reference in AES-GCM encrypted source configuration; resolve the exact source/revision into ephemeral ACL credentials; schedule activation and restoration; let real ACL/TLS Consul commit each CAS, then have the test-owned HTTPS proxy close the client TCP response after commit. Assert the remote exact bytes changed, the worker classifies the outcome as unknown, each faulted phase generated exactly one CAS PUT, and lease-expiry recovery completes by exact read-back with no duplicate write before the activation plan advances. Verify the external resolver receives only the expected reference and all observed Consul requests use the disposable ACL token.
- **Observed result:** the first real-response-drop attempt exposed a hidden duplicate: aiohttp retried the idempotent HTTP `PUT` after the ambiguous close, and the retry lost Consul CAS and turned the publication into `rejected/conflict`. `PinnedAioHttpJsonClient` now disables aiohttp's internal retry at its shared transport boundary and fails closed if that control is absent. After the fix, TLS MySQL + Consul **1 passed in 6.12s**; TLS PostgreSQL + Consul **1 passed in 5.71s**; HTTP client, Nacos/Consul readers/writers, source resolver/store, publication worker/composition, and activation-plan worker regression **104 passed in 6.47s**. Ruff F checks, `compileall`, and `git diff --check` passed. Disposable runner and fixture container queries were empty after both runs.
- **Limit:** this simulates a post-commit TCP response close through the test-owned proxy, not a network partition or unknown server commit. The no-retry control uses a guarded aiohttp internal attribute because the library exposes no public switch; an upgrade that removes it fails closed and must be revalidated. Other plan races remain covered by the direct-credential acceptance and are not all repeated through the reference resolver here. Production KMS/Vault, in-flight credential rotation, native Consul TLS listener, cluster consistency, instance receipts, installed-wheel full dual-provider lifecycle, and React→Python browser E2E remain open. B0.3/B0.5 remain open; Console API 0.4.0 wire is unchanged.

### Installed CLI completes a dual-provider publish with both providers authenticated (2026-10-13)

- **Risk/requirement:** the earlier installed-wheel dual-provider success path used unauthenticated providers, while separate provider-auth tests did not prove both authenticated sources could be recovered and published by the same installed Console worker deployment.
- **Layer:** built wheel and installed `sentinel-console serve` with two Uvicorn workers; first-run HTTP setup to auth-enabled Nacos 3.2.4 using direct username/password; production SQL registered-source encryption/decryption for the Consul source; SQL mutation/outbox and provider router; Nacos HTTPS + gRPC TLS CAS and Consul ACL/TLS CAS against disposable real providers.
- **Action/assertions:** initialize the installed Console with Nacos as the first authenticated source; register the second Consul source row using the production AES-GCM SQL credential format; enqueue one publication for each provider; wait for both installed workers to complete, assert durable operation/publication receipts and exact provider read-back. The Consul ACL token is not passed to the CLI process environment, is encrypted in SQL, is sent only in the provider header, and is absent from the request URL. Both sources use temporary CA trust provided to the installed service.
- **Observed result:** final-source run after the test-collection fix: MySQL 8.4.11 TLS + authenticated Nacos/Consul: **1 passed in 37.25s**; PostgreSQL 16 TLS (`sslmode=verify-full`) + authenticated Nacos/Consul: **1 passed in 36.62s**. The installed wheel, formal two-worker service, SQL durable outbox, Nacos auth/gRPC CAS, Consul ACL CAS and read-back all participated. Ruff, format, compileall, test collection (4 tests, no imported-class duplication), and `git diff --check` passed. Disposable SQL/provider containers and Nacos TLS/auth fixture were cleaned; exact owned-name/prefix query returned no leftovers.
- **Limit:** this closes only the installed dual-auth success lifecycle. It does not prove production KMS/Vault delivery or rotation, native provider TLS listener deployment, ACL policy operations, ambiguous provider outcomes/failure/cancellation matrix, multi-node consistency, instance receipts, or React→Python browser E2E. B0.3/B0.5 remain open; Console API wire 0.4.0 is unchanged.
