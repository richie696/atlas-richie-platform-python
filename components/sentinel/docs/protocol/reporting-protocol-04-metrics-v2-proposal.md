# Agent Metrics Reporting V2 — Proposal (DRAFT)

> **Status:** Product decisions D2–D12 frozen for implementation by ADR-SEN-020 (2026-10-14). The JSON Schema/runtime implementation is not yet complete, and production sending remains disabled until the listed conformance, TLS, SQL, and integration gates pass.
> **Scope:** Close the real-metrics ingestion gap in Sentinel Dashboard B0.4.
> **Compatibility:** Preserve the frozen V1 event envelope and its six `event_kind` values. Metrics V2 is a separate typed contract; its approved wire/profile values are recorded in ADR-SEN-020. No Console API 0.4.0 changes are implied.
> **Last reviewed:** 2026-10-14

## 1. Why this proposal exists

The Dashboard already defines metrics queries and quality states, and Sentinel
has local metrics primitives. They are not yet connected by a production
Reporter/Collector path. The frozen Reporting V1 envelope is specifically an
event protocol: it does not carry generic metrics, raw RT, or system-resource
samples. Its outer transport is still a draft. Adding metric fields to a V1
event payload would violate the frozen contract and blur event and measurement
semantics.

This proposal therefore treats metrics as an explicit V2 extension of the
Agent Reporting family. It does not authorize changing V1 or claiming that a
Collector, durable metrics store, or production metrics reader already exists.

## 2. Existing facts and gaps

| Boundary | Current source evidence | Gap to close |
| --- | --- | --- |
| Sentinel entry metrics | `MetricRegistry.iter_snapshots()` returns process-lifetime per-label counters (`admitted`, `blocked`, `succeeded`, `failed`, `cancelled`) and a bounded latency histogram. A configured `MetricSink` now receives the changed label set's immutable cumulative snapshot synchronously after each recorded outcome; the default Noop path avoids constructing/emitting snapshots. | These snapshots are not a cross-process wire contract; the Dashboard needs explicitly defined rate and aggregation semantics. Any reporting sink may only enqueue in bounded local memory, must reject new work at capacity, and may not perform network/DB I/O on the Engine completion path. A brief mutex wait for in-memory state updates is permitted; this is not a wait-free or hard-realtime guarantee. |
| System metrics | `SystemMetricSampler` returns CPU, load, process RSS bytes and (when the process RSS and a finite visible limit are both known) memory ratio, event-loop lag, in-flight QPS, completed QPS, sample time, and a degraded flag. The stdlib implementation computes process CPU ratio only when a valid Linux cgroup v1/v2 CPU quota is readable; it reads process RSS from Linux procfs and walks visible cgroup v1/v2 ancestors to find the tightest finite memory limit. Unsupported platforms, unreadable procfs/cgroup state, or a missing finite limit remain unavailable. Event-loop lag remains unavailable. | A sample must preserve `null`/unavailable. This local process sampler does not provide host metrics and does not authorize a Reporting V2 wire or Console reader. A cgroup CPU gauge is process/quota scoped and does not represent host CPU. |
| HTTP/business metrics | The Console query model includes HTTP QPS, resource-entry rate, business TPS, RT p95, blocked ratio, CPU, memory ratio, and memory bytes. | Sentinel core counters alone do not prove HTTP request counts, business transaction counts, or memory measurements. Each metric needs an identified producer and denominator. |
| Reporting V1 | V1 freezes event envelopes only; generic metrics are excluded. The V1 transport document remains pending freeze. | Do not treat a V1 fake Collector or event transport as metrics ingestion. |
| Console | `MetricsReader` is an application port. Without a host authority, the SQL composition returns explicit `not_integrated` readings; generic `build_app()` without a reader remains unavailable. | No production Agent/Collector authority or historical query store is installed. |

## 3. Proposed boundaries

1. **Reporter owns local capture and bounded delivery.** Sampling and enqueueing
   must not perform network I/O or block the Sentinel request/entry path.
   Reporter preserves one process identity, `startup_epoch`, and monotonically
   increasing sequence within that epoch. Queue bounds, overflow behavior,
   shutdown, retry, and late acknowledgement behavior must be frozen as part
   of the transport contract.
