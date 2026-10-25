# B0.1 — Ruleset command HTTP slice

Status: **typed rule-command HTTP boundary, SQL draft/version mutation, binding-directory read and admin registration with durable receipt are implemented; provider publication is composed for explicitly configured deployments and verified through installed CLI acceptance; production deployment policy/operations and final React→Python browser acceptance remain open**.

## Contract and boundary

Registers the OpenAPI operations:

- `POST /api/v1/rulesets/{bindingId}/commands`
- `GET /api/v1/rulesets/{bindingId}/operations/{requestKey}`

The strict body parser supports exactly `save_draft`, `delete_draft`,
`freeze_version`, `publish`, `create_plan`, and `cancel_plan`. It binds a
candidate or activation schedule to the exact path binding and rejects unknown
or extra fields. Schedule instants require explicit UTC milliseconds.

Mutation requires an administrator session, allowed Origin, CSRF proof, and a
single `Idempotency-Key` exactly matching the body request key. The application
port receives actor, session digest, CSRF digest, request ID, and current UTC
time. Operation lookup is administrator-only and scoped to the same actor,
session, binding, and request key. Responses are allow-listed typed results or
finite reasons; arbitrary exception detail is never returned. If no mutation
authority is injected, both operations fail closed with `503`.

The SQL slice persists complete drafts, immutable versions, exact original
operation receipts, and audit facts in one transaction for `save_draft`,
`delete_draft`, and `freeze_version`; stale revision changes are rejected.
Freeze requires the exact current draft revision and a publishable validation
receipt matching binding, profile, base checksum, and recomputed complete
candidate checksum. SQL draft and version readers provide exact binding-scoped
list/detail reads and are installed by the SQL identity app composition.
Mutation remains opt-in: its caller must provide a dedicated key ring and an
authoritative exact-binding reader. A SQL composition factory and deployment
key configuration are available; `build_sql_identity_app(...)` accepts these
inputs as a pair and rejects partial wiring or mixing them with a separately
supplied authority. The composition does not invent a binding from a
browser-supplied identifier. In this initial `POST .../commands` adapter,
`publish` and activation-plan variants persist a finite `unsupported` result
without provider side effects. This is distinct from the subsequently
implemented `/publications` and `/plans` routes and SQL workers, whose
configured Nacos/Consul execution is covered by installed-CLI evidence in
checklist §15.1010–§15.1011, §15.1040–§15.1041, and §15.1057–§15.1068.

The first-run deployment configuration must load the independent rule-command
key ring from the existing environment contract and accept the exact-binding
reader only as an explicit host-owned dependency. Key material without that
reader, or a reader without the complete key ring, is a configuration error;
the Console must not silently drop either input or manufacture binding facts.

This initial draft/version SQL slice is not, by itself, the production rule
authority end state. Later slices persist publication/plan lifecycle facts
and perform provider writes/read-back through explicitly configured
Nacos/Consul workers; the installed-CLI, PostgreSQL/MySQL evidence is recorded
in the checklist sections cited above. These results do not validate
customer-specific production target policy, credential delivery/rotation,
network topology, ingress, or final React→Python browser acceptance. The
`/commands` variants above remain distinct from the dedicated publication/plan
routes.

## Focused verification

- Historical grouped focused run of the initial mutation store, parsing, draft API, version API,
  and SQL identity composition: **32 passed**.
- Covers admin/CSRF checks before writes, exact-binding kind/profile validation,
  five typed rule kinds including empty arrays, create/update/delete CAS,
  idempotency and original receipt replay, immutable freeze against an exact
  publishable validation receipt, unsupported publish without provider effect,
  exact-binding SQL draft/version list/detail, operation HTTP serialization,
  and SQL app reader composition. API/parser tests cover all six command DTOs,
  viewer/anonymous denial, malformed fields, and absent authority behavior.
- Python 3.13 `compileall` passed for Console source and changed test modules;
  `git diff --check` passed.
- Rule-command key configuration, SQL identity composition, and mutation store
  focused run: **15 passed** after adding dedicated key-ring and composition
  coverage.
- Full browser E2E and full Console suite were not run; they remain reserved
  for the final implementation milestone.

## Coverage update

At the time of this initial slice, the static source maximum increased from
**38/42** to **40/42** registered OpenAPI method/path operations; the two
missing routes then were bootstrap initialization and its original-operation
lookup. This is historical coverage, not the current contract/runtime status:
the current checklist records **44 paths / 45 operations** and route/method
parity coverage in §15.599 and §15.992. Route registration/parity alone does
not prove that optional authorities are configured in a deployment.

## Durable draft-command slice — initial test design and evidence (historical)

This section records the original draft/version SQL acceptance design. At that
stage, the `/commands` authority supported `save_draft`, `delete_draft`, and
`freeze_version`; its `publish` and plan variants returned durable
`unsupported` receipts. Do not read this historical test-design snapshot as a
description of the later dedicated publication/plan APIs and workers. No
accepted response may imply a provider write unless that operation used the
configured provider path and its durable receipt/read-back.

