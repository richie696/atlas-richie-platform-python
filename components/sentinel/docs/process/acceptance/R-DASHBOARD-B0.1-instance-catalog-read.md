# B0.1 — Instance catalog read API

## Scope

Implement the Python `GET /api/v1/instances` contract for the authenticated,
paged instance directory and its process-level operational summaries. This
slice adds no production inventory/telemetry adapter, collector, persistence, or
demo fallback. Without a host-owned reader, the route returns
`503 service_unavailable`.

## Ownership and design

- `InstanceCatalogReader` is the consumer-owned authority Port. Its host adapter
  owns inventory, telemetry, and request-budget policy; it must return one
  exact, query-bound snapshot.
- Frozen domain values own scope, time-window, paging, coverage, metric,
  incarnation, receipt, and count invariants. The API adapter owns session
  authorization, strict query parsing, UTC-millisecond wire projection, and
  finite error mapping.
- Catalog scope is restricted to fleet (no `appId`) or application (`appId`);
  detail identities and resource selectors are not catalog filters. Host,
  container, and process scopes belong to the detail operation.
- Admin/view sessions have `metrics:view`; anonymous sessions are rejected.
  Missing/unavailable authority is never represented as an empty list.
- This reuses the established Console route/application/Port structure; no new
  GoF pattern is introduced.

## Focused test matrix

| ID | Layer | Preconditions / action | Assertions |
| --- | --- | --- | --- |
| B0.1-INSTANCE-1 | HTTP | Admin and view read a query-bound page | Exact projection, UTC milliseconds, `no-store`, `Vary: Cookie` |
| B0.1-INSTANCE-2 | Authorization | Anonymous or unavailable session | 401/503; reader is not called; no internal detail |
| B0.1-INSTANCE-3 | Validation | Missing, duplicate, unknown, malformed, or contradictory query | 400 `invalid_request`; authority is not called |
| B0.1-INSTANCE-4 | Authority | Missing/unavailable reader, missing target, rate-limited query | 503/404/429 finite codes; bounded retry delay |
| B0.1-INSTANCE-5 | Domain | Mixed process epoch, invalid receipt/count/page/metric facts | Construction rejects inconsistent facts |

## Verification record

- `PYTHONPATH=src .venv/bin/pytest -q tests/test_instance_catalog_api.py tests/test_observation_catalog_api.py tests/test_system_connections_api.py tests/test_system_protocols_api.py tests/test_system_audit_api.py tests/test_registered_sources_api.py` — **33 passed**.
- `.venv/bin/python -m compileall -q src/atlas_richie/sentinel_console tests/test_instance_catalog_api.py` — passed.
- `npm run contract:check` in `dashboard-prototype` — passed; 42 OpenAPI paths verified.
- 88-column check for changed Python files and `git diff --check` — passed.

This is a focused backend contract slice, not production composition, live
React-to-Python integration, deployment, or browser E2E. Full E2E remains
reserved for the agreed milestone gates.
