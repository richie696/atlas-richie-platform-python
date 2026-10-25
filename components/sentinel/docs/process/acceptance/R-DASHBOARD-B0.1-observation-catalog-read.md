# B0.1 — Observation catalog read API

## Scope

Implement the Python `GET /api/v1/observation/catalog` contract for environment
and application selectors. This slice adds no separate catalog table and does
not seed demo data. The default SQL host composition supplies a Metrics V2
reader that projects identities only from non-revoked Reporter bindings with
an accepted snapshot (`current_epoch` and `last_received_at`). Enrollment has
no display-name field, so each authoritative identifier is also the selector
name. An empty authoritative set returns an empty catalog; database or invalid
authority failures remain `503 service_unavailable`.

## Ownership and design

- `ObservationCatalogReader` is the minimal Console application Port for the
  authoritative catalog read; `SQLAlchemyMetricsObservationCatalogReader` is
  its default SQL adapter and reads persisted Metrics V2 facts through the
  selected runtime database engine.
- Frozen domain values own the bounded facts and basic invariants. The API
  adapter owns session authorization, wire names, timestamp serialization and
  safe failure mapping.
- Admin and view roles may read; anonymous requests are rejected. Catalog
  authority failures are not converted into empty lists or fabricated scope.
- This is a straightforward read use case reusing the established Console
  route/application/Port structure. The SQL adapter translates existing
  domain-owned facts and does not add a general database abstraction.

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
- Real SQL adapter tests cover active, duplicate, unobserved, and revoked
  Reporter identities, empty authoritative state, and clock validation.
- Default SQL identity composition wires the adapter while preserving explicit
  reader injection for a host-owned alternative.
- `uv run --extra test pytest -q tests/test_metrics_observation_catalog_reader.py tests/test_observation_catalog_api.py tests/test_identity_composition.py` — **17 passed**.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/atlas_richie/sentinel_console tests/test_observation_catalog_api.py` — passed.
- 88-column check for changed Python source and `git diff --check` — passed.

This verifies the default SQL reader with real SQLite migrations. PostgreSQL
and MySQL use the same SQLAlchemy reader but remain part of complete live T07.1
composition and browser-to-service acceptance. It does not prove Metrics V2
data has been produced or that any chart is populated.
