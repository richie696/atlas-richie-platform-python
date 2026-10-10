# B0.1 — Observation catalog read API

## Scope

Implement the Python `GET /api/v1/observation/catalog` contract for environment
and application selectors. This slice adds no catalog persistence/collector
adapter and does not seed demo data. Until a host-owned reader is composed, the
endpoint returns a safe `503 service_unavailable` response.

## Ownership and design

- `ObservationCatalogReader` is the minimal Console application Port for the
  authoritative catalog read; a later host adapter owns its source and storage.
- Frozen domain values own the bounded facts and basic invariants. The API
  adapter owns session authorization, wire names, timestamp serialization and
  safe failure mapping.
- Admin and view roles may read; anonymous requests are rejected. Catalog
  authority failures are not converted into empty lists or fabricated scope.
- This is a straightforward read use case reusing the established Console
  route/application/Port structure; no new GoF pattern is needed.

## Focused test matrix

| ID | Layer | Preconditions / action | Assertions |
| --- | --- | --- | --- |
| B0.1-CATALOG-1 | HTTP | Admin and view read catalog snapshot | Exact schema fields, UTC millisecond time, `no-store`, `Vary: Cookie` |
| B0.1-CATALOG-2 | Authorization | Anonymous request | 401; reader is not called |
| B0.1-CATALOG-3 | Validation | Invalid request ID or unavailable session | Finite 400/503; no internal detail |
| B0.1-CATALOG-4 | Failure | Missing or unavailable catalog authority | 503 `service_unavailable`; no fabricated empty catalog |
| B0.1-CATALOG-5 | Domain | Invalid time, blank identity, empty name or over-bound collection | Value construction rejects invalid facts |

## Verification record

- `PYTHONPATH=src .venv/bin/pytest -q tests/test_observation_catalog_api.py tests/test_system_connections_api.py tests/test_system_protocols_api.py tests/test_system_audit_api.py tests/test_registered_sources_api.py` — **26 passed**.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/atlas_richie/sentinel_console tests/test_observation_catalog_api.py` — passed.
- 88-column check for changed Python source and `git diff --check` — passed.

This is a focused API slice, not production catalog composition, React-to-Python
live integration, or browser E2E. The default `build_app` composition has no
catalog reader and correctly remains unavailable.
