# B0.1 — Registered source registry read API

## Scope

Implement the Python `GET /api/v1/system/sources` consumer contract. This slice
reads only the authoritative server-owned registry snapshot and projects safe
metadata. It does not register sources, probe Nacos/Consul, access their
credentials, write configuration, or create a production persistence provider.
The route remains explicitly unavailable (503) until a trusted reader is
composed.

## Ownership and design

- `RegisteredSourcesReader` is the Console application port for the existing
  source-registry read capability; a future durable registry adapter owns the
  persistence mapping.
- Immutable domain records include source ID/revision/name/endpoint/provider,
  provider location, authentication mode, and only the boolean
  `credential_configured`. They have no credential or reference-value field.
- The HTTP adapter requires an active admin session, emits a bounded UTC
  snapshot, and never treats this registry read as a connection health check.
- Existing Nacos and Consul identities are finite enum variants. No new GoF
  pattern is required for this read path; vendor SDK adaptation belongs to a
  later provider integration, not this API.

## Focused test matrix

| ID | Layer | Preconditions / action | Assertions |
| --- | --- | --- | --- |
| B0.1-SOURCES-1 | HTTP | Active admin reads a snapshot containing Nacos and Consul | Exact provider-specific wire fields, UTC milliseconds, `no-store`, `Vary: Cookie`; no secret/reference fields |
| B0.1-SOURCES-2 | Authorization | Active `view` requests the registry | 403 `forbidden`; reader is not called |
| B0.1-SOURCES-3 | Authorization | Anonymous session or invalid request ID | Finite 401/400 response; reader is not called |
| B0.1-SOURCES-4 | Failure | Missing/failed reader or unavailable session authority | Safe 503 `service_unavailable`; no internal failure text |
| B0.1-SOURCES-5 | Domain | Invalid endpoint, auth/credential contradiction, duplicate IDs, excessive count, or naive time | Snapshot/record construction rejects invalid facts |

## Verification record

- `PYTHONPATH=src .venv/bin/pytest -q tests/test_registered_sources_api.py tests/test_system_connections_api.py` —
  **10 passed**. Covers Nacos/Consul projections, admin-only access, anonymous
  and malformed request rejection, safe 503 paths, domain bounds, and the
  shared provider enum regression.
- `python -m compileall -q` for the new route/application/domain modules and
  `git diff --check` — passed.

This record is a focused API acceptance slice, not production registry
persistence, real Nacos or Consul validation, or browser E2E. The default
`build_app` composition has no registry reader and correctly returns 503.
