# Metrics V2 M6.5.8b Owner-Review Ballot

> **Status: DECISIONS FROZEN — product owner authorized D2–D12 candidate values on 2026-10-14.**
> **Implementation gate:** This freezes the design and authorizes implementation.
> It does not claim that TLS identity, Collector, SQL durability, or cross-language
> production runtimes already exist; production acceptance remains gated by the
> tests listed in [`ADR-SEN-020`](ADR-SEN-020-metrics-v2-freeze.md).
>
> Scope: decisions needed to turn the proposal in
> [`reporting-protocol-04-metrics-v2-proposal.md`](reporting-protocol-04-metrics-v2-proposal.md)
> into an implementable contract. The user-confirmed §4.1 metric semantics are
> recorded as confirmed only within their stated scope; every other recommendation
> below remains a candidate until signed.

## Decision status

- **CONFIRMED — semantics only:** producer, meaning, unit/scope and denominator
  in §4.1 of the proposal, as recorded in progress tracker §15.1047. This is not
  wire, transport, storage, quality-policy, or production-send approval.
- **FROZEN — product owner authorization (2026-10-14):** D2–D12 values and
  implementation boundaries in ADR-SEN-020. Existing `reporting.drafts` code,
  schema, fixtures, and Java/Go validators are evidence inputs, not proof of a
  production implementation.
- Separate role-specific security/storage/language review records are not
  fabricated. Their operational verification remains required before final
  production/E2E acceptance, but does not block implementing the authorized
  defaults.

## Ballot

