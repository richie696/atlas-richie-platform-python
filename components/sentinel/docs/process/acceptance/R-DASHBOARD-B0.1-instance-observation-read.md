# B0.1 — Instance observation detail API

## Scope

Implement `GET /api/v1/instances/{instanceId}` for one exact application,
environment, process epoch, requested collection scope, and bounded metric
window. This slice adds no production inventory/telemetry adapter or Collector.
Without a host-owned reader, the endpoint returns `503 service_unavailable`.

## Ownership and contract

- `InstanceObservationReader` is a consumer-owned Port. The host adapter owns
  current-incarnation lookup, supported-scope facts, metric authority, and
  rate-budget policy.
- Immutable domain records reject mismatched process epochs, metric selections,
  sample windows, unsupported-scope data, invalid ordering, excess samples, and
  missing/incorrect coverage semantics.
- The requested target is composed from the path instance ID plus required
  `appId`, `environmentId`, `processEpoch`, scope, window, and step query facts.
  The API does not accept a duplicate instance ID in query parameters.
- An unsupported host/container/process scope is an explicit instance fact
  with `metrics: null`; the adapter must never substitute another scope's
  measurements. A retired process incarnation returns `410 target_retired`.
- Admin/view sessions with `metrics:view` may read. Internal authority errors
  are redacted; the route distinguishes missing target, retired incarnation,
  rate limit, and unavailable authority.
- Catalog/detail projections share one serializer for instance identity,
  receipt, coverage, and process metrics.

## Focused test matrix

| ID | Layer | Preconditions / action | Assertions |
| --- | --- | --- | --- |
| B0.1-DETAIL-1 | HTTP | Admin/view reads current process detail | Exact query echo, receipt/metrics epoch, six operational summaries, no-store |
| B0.1-DETAIL-2 | Domain | Requested collection scope unsupported | `metrics` is null; no metric borrowing |
| B0.1-DETAIL-3 | Validation | Invalid scope/query or wrong query-bound snapshot | 400 or safe 503 before returning data |
| B0.1-DETAIL-4 | Authority | Target missing, epoch retired, limited, unavailable | 404/410/429/503 finite codes; internal detail redacted |

## Verification record

- `PYTHONPATH=src .venv/bin/pytest -q tests/test_instance_catalog_api.py tests/test_observation_catalog_api.py tests/test_system_connections_api.py tests/test_system_protocols_api.py tests/test_system_audit_api.py tests/test_registered_sources_api.py` — **37 passed**.
- `.venv/bin/python -m compileall -q src/atlas_richie/sentinel_console tests/test_instance_catalog_api.py` — passed.
- `npm run contract:check` in `dashboard-prototype` — passed; OpenAPI verified 42 paths.
- 88-column check for changed Python source and `git diff --check` — passed.

This is a focused HTTP/domain verification, not production composition,
database/Collector integration, live React-to-Python traffic, or browser E2E.
Full E2E remains reserved for agreed milestone gates.