| Risk | Isolated persistence/API assertion |
| --- | --- |
| Unauthorized/stale session | Revoke/expire the administrator session or mismatch CSRF; no draft, operation receipt, or audit row is written |
| Lost update | Create with no baseline revision; replace/delete only with exact draft revision; stale revision is a conflict and keeps current content |
| Idempotency | Same request key + same actor/session/input returns the exact original result; changed input or another session conflicts without another write |
| Receipt integrity | Read is limited to original actor/session and exact binding; a later draft edit does not mutate the old operation result |
| Full rule preservation | Persist all five typed rule kinds and empty rule arrays without dropping fields or identifiers |
| Unsupported workflow | Publish and plan commands return a stable unsupported result and create no publication/provider side effect |
| Freeze must bind the exact validated draft | Only the current expected draft revision plus a publishable receipt matching binding/profile/base/candidate checksum may create one immutable version; stale, missing, mismatched, or non-publishable evidence creates no version |
| Version immutability | Replaying freeze returns the exact original version; later draft edits cannot rewrite that version's name, note, checksum, or complete records |
| Binding directory availability and session revocation | Exact binding lookup runs without an open SQL transaction; a session revoked during that lookup is rejected by the second authorization check before any draft/operation/audit write |
| Transaction boundary | Draft state, operation receipt, and audit commit together; DB failure leaves none of them committed |

The focused evidence at that time was SQLite migration/transaction coverage
with an injected test binding directory. The exact-binding mutation port then
accepted an explicit deployment-owned reader; the separate SQL directory
reader was added for the list endpoint. The later admin binding-registration
API and standard SQL composition now populate/read that directory; PG/MySQL
registration concurrency and idempotency are recorded in checklist §15.455
and §15.1048. This historical test-design paragraph does not describe the
current directory state.

## SQL binding-directory authority — test design before implementation

The Console SQL database may own the **binding metadata directory** (app,
environment, rule kind/profile, source identity, and redacted location), while
the selected Nacos/Consul item remains the sole authority for live rule arrays.
This must not turn the Console database into a rule-content store or allow a
browser-provided binding ID to manufacture an authority fact. The directory
reader must compose metadata only with the exact registered source and
publication target for that same binding.

| Risk | Layer | Required assertion |
| --- | --- | --- |
| Cross-binding join manufactures a target | SQL reader | Only rows with matching binding ID, source ID, registered-source provider, and exact publication target are returned; mismatches fail closed rather than being skipped |
| Query result leaks another environment/application/type | SQL reader | Apply exact environment, optional app, optional kind, search, stable ordering, and bounded pagination before constructing the page; response query equals request |
| Source or target is absent | SQL reader | Missing source/target authority data never becomes an empty successful page or a guessed location; report authority unavailable. A stale source revision remains visible for repair; publish-target operations separately reject stale revisions |
| Sensitive connection material reaches the binding DTO | Mapper/domain | Source display label and exact Nacos/Consul key location are projected without credentials, userinfo, token/password query fields, or arbitrary target-body fields |
| Management metadata becomes rule authority | Persistence boundary | The binding record contains no rule array or snapshot body; changing directory metadata cannot modify the selected configuration-center item |
| Dialect behavior differs | Migration + SQL integration | Migration creates/drops only the binding metadata table and index; SQLite focused tests validate mapping, while PostgreSQL/MySQL remain separately required |

Run the binding-directory SQL reader tests and the existing rule-binding API
tests only for this slice. Do not run full E2E here; production Nacos/Consul,
PostgreSQL/MySQL deployment, and final React-to-Python E2E remain separate
acceptance gates.

## First-run rule-command composition — test design before implementation

| Risk | Layer | Required assertion |
| --- | --- | --- |
| Standard first-run CLI cannot activate configured rule commands | Deployment config + composition | A valid rule-command key ring selects the canonical SQL binding reader on the shared runtime database bridge; an explicit host reader overrides it |
| A browser identifier becomes authoritative binding data | Composition | Default or host reader returns the authoritative binding; no binding is derived from request input |
| Key/reader inputs conflict with a prebuilt mutation authority | Configuration + ASGI composition | Reject a reader without keys and reject mixed SQL inputs with a prebuilt authority; a key ring alone selects the canonical SQL reader |
| Key material leaks through the first-run config representation | Config | Active ID/key bytes are not exposed in `repr` or raised parse errors |

Run only `test_first_run_deployment_configuration.py`,
`test_first_run_composition.py`, and `test_rule_command_key_configuration.py`
for this slice; broader Console/database and browser E2E remain separate gates.

## SQL binding-directory reader — implementation result

Added migration `0018_rule_binding_directory`, the Console-owned metadata row,
and `SqlAlchemyRuleBindingDirectoryReader`. The reader also implements the
exact-ID mutation lookup contract, while SQL identity composition defaults the
directory GET route to this reader. Provider target writes update the
corresponding metadata source/location in the same transaction. The rule array
and snapshots are not persisted in this table.

Focused grouped verification passed **41 tests** across the new SQL reader,
binding API, publication target reader/writer, identity composition, first-run
composition, and deployment configuration. Source/test `compileall` and
`git diff --check` passed. A later B0.1 slice added the admin registration API
and stateful dashboard form (§15.453–§15.454). This follow-up wires the
canonical SQL reader into the standard first-run CLI when the command key ring
is configured, without requiring custom Python composition code; see §15.458.
Configured provider publication and worker acceptance are recorded in
checklist §15.1010–§15.1011 and later recovery sections; the current React
production build is also served from the installed wheel (§15.1049). Production
deployment policy/topology and final browser E2E remain open.

## Standard CLI SQL reader composition — 2026-10-10

The earlier explicit-reader requirement prevented the packaged `serve` entry
point from using its own canonical SQL binding directory. `FirstRunSqlIdentityConfiguration`
now accepts a rule-command key ring without a custom reader; the first-run host
composition creates `SqlAlchemyRuleBindingDirectoryReader` against the same
`RuntimeDatabaseEngineBridge` passed to SQL identity composition. Hosts may
still supply a custom exact reader, and supplying a reader without rule-command
keys remains invalid. Neither branch trusts browser-provided binding facts.

Focused evidence and remaining boundaries are recorded in checklist §15.458.