| ID / status | Recommended candidate for review | Existing evidence / cross-language impact | Required decision and principal risk |
| --- | --- | --- | --- |
| **D1 — CONFIRMED (bounded scope)** Metric meaning | Keep §4.1 as written: completed HTTP responses include 4xx/5xx; entry rate is admitted + blocked; TPS is explicitly instrumented business completions; p95 pools same-boundary HTTP histograms; blocked ratio is blocked/attempted; CPU/memory are process-only; missing/overflow/insufficient data is unavailable. | Owner confirmation §15.1047; ASGI HTTP producer tests and Sentinel metric tests are recorded in §15.1053. | No further semantic vote requested. Do not infer TPS/QPS from another producer or change unavailable to zero. This does not approve a wire encoding. |
| **D2 — FROZEN** Three clocks | `captured_at` is UTC diagnostic time; `capture_elapsed_ns` is canonical decimal string measured from the process monotonic-clock origin and compared only within one authenticated reporter + UUID epoch; Collector alone assigns `received_at`. Process restart creates a new epoch; a gap >10 seconds rebaselines. | Draft field/codec/shared fixtures exist; §15.1051 records draft-only Python/Go/Java validation. | Frozen by ADR-SEN-020. Invalid/regressing/overflow elapsed values reject; wall-clock/Collector receive time never substitute for rate intervals. |
| **D3 — FROZEN** Reporter and epoch identity | One process/worker is one reporter, enrolled to environment/application/instance/process. Certificate principal is authoritative; payload `reporter_id` must match its enrollment and is not trusted for authorization. Each process start gets an opaque UUID `startup_epoch`; sequence starts at 1 and strictly increases. | Draft's integer epoch must be migrated to UUID in the frozen schema; existing validators did not verify authenticated binding. | Frozen by ADR-SEN-020. Workers require distinct enrolled reporter identities; sequence never wraps past `2^53 - 1`; a new process epoch is required. |
| **D4 — FROZEN** Cumulative values and reset | Counters are cumulative within an epoch, safe JSON integers through `2^53 - 1`; nanosecond duration sums are canonical decimal strings up to 38 digits. Reset/missing baseline/epoch change produces no rate and requires rebaseline; values never wrap. | Existing Python/shared fixtures cover safe integer and exact decimal boundaries. | Frozen by ADR-SEN-020; Java/Go preserve decimal values exactly. |
| **D5 — FROZEN** Histogram | Inclusive upper-bound disjoint buckets + overflow; exact HTTP duration bounds are `1,5,10,25,50,100,250,500,1000,2000,5000,10000 ms`; merge only identical bounds; nearest-rank p95 from pooled deltas, never average reporter p95; empty/missing/overflow p95 unavailable. | Existing Sentinel histogram uses first nine bounds; wire profile adds `2,5,10 s` upper bounds. | Frozen by ADR-SEN-020; adding/reordering boundaries requires explicit schema revision. |
| **D6 — FROZEN** Record and resource bounds | 65,536 encoded UTF-8 bytes; 256 total records across arrays; at most 64 boundaries (exact HTTP profile uses 12); 200 Unicode scalar identifiers/resource labels; safe JSON integers; 38 digit decimal sums; 256 active resource series/reporter. | Existing validators cover most per-message bounds; series quota needs runtime enforcement. | Frozen by ADR-SEN-020. New series above quota are rejected, never silently evicted; arbitrary request/user labels remain prohibited. |
| **D7 — FROZEN** Cadence, stale and late data | Sample each second; stale after >3 missed intervals based on Collector `received_at`; never derive rate over >10 seconds of reporter elapsed time; rebaseline. Already-receipted duplicate is idempotent; unreceipted older sequence is rejected; late arrival never overwrites a newer baseline. | Runtime scheduler/Collector remain to implement. | Frozen by ADR-SEN-020. |
| **D8 — FROZEN** Aggregation and unavailable quality | Keep null; quality is available/partial/stale/no_samples/not_integrated. Sum deltas on a common valid interval, pool histogram counts, sum ratio numerator/denominator, never average reporter rates/ratios/p95. Unknown expected inventory stays unknown; zero attempted entries is unavailable. | Existing Console quality vocabulary and bounded `MetricsReader` are reused. | Frozen by ADR-SEN-020; do not synthesize zero or full coverage. |
| **D9 — FROZEN** Transport and authentication | HTTPS + mutual TLS; validate the peer certificate and resolve its principal to an enrolled reporter binding on every request. Reject missing/invalid/revoked/cross-scope identities. Client claims/headers are not authority. | No V2 transport/Collector currently exists; V1 transport is not reused. | Frozen by ADR-SEN-020; credential issuance, rotation/revocation and safe deployment are implementation/readiness requirements. |
| **D10 — FROZEN** Idempotency and durable ACK | Key is authenticated reporter + UUID epoch + sequence. Persist SHA-256 exact-body digest. Same key/digest returns original receipt; changed digest gives stable `idempotency_conflict`. Receipt and accepted samples are one transaction; ACK only after commit. | No V2 receipt/history runtime currently exists. | Frozen by ADR-SEN-020. |
| **D11 — FROZEN** Persistence and retention | Use the Console-selected SQL database; target dialects are SQLite, PostgreSQL, and MySQL. Raw receipt/snapshots: 24h; 1-minute UTC rollups: 30d. Explicit idempotent expiration and bounded queries; never Consul. Use consumer-owned Port, SQLAlchemy infrastructure Adapter, small ingest/query Facades, and a narrowly scoped Template Method only for proven transaction/dialect variation. | Existing Console persistence uses SQLAlchemy/Alembic and a consumer-owned `MetricsReader`. Source inspection found `RuntimeDatabaseEngineProvider` allows MySQL/PostgreSQL only; SQLite is present in bootstrap/migration/test paths, so its runtime composition is a known gap. Metrics-specific durable writer/reader is not implemented. | Frozen by ADR-SEN-020. Close SQLite runtime composition and test all three target dialects; future DB adds an isolated dialect adapter/migration and the same contract suite; no vendor branches in metric business logic. |
| **D12 — FROZEN** Cross-language compatibility | Strict typed records; reject unknown fields, duplicate JSON keys, invalid enum/time/decimal/integer values, and bound violations. Python/Java/Go use identical positive and negative fixtures. Exact V2 field set never silently widens; any wire change requires an explicit schema revision/protocol identifier and ADR. | Draft Python codec and test-only Java/Go validators already share fixtures (§15.1051). | Frozen by ADR-SEN-020; validators remain test-only until production SDK/runtime implementation. |
| **D13 — CONFIRMED (bounded scope)** Local Adapter enqueue behavior | Permit a brief wait for the in-memory mutex used to update bounded buffer state. At capacity, reject new identities instead of waiting; perform no network/database I/O on the Engine completion path. Do not claim wait-free behavior or a hard realtime latency bound. Preserve current exact drop/coalescing accounting; do not switch to try-lock/drop. | Owner confirmation recorded in §15.1079. Existing concurrency/capacity tests cover the unchanged mutex-protected state and accounting; §15.889 documents the observed contention behavior that prompted this decision. | No further D13 vote requested. This decides only the local Adapter lock/capacity contract; it does not approve Metrics V2 wire, Reporter/Collector, or production sending. |

## Decision record

- Product owner authorization: **D2–D12 candidate defaults frozen for implementation, 2026-10-14**.
- Independent record: [`ADR-SEN-020`](ADR-SEN-020-metrics-v2-freeze.md).
- D1 remains the previously confirmed metric semantics; D13 remains the previously confirmed bounded Adapter mutex behavior.
- Named role-specific sign-offs are not represented as received. Required security, database-dialect, and three-language runtime tests remain implementation/production-readiness gates.
- Existing `reporting.drafts` types are not automatically the final schema: align and migrate them to this decision, then freeze the JSON Schema and fixtures. Do not enable production sends until the TLS Collector, durable SQL receipt/history and contract matrix pass.