2. **Metrics and events remain distinct record families.** Keep the V1 event
   envelope unchanged. V2 metric records use finite, typed per-kind payloads;
   no `dict[str, Any]`, raw logs, request/response bodies, user identity, or
   credentials. A metric batch may carry more than one typed record, but the
   protocol must bound both per-record and total encoded size.
3. **Counters are cumulative within an epoch.** Report cumulative monotonic
   counts with `captured_at`; do not reset counters on every scrape. The
   Collector computes rates only from two valid observations of the same
   reporter, epoch, and metric identity. A new epoch, counter decrease,
   excessive sample gap, or stale reporter starts a new baseline; it must not
   create a negative or fabricated rate.
4. **Histograms aggregate by bucket counts.** Freeze common bucket boundaries
   and bucket inclusivity/overflow semantics. Aggregate distributions by adding
   corresponding bucket counts, then compute pooled p95. Never average
   per-process p95 values. Missing histograms remain unavailable; zero samples
   are not a zero-latency observation.
5. **Gauges are instantaneous samples.** CPU, memory, load, and event-loop lag
   carry explicit units, capture time, and nullable values. The Console must not
   substitute zero for unsupported or failed sampling. Resource scope and
   denominator must be explicit; host/container/process values are not
   interchangeable.
6. **Identity is bound by the authenticated transport.** Environment and
   application ownership must come from trusted registration/credential claims
   or an explicitly reviewed enrollment contract, not arbitrary reporter
   fields. The Collector validates that the reporter may write only its bound
   identity. Tokens and certificate material never enter metric records,
   persistence, errors, or Dashboard responses.
7. **Collector acknowledges only durable acceptance.** The deduplication key is
   `(reporter_id, startup_epoch, sequence)`. A duplicate returns the original
   accepted outcome without duplicate samples. Ack must not precede the
   configured durable commit boundary. Old epochs cannot replace current
   instance state, but their in-window historical samples may be retained only
   under a separately frozen policy.
8. **Configured SQL storage owns history; Consul does not.** The Console-selected
   SQLite, PostgreSQL, or MySQL dialect stores accepted bounded
   metric samples/aggregates and the idempotency receipt. Consul remains a rule
   configuration source and is not used as a metric database or history store.
   Retention, partition/index strategy, compaction, and deletion semantics must
   be specified before the production reader is enabled.
9. **Console query ports remain provider-neutral.** A SQL-backed Collector/query
   implementation adapts to the existing `MetricsReader` and instance-catalog
   authority. The React application continues to call only Console HTTP; it
   never talks directly to Sentinel agents, MySQL, or Consul.

## 4. Metric producer mapping and wire decisions

The current Console read contract already declares a finite metric set and a
`MetricDenominator` aggregation-basis label in
`sentinel_console.domain.instance_catalog.OPERATIONAL_METRIC_DEFINITIONS`.
That label identifies the population/measurement basis associated with a
reading; it is **not** the arithmetic denominator used to turn a counter into
a rate. Rates use a valid elapsed interval, while ratios use their named
population count. The V2 wire must preserve this distinction instead of
overloading one `denominator` field with both meanings.

