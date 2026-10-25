# B0.1 — Generic metrics query API

## Scope

Implement `GET /api/v1/metrics/query` for an explicit observation scope,
half-open UTC window, metric selection, and sampling step. This slice adds no
Reporter/Collector, metric store, or production aggregation adapter. If a host
does not compose `MetricsReader`, the route returns `503 service_unavailable`.

## Ownership and contract

- `MetricsReader` is the consumer-owned query authority. It owns aggregation,
  inventory denominator, source quality, and query rate budget; the Console
  does not calculate, fill, or infer metric values.
- `ObservationContext`, `MetricQuery`, `MetricBundle`, `MetricSeries`, and
  annotation values enforce query identity, supported metric IDs/units,
  denominator/quality, exact selected metric cardinality, sample ordering and
  bounds, and half-open window alignment.
- Query parameters are strict and unique. `metrics` is one bounded,
  comma-separated list; duplicate/unknown IDs, oversized series, unknown query
  fields, and invalid timestamps are rejected before authority access.
- Admin/view with `metrics:view` may read. Missing targets, retired incarnations,
  rate limiting, and unavailable authority use their finite OpenAPI errors.
- The bundle serializer is shared with instance detail, so both routes use the
  same metric and context projection.

## Focused test matrix

| ID | Layer | Preconditions / action | Assertions |
| --- | --- | --- | --- |
| B0.1-METRICS-1 | HTTP | View queries exact fleet metric selection | Query echo, summaries/series, no-store, reader gets exact query |
| B0.1-METRICS-2 | Validation | Duplicate metric, malformed scope/time/step, duplicate/unknown fields | 400 `invalid_request`; no authority read |
| B0.1-METRICS-3 | Authority | Missing target, retired process, rate-limited, unavailable | 404/410/429/503 finite codes; private details redacted |
| B0.1-METRICS-4 | Domain | Wrong query echo, duplicate/missing metric, unordered/out-of-window samples | Bundle construction rejects inconsistent facts |

## Verification record

- `PYTHONPATH=src .venv/bin/pytest -q` — **166 passed, 1 skipped** across the
  full Python Console suite (15 existing HTTPX per-request-cookie deprecation
  warnings remain in bootstrap database-check tests).
- `.venv/bin/python -m compileall -q src/atlas_richie/sentinel_console tests` — passed.
- `npm run contract:check` in `dashboard-prototype` — passed; OpenAPI verified
  42 paths.
- 88-column check for changed Python sources and `git diff --check` — passed.

No live metrics authority, Reporter/Collector, production DB, deployed
React-to-Python traffic, or browser E2E was exercised. Full E2E remains a
milestone-only gate.
