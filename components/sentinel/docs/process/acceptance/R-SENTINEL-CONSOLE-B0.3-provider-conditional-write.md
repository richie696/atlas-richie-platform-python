# B0.3 — Provider conditional-write capability gate

Status: **provider evidence reviewed; SQL publication workflow plus real Consul and Nacos 3.x update-CAS execution have isolated acceptance evidence; Nacos create-only semantics, production TLS/auth, provider-stage crash recovery, instance activation, and the complete publication lifecycle remain open**.

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
private SDK internals. Keep Nacos publication fail-closed until one of these
maintainable seams is available and verified: (1) upstream adds public
server-MD5 read plus pinned-channel/auth transport injection; (2) maintain a
narrow, reviewed SDK fork with those seams; or (3) implement the minimal
versioned Nacos gRPC transport locally, including authentication, TLS/SNI,
DNS pinning, CAS outcome classification and exact read-back. Any route must
also verify create-only CAS behavior against the selected server versions.
This is an implementation constraint, not a decision to drop Nacos support.

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

These findings strengthen the fail-closed decision for unsupported cases. Full
Nacos publication must eventually provide server-authoritative
existence/content/MD5 observation, DNS pinning and TLS identity for every
channel, a provider-side conditional operation for each supported create or
update path, response classification, and exact read-back. The current local
adapter implements only the existing-key update path; SDK cache flags do not
satisfy the remaining create/absence requirements.

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
it does not close the create-only acceptance item.

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
unavailable, not as proof that the key is absent. This slice does not enable
Nacos publication: it is not wired as a complete `RulePublicationProvider`,
does not issue gRPC CAS, and does not solve Nacos create-only semantics. It
supplies the authoritative read and reconciliation half without weakening the
CAS requirement or changing the current fail-closed writer gate.

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