| Metric | Existing Console unit / aggregation basis | Owner-frozen observation and producer boundary | Remaining wire/profile decision before freeze |
| --- | --- | --- | --- |
| `http_qps` | `requests_per_second` / `completed_http_requests` | Completed HTTP response counter delta ÷ elapsed seconds; include completed 4xx/5xx responses; HTTP server/framework adapter, never infer from Sentinel entries | Freeze adapter identity, status/cancellation boundary representation, labels, and interval encoding |
| `resource_entry_rate` | `entries_per_second` / `attempted_entries` | `admitted + blocked` Sentinel entry counter delta ÷ elapsed seconds; Sentinel `MetricRegistry`; not HTTP QPS/TPS | Freeze resource identity encoding and cross-resource aggregation selection |
| `tps` | `transactions_per_second` / `business_transactions` | Application-declared completed transaction counter delta ÷ elapsed seconds; opt-in application instrumentation; unavailable until configured | Freeze explicit instrumentation API/record identity and interval encoding |
| `rt_p95` | `milliseconds` / `completed_http_requests` | Pooled histogram of completed HTTP request durations at the same declared request boundary as `http_qps`; missing data or overflow is unavailable | Freeze bucket boundaries, inclusivity/overflow representation, and wire encoding; Sentinel entry RT is not interchangeable absent an explicit one-to-one mapping |
| `blocked_ratio` | `ratio` / `attempted_entries` | Blocked entry delta ÷ attempted-entry delta for the same resource population and interval; missing denominator is unavailable | Freeze zero-denominator quality representation and cross-resource aggregation selection |
| `cpu_ratio` | `ratio` / `cpu_cores` | Process CPU consumption only; insufficient collection conditions are unavailable | Freeze process CPU normalization, platform capability representation, and collection cadence |
| `memory_ratio` | `ratio` / `memory_limit_bytes` | Process used bytes ÷ verified effective process limit; insufficient collection conditions or missing verified limit is unavailable | Freeze effective-limit provenance/representation and collection cadence |
| `memory_bytes` | `bytes` / `reporting_processes` | Process RSS bytes; process scope only; insufficient collection conditions are unavailable | Freeze reporter population semantics and missing-sample quality representation |

This table reconciles the existing Dashboard DTO vocabulary with the metric
semantics frozen in §4.1. ADR-SEN-020 freezes the wire/profile defaults needed
to encode these semantics. Runtime implementation and acceptance remain open.
The existing denominator enum is an API aggregation-basis fact, not the elapsed
time arithmetic for a rate.

The producer mapping is intentionally not declared complete. Existing
`DefaultSystemMetricSampler` does not provide CPU usage or memory usage on all
platforms. A Dashboard chart may show `not_integrated` or partial coverage until
the corresponding producer is actually configured and observed.

### 4.1 Owner-frozen metric semantics (2026-10-13); wire remains draft

The product owner approved the following metric producer, meaning, and scope
semantics on 2026-10-13. ADR-SEN-020 separately freezes the D2–D12
wire/profile defaults for implementation on 2026-10-14. Neither approval
claims that the runtime path has been implemented or accepted.

| Metric | Candidate producer/definition | Scope and unavailable behavior |
| --- | --- | --- |
| `http_qps` | HTTP server adapter increments a cumulative completed-response counter; include all completed status classes, including 4xx/5xx. Collector computes its rate over a valid interval. | Process scope; unavailable if no HTTP adapter is installed. Never infer from Sentinel entries. |
| `resource_entry_rate` | Sentinel records cumulative `admitted + blocked` resource-entry counts. Collector computes their sum delta over a valid interval. | Process/resource scope; never infer an HTTP request or business transaction. |
| `tps` | Explicit application instrumentation records completed business transactions. No automatic HTTP or Sentinel-entry mapping. | Application-declared process scope; unavailable until explicitly instrumented. |
| `rt_p95` | Use a merged histogram at the same HTTP boundary as `http_qps`; pool bucket deltas and calculate p95 from merged counts, never average per-reporter p95s. | HTTP boundary. Missing histogram data or overflow makes the value unavailable. |
| `blocked_ratio` | Blocked entries divided by attempted entries (`admitted + blocked`) for the same selected resource population and interval. | Process/resource scope; unavailable when the denominator is missing. |
| `cpu_ratio` | Report process CPU usage only; do not substitute host CPU. | Process scope; unavailable when collection conditions are insufficient. |
| `memory_bytes` / `memory_ratio` | Report process memory only; a ratio requires a verified positive effective limit. | Process scope; unavailable when collection conditions or the verified limit required by the metric are insufficient. |

Common candidate rules: reporters send cumulative counters within one
`startup_epoch`; the Collector derives interval rates only from two valid
samples for the same authenticated reporter and metric identity. Resets,
identity changes, invalid elapsed time, stale gaps, unsupported scope, or
missing histogram data break the baseline and produce unavailable/partial
quality rather than a fabricated numeric value. Resource labels remain
bounded; arbitrary business labels and request/user dimensions are forbidden.

