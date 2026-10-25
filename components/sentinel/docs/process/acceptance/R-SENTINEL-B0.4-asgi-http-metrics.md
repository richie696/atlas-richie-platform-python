# B0.4 ASGI HTTP metrics producer slice

Status: locally implemented; not a B0.4 or protocol sign-off.

## Scope

The pure ASGI adapter may optionally record process-local completed HTTP
request counts and a bounded response-time histogram. Metrics are opt-in via
`SentinelASGIMiddleware(http_metrics=...)`; without that collaborator the
existing middleware path does not collect these values. A completed response
counts only after the final body send succeeds, or after the final trailer send
when the ASGI response declares trailers; a successful `http.response.pathsend`
is also a final-send signal when trailers are not expected. The producer includes completed
responses regardless of HTTP status and retains no route, status, header,
identity, request-body, or response-body dimensions.

The snapshot is a local cumulative count plus the mergeable histogram. It is
not itself a QPS time series, TPS, Console `MetricsReader`, reporter payload,
cross-process aggregate, durable history, or a frozen Metrics V2 wire format.
No network client, Collector, SQL store, or provider dependency is added.

## Focused acceptance

- [x] Bounded histogram places inclusive-boundary, overflow, and invalid
  samples correctly; aggregate count matches histogram sample count.
- [x] Concurrent producers preserve count/histogram consistency.
- [x] Normal and error-status completed responses are counted only after a
  successful final ASGI send.
- [x] Streaming responses are counted at end-of-body, not at the first chunk.
- [x] Trailer-enabled responses are counted only at the final trailer; missing
  trailers do not cause premature completion.
- [x] Successful file `pathsend` is counted without retaining its filesystem
  path; failed `pathsend` is not counted.
- [x] Failed send, application exception before completion, and non-HTTP scope
  do not increment the HTTP count.
- [x] Duplicate completion messages cannot increment the counter twice.
- [x] Snapshot DTO exposes only bounded aggregate fields and no request-derived
  dimensions.

Focused tests: `sentinel-adapter-asgi/tests/test_http_metrics.py` plus the
existing ASGI middleware suite; Sentinel metric registry/engine tests cover
the shared histogram contract.

Current-worktree verification (2026-10-12):

- `uv run --directory components/sentinel/sentinel-adapter-asgi --extra test pytest -q`: **34 passed** (full ASGI adapter suite, including the HTTP metrics producer).
- `uv run --directory components/sentinel/sentinel --extra test pytest -q tests/test_metrics_capture_adapter.py tests/test_sen_engine_metrics.py tests/test_metric_registry.py`: **33 passed** (local capture adapter, Engine metrics, and registry/histogram contract).
- `git diff --check` is recorded with tracker entry §15.937.

Producer-semantic refresh (2026-10-13):

- The completed-response test now explicitly covers HTTP 400, 404, 429, and 503;
  the internal typed-capture path checks both a 4xx and a 5xx sample. This
  confirms status class does not affect inclusion after successful response
  completion and does not add a status label to the bounded snapshot.
- `uv run --project . --extra test pytest -q tests/test_http_metrics.py` from
  `components/sentinel/sentinel-adapter-asgi`: **19 passed**.
- `uv run --project . --extra test pytest -q tests/test_metrics_capture_adapter.py tests/test_sen_engine_metrics.py tests/test_metric_registry.py tests/test_default_system_metric_sampler.py`
  from `components/sentinel/sentinel`: **46 passed**.
- `git diff --check` passed. The local environment does not provide Ruff, so
  no Ruff result is claimed. This is producer-semantic coverage only; it does
  not close Metrics V2 wire, Reporter/Collector, SQL history, or B0.4.

## Local metrics-capture adapter (implementation only)

The private `MetricsCaptureAdapter` adapts entry `MetricSnapshot` values from
the existing `MetricSink` seam and `SystemSnapshot` values from a wrapped
`SystemMetricSampler` into a distinct in-process `MetricsReportingPort`. Its
bounded buffer keeps the latest cumulative capture per source/label identity,
coalesces existing identities, and counts/rejects new identities at capacity.
The port is not a wire envelope and is not wired to `AgentReporter`, a
Collector, or SQL. Captures are typed and retain their source snapshots; no
V1 event kinds, Reporter identity/sequence, durable acknowledgement, or V2
schema fields are assigned here.

Focused tests: `sentinel/tests/test_metrics_capture_adapter.py` covers source
mapping, sync/async sampler preservation, coalescing, bounded overflow,
capacity/type validation, and concurrent producers. This remains local
implementation evidence, not a B0.4 or protocol sign-off.

If the reporting port raises any ordinary `Exception` while a wrapped system
sampler returns a valid sample, the adapter preserves that sample and keeps
system admission independent from the reporting failure. The adapter records
only a failure count and exception class name; it does not retain or expose
the exception message. Process-level exceptions such as `KeyboardInterrupt`
and `SystemExit` are not swallowed. The entry `MetricSink` path keeps its
existing Engine failure-isolation behavior.

The optional `SystemMetricLifecycle` capability pairs process sampler entry
accounting with terminal outcomes. `SystemSlot` records only inbound entries
it admits; the Engine notifies only Slots that actually admitted an entry,
including those released after a later Slot rejects it. The capture adapter
preserves this capability when the wrapped sampler supports it. Focused
Engine, SystemSlot, sampler, and capture-adapter tests cover success and
later-admission-block cleanup. These counters support process-local snapshots;
they do not create a periodic sampler, transport, or durable history.

## Not accepted here

This slice does not claim Console chart delivery, reporting protocol
compatibility, fleet aggregation, cross-platform process metrics, MySQL/Consul
integration, production deployment, or browser E2E. Metrics V2 remains DRAFT;
full Docker-backed React-to-Python E2E remains reserved for the final gate.
