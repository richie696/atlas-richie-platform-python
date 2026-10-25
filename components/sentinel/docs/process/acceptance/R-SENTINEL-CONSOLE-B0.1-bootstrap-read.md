# Python Console B0.1 — Bootstrap Read Slice

Status: **partial implementation; not signed or production-ready**.

## Scope and ownership

The independent Console lives in `components/sentinel/sentinel-console` as the
`atlas-richie-sentinel-console` package. It does not replace or extend
`atlas-richie-sentinel-dashboard`, which remains the per-process embedded
diagnostic UI/API. The Console composes its own ASGI application and consumes
only the minimum ports needed by the current operation.

The first operation is `GET /api/v1/system/bootstrap` from
`components/sentinel/docs/CONSOLE_API_CONTRACT.md` and the generated OpenAPI
contract. The HTTP adapter owns request-id validation, cookie extraction, wire
projection, and finite error mapping. `ReadBootstrap` owns the read sequence.
The durable initialized fact, deployment-owned setup-window marker, and
request-scoped bootstrap operator verification are three separate authorities
with explicit ports. `SqlAlchemyBootstrapInitializationReader` now adapts only
the relational initialized flag; it does not own the external setup window.
There is no implicit in-memory production provider and no default administrator.

## Invariants

- An initialized marker projects only `{"initialized": true}` and setup cannot
  be reopened by an operator cookie.
- An operator grant is reported only if the setup window is open and the
  request-specific opaque cookie is verified by its authority.
- A closed setup window cannot have a reported operator grant.
- Missing/invalid `x-request-id` is rejected without reflecting the supplied
  value. A valid request ID is echoed in the response header and error DTO.
- An unavailable bootstrap/session authority returns finite `503
  service_unavailable`; it is never represented as uninitialized, unauthorized,
  or a successful anonymous state.
- Authority results that violate the Python runtime port contract fail closed;
  an invalid boolean is not treated as truthy authorization.
- Unexpected application exceptions are not swallowed by the route; they stay
  visible to the ASGI server's error reporting.
- The SQLite integration proves the SQLAlchemy adapter and application/API
  boundary locally, not production database semantics. Deployment-backed
  setup-window persistence, operator cookies/authorization-code exchange,
  CSRF/Origin validation, production startup composition, and setup commands
  remain unimplemented.

## Risk-to-test matrix

| Risk | Test | Evidence |
| --- | --- | --- |
| Completed setup accidentally reopens | Initialized state + granting verifier | Minimal initialized DTO; verifier is not called |
| Request-specific grant is omitted or inferred globally | Open setup + opaque cookie | Grant returned only after verifier receives that cookie |
| Closed gate reports stale grant | Closed setup + granting verifier | Grant remains false; verifier is not called |
| Request ID injection/reflection | Invalid ID | 400 finite error; invalid text absent; state port untouched |
| Initialization authority outage looks like first-run | SQLAlchemy adapter raises typed authority failure | 503 stable code; sensitive message absent |
| Missing guard row permits first admin | SQLite adapter/API integration removes guard row | 503; setup-window and operator authorities are not queried |
| Database connection failure looks like first-run | SQLite ASGI integration points at a synthetic missing parent directory | 503 stable code; database path/message absent |
| Setup-window fact is confused with database state | Separate initialization and setup-window ports | Initialized result skips setup-window/operator reads; uninitialized result queries them in order |
| Session authority outage looks like denial | Verifier raises typed authority failure | 503 stable code; sensitive message absent |
| Broken adapter truthiness grants access | Verifier returns non-bool | 503 fail-closed response |

Most tests use `httpx.ASGITransport` against the Starlette route composition,
with explicit test-only port doubles. Additional integration tests use the
real SQLAlchemy adapter and Alembic migration over disposable in-memory SQLite.
They verify the local ASGI/database boundary but do not prove socket
deployment, PostgreSQL/MySQL semantics, cryptographic session validation,
browser-to-Python E2E, or production authorization.

## Implementation result

Current focused evidence: Python 3.12.14 virtual environment, Starlette 0.52.1,
HTTPX 0.28.1, **13/13 bootstrap API + persistence integration tests passed**;
the complete Console suite passed **22/22** and source compilation passed.
The existing embedded `sentinel-dashboard` regression suite was not changed in
this slice. A local wheel build produced one sdist and one wheel; archive
inspection confirmed the package contains the SQLAlchemy initialization
adapter, route, migration runner, and Alembic revision. The wheel was installed
into a disposable target and the complete Console suite passed **22/22** using
the installed package.

This is a B0.1 vertical slice with one SQLite-backed read adapter only. B0.1
remains open until setup-window/operator authorities, production startup,
authorization boundary, remaining Console operations, error contract, and
permissions are implemented and verified. B0.2–B0.6 remain open.

## Follow-up coverage — system observation and audit reads

The Python application now also composes authenticated
`/api/v1/system/connections`, `/api/v1/system/protocols`, and admin-only
`/api/v1/system/audit` routes. Audit has a SQLAlchemy reader and a focused
disposable-SQLite test suite; persisted account/password actions and outcomes
map to the finite UI vocabulary. Unknown or structurally incomplete facts fail
closed as `service_unavailable`. The current local Python environments lack
SQLAlchemy, so the new SQLite tests could not be collected in this run. These
routes remain host-injected: production startup does not yet provide the
corresponding facts/readers, so absent authorities return 503. Focused
ASGI/SQLite tests are slice evidence only, not browser E2E or production
database acceptance.
