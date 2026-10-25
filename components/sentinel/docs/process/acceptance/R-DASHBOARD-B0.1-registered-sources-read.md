# B0.1 — Registered source registry read API

## Scope

Implement the Python `GET /api/v1/system/sources` consumer contract. This route
reads only the authoritative server-owned registry snapshot and projects safe
metadata. This read operation does not register sources, probe Nacos/Consul,
resolve their credentials, or write configuration. The API has no demo/default
reader: a generic `build_app()` without an injected `RegisteredSourcesReader`
returns 503, while SQL identity composition with registered-source keys
composes `SqlAlchemyRegisteredSourceStore` as the durable reader.

## Ownership and design

- `RegisteredSourcesReader` is the Console application port for the
  source-registry read capability; `SqlAlchemyRegisteredSourceStore` owns the
  current SQL persistence mapping and returns safe registry facts without
  decrypting or probing credentials.
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
- Installed-wheel / standard CLI acceptance through
  `tools/with_disposable_e2e_dependencies.sh uv run --no-sync --extra test
  --extra mysql pytest -q --tb=short
  tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_migrates_and_serves_safe_first_run_state`
  — **1 passed in 19.06s** on disposable MySQL 8.4.11 + Consul 1.21.1. After
  first-run initialization, the real authenticated CLI request reads the
  persisted Consul source from `/api/v1/system/sources`, verifies safe source
  metadata/no token leakage, and completes the configured source probe.

The unit/API slice and installed CLI path are distinct evidence: the latter
proves this configured MySQL/Consul route is live in the standard CLI. It does
not prove PostgreSQL parity for this exact CLI path, React-to-Python browser
integration, production secret delivery, or browser E2E. A generic `build_app`
without a composed reader still correctly returns 503.