The candidate histogram `total_ns` is encoded as a canonical decimal string
with at most 38 digits, not a JSON number. It is a cumulative nanosecond sum
and can exceed JavaScript's exact integer range during normal long-running,
high-throughput operation. Python stores it as an integer; Java uses
`BigInteger`, Go uses `math/big.Int`, and storage uses an exact decimal numeric
column. Counts and bounded gauge/identity fields retain their own integer or
number limits. This is a DRAFT codec decision only; it does not freeze the V2
wire or authorize production transport.

The exact histogram boundary list, sample cadence/staleness thresholds,
resource cardinality limit, CPU quota interpretation across operating systems,
and request cancellation/status semantics were frozen for implementation by
ADR-SEN-020 on 2026-10-14. Current `LatencyHistogram` can merge only
identical boundaries and reports no finite p95 when the nearest-rank falls in
overflow; that is a useful implementation primitive, not by itself the V2
cross-language boundary definition.

## 5. Query and aggregation rules

- Query windows remain UTC half-open intervals and use the existing bounded
  `MetricQuery` selection and `MetricsReader` contract.
- Fleet/application rates are calculated from summed counter deltas over the
  same valid time interval. Do not average instance QPS or blocked ratios.
- RT p95 is calculated from pooled histogram bucket deltas; do not average
  p95 values.
- A sample's capture time is reporter-local diagnostic time. Collector
  `received_at` is server-owned and is the authority for ingestion order,
  freshness, and retention. Reporter MUST NOT send a claimed `received_at`.
- **Rate interval clock (frozen by ADR-SEN-020):** Do not use the
  reporter wall-clock `captured_at` for rate arithmetic: NTP/manual clock
  adjustments can move it backwards or change elapsed intervals, and its
  value is diagnostic only. Do not silently substitute Collector
  `received_at` either: network delay, retries, batching, and queueing can
  distort the producer interval. The frozen interval source is
  `capture_elapsed_ns`, a canonical decimal-string reporter monotonic elapsed
  value captured with each cumulative snapshot and comparable only within the
  authenticated `(reporter_id, startup_epoch)`;
  it preserves `captured_at` for diagnostics and `received_at` for Collector-
  owned freshness/retention. Restart/overflow handling follows ADR-SEN-020. A long gap, clock
  discontinuity, sequence regression, or invalid elapsed value must produce
  unavailable quality, not a fabricated rate.
- Coverage distinguishes expected reporters from reporting reporters. If
  expected inventory is not authoritative, report unknown coverage rather than
  inventing a denominator.
- Staleness, late samples, duplicate sequence, counter reset, unsupported
  scope, and partial coverage have distinct quality outcomes. Missing values
  stay `null`/unavailable, never numeric zero.

## 6. Security, bounds, and operations

ADR-SEN-020 freezes message/resource cardinality, series, cadence, and
retention limits. Reporter retry deadlines/backoff remain bounded
implementation reliability parameters; query-window limits remain those of
the existing Console API. Resource labels are the only permitted
high-cardinality dimension and remain quota-bound; over-quota new series are
rejected and counted locally, never silently expanded.

The production transport must support authenticated non-loopback deployment
before a cross-pod or cross-host Dashboard acceptance can be claimed. The
loopback-only V1 draft is not sufficient evidence for that deployment. TLS,
credential issuance/rotation, server authorization, rate limiting, error
redaction, and per-reporter isolation need an explicit security review. Local
development may use an explicitly named insecure profile only if the accepted
contract permits it and startup cannot accidentally select it in production.

## 7. Proposed implementation sequence

1. **Complete (2026-10-13):** review the producer mapping and freeze metric
   definitions, units, scopes, and ratio denominators in §4.1 / M6.5.8a.
2. Freeze a typed V2 metric schema, authentication/identity binding, bounds,
   acknowledgement/idempotency, transport, and compatibility rules; record an
   independent ADR and owner sign-off. Keep V1 event schema immutable.
3. Implement language-neutral schema fixtures and Python/Java/Go codec
   contract tests before enabling network writes.
4. Implement the local Sentinel metric capture Adapter and independent
   in-process Metrics Reporting Port as a separate, non-wire slice. Only after
   the V2 contract is frozen, connect a Reporter transport; retain bounded
   storage, overflow accounting, and graceful shutdown semantics.
5. Implement the authenticated Console Collector, durable SQL idempotency and
   history store, and SQL-backed `MetricsReader`; include process restart,
   duplicate batch, stale epoch, counter reset, and lease-free multi-reporter
   aggregation tests as appropriate.
6. Wire the explicit production composition. Keep unconfigured metrics
   unavailable; do not enable mock fallback in live mode.
7. Run component integration against disposable MySQL and final React→Python
   browser E2E. Consul is included in the final product flow only for rule
   source operations; it is not a metrics dependency. Delete only the temporary
   containers created by that E2E run.

### 7.1 Current code prototype (not yet aligned to frozen V2)

`foundation/contracts/src/atlas_richie/contracts/reporting/drafts/metrics_v2.py`
contains frozen in-process candidate value objects for cumulative counters,
histogram buckets, gauges, and snapshot identity. It is deliberately isolated
under `reporting.drafts`; it is not re-exported from `reporting.v1` and is not
imported by Sentinel runtime, Reporter, Collector, or Console composition. The
paired `metrics_v2_codec.py` uses an explicit `atlas-richie.metrics/v2-draft`
marker, rejects duplicate/unknown fields, invalid types and non-finite JSON,
and applies provisional 64 KiB / 256-record bounds. These values and names are
review candidates only, not a frozen contract. Tests lock only local type,
codec, and invariant behavior. `calculate_counter_rate_draft` derives a rate only within
one reporter/epoch and strictly increasing sequence/time; missing baselines,
resets, and invalid ordering produce explicit non-value states. It intentionally
does not choose a stale-gap threshold or aggregate different reporters. These
helpers do not resolve the review items in §6/§9, establish a
cross-language schema, or authorize production transmission. Histogram deltas
currently support only per-reporter interval derivation and p95 evaluation;
they deliberately do not expose cross-reporter pooling because the draft has no
frozen shared-window/alignment identity. Do not combine deltas merely because
their metric name, resource, and bucket boundaries match. Before adding a
transport, protocol owners must still approve field names, bounded integer ranges,
histogram boundaries, identity/auth binding, and size/cardinality limits.
**Important review correction:** the original draft helpers calculated elapsed
time by subtracting `captured_at` wall-clock timestamps, which conflicted with
§5's diagnostic-only meaning. The current isolated draft candidate now uses
`capture_elapsed_ns` for rate arithmetic and includes a wall-clock-regression
test. M6.5.8b must still approve the interval-clock semantics and encoding, then
review reset/overflow/staleness behavior before production use; the candidate
DTO/schema/codecs/fixtures do not constitute that approval.
The candidate JSON Schema and shared fixtures now live under
`foundation/contracts/schemas/reporting/metrics-v2-draft.schema.json` and
`foundation/contracts/tests/reporting/metrics_v2_draft/fixtures/`. Python plus
test-only Java and Go validators exercise the shared fixtures through
`foundation/contracts/tools/test_metrics_v2_draft_conformance.sh`. These
validators are not production SDKs or owner-approved codecs. JSON Schema is not
treated as sufficient for duplicate-key rejection or cross-field histogram
and availability invariants. The runner also enforces valid/invalid filename
classification so adding a fixture without exercising it cannot silently pass.
The candidate schema encodes cumulative histogram `total_ns` as a canonical
38-digit decimal string so high-throughput cumulative duration sums remain
exact across languages; other bounded JSON integer fields retain the safe
integer policy.

The draft value-object module also contains a pure histogram interval helper:
it subtracts cumulative bucket counts only for the same reporter/epoch,
monotonic sequence/time, histogram identity, and unchanged boundaries; a
decrease requires a new baseline rather than producing negative counts. It can
calculate nearest-rank p95 for one interval delta, returning unavailable when
the rank falls in the overflow bucket. Cross-reporter interval pooling is
intentionally absent until the protocol defines how reporters map to one
shared aggregation window. This helper does not define the pending wire
bucket inclusivity, stale-gap, or boundary policy, and it is not imported by
Sentinel runtime, Reporter, Collector, or Console.

## 8. Approved design boundaries and pattern use

- **Adapter — approved:** Sentinel `MetricSnapshot` and
  `SystemSnapshot` have different source semantics than the Dashboard's metric
  DTO. A narrow producer adapter should map them into typed protocol records
  without leaking Console types into Sentinel core or SDK types into the wire.
- **Observer/event publication — reuse only where fact semantics fit:** the
  existing `MetricSink` is a synchronous local capture seam. Its production
  adapter may enqueue immutable snapshots, but must not synchronously call a
  network Collector. This is a local capture/queue boundary, not an excuse to
  reuse the frozen V1 event envelope for measurements.
- **Strategy — not currently justified:** the product has not selected multiple
  metrics providers. Keep the Console `MetricsReader` as the existing consumer
  port; do not introduce provider strategies until a real alternative exists.
- **Repository — implementation detail:** durable SQL history is owned by the
  Collector/query implementation and should follow the existing Console
  persistence conventions; do not expose ORM entities across the application
  port.
- **Facade — approved:** a small ingest Facade owns request orchestration and
  durable-ACK result mapping; a separate query Facade composes the existing
  consumer-owned `MetricsReader`. Neither is a generic SQL service locator.
- **SQL Adapter — approved:** `MetricsHistoryPort` is consumer-owned and its
  SQLAlchemy infrastructure adapter uses the selected Console engine. Target
  SQLite, PostgreSQL, and MySQL share one storage contract. Proven dialect-only
  primitives belong in narrow adapters/migrations, not metric business logic.
- **Template Method — conditional and narrow:** use only around the invariant
  durable ingest order (claim receipt → store accepted records → commit → ACK)
  when a real dialect variation needs hooks. Do not add a base class merely to
  satisfy the pattern checklist; prefer composition when SQLAlchemy's portable
  transaction path suffices.

**Owner decision (2026-10-11):** the Sentinel-side Adapter boundary is
approved for local capture only: adapt `MetricRegistry` and
`SystemMetricSampler` snapshots to an independent, bounded,
non-networking `MetricsReportingPort`. This approval does not freeze Metrics
V2, authorize importing draft records into Sentinel runtime, or authorize a
Reporter transport, Collector, SQL history, or Console metrics reader. The
implementation is recorded in §15.740 of the Dashboard progress tracker.

**Owner decision (2026-10-13):** the local Adapter contract permits a brief
wait for the in-memory mutex used to update bounded state. Enqueue remains
local and bounded: a full buffer rejects a new identity rather than waiting
for capacity, and the Engine completion path performs no network or database
I/O. This is not a wait-free API and promises neither a maximum mutex wait nor
a hard-realtime latency bound. The existing exact drop/coalescing accounting
semantics remain unchanged; do not replace the mutex with try-lock/drop.

ADR-SEN-020 authorizes implementation of the frozen defaults, but this proposal
alone is not production acceptance. The wire/runtime code, security path, and
durable storage remain to be implemented and verified.

## 9. Review/sign-off checklist

- [x] Product owner authorized the D2–D12 implementation defaults in
  ADR-SEN-020 on 2026-10-14; separate named role signatures are not fabricated.
- [x] Sentinel / performance owner permits brief mutex-protected local state
  updates; capacity remains non-waiting/rejecting, and no wait-free or hard-
  realtime guarantee is made. Exact rejection/coalescing accounting remains
  unchanged (§15.1079).
- [ ] Security identity/TLS behavior is verified by implementation tests.
- [ ] SQLite/PostgreSQL/MySQL shared storage contract, retention and deletion
  behavior pass adapter integration tests.
- [ ] Java/Go/Python runtimes validate the frozen shared schema/fixtures.
- [ ] Dashboard owner approves quality/staleness/coverage projection and the
  unavailable behavior before live charts are enabled.
