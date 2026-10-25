# Rules scope catalog — focused acceptance design

Status: implementation slice; the 0.5.0 Console v1 wire contract remains immutable.

## Ownership and behavior

The Rules page needs environment/application selector facts even before any
Metrics V2 Reporter has published a sample. Its authority is the persisted,
credential-free rule-binding directory (metadata joined to its registered
source and exact publication target), not the observation/metrics catalog.
The new bounded, authenticated read is an additive versioned scope contract.
An empty valid binding directory returns empty selector collections; missing
authority or inconsistent binding/source/target facts fail closed as
`503 service_unavailable`. The endpoint never returns rule bodies, target
credentials, or raw connection data. Existing Console API 0.5.0 endpoints and
the Metrics V2 observation catalog keep their current semantics.

The feature owns its React scope DTO, port, gateway, resource and mock handler.
The backend's rule-binding reader owns the SQL projection; the API adapter owns
session authorization, response mapping and safe errors. The current SQL
adapter is the default implementation; no new database-specific branch or
cross-feature import is introduced.

## Focused risk-to-test matrix

| ID | Layer | Preconditions / action | Assertions |
| --- | --- | --- | --- |
| RULE-SCOPE-DOMAIN-1 | Domain | Construct sorted and empty scope snapshots | Bounds, unique environment and `(environment, application)` identities, and parent environment references are enforced |
| RULE-SCOPE-SQL-1 | Database integration | Read zero or multiple registered bindings across environments | Empty result is valid; scopes are deduplicated, sorted, and projected only from complete exact binding/source/target joins |
| RULE-SCOPE-SQL-2 | Database integration | Seed orphan or mismatched source/target metadata and exceed configured bound | Authority returns a safe unavailable failure; it never exposes a partial/guessed catalog |
| RULE-SCOPE-HTTP-1 | HTTP/auth | Admin and view request scopes with valid request IDs | Exact response fields, `no-store`, `Vary: Cookie`, no credential-bearing fields |
| RULE-SCOPE-HTTP-2 | HTTP/auth | Anonymous request or absent reader | 401 without authority access; absent authority returns 503 |
| RULE-SCOPE-HTTP-3 | HTTP/failure | SQL authority failure or invalid scope snapshot | 503 `service_unavailable`; no raw exception or partial data |
| RULE-SCOPE-REACT-1 | HTTP/UI | Metrics observation catalog fails while rule scope read succeeds | Rules page remains mounted, scope selector/binding read can proceed; no Metrics failure banner is shown |
| RULE-SCOPE-REACT-2 | Mock/contract | Mock mode with registered bindings; backend SQL authority with empty bindings | Scope endpoint returns the same HTTP shape used by live mode; unknown paths remain fail-closed |

## Verification boundary

Run the backend domain/SQL/HTTP tests, React scope gateway and mounted Rules
tests, contract generation/parity, typecheck/lint/format checks, and one visible
Codex In-App Browser Rules-page read against the controlled local Console.
This focused slice is not the full T07.1 E2E journey and does not prove any
active metric has been reported.

## Verification record — 2026-10-15

- Backend domain, SQL-authority, authenticated HTTP, and OpenAPI-route parity tests: **44 passed**. Empty authority returns an empty catalog; broken source/target authority, missing reader, anonymous session, or invalid snapshot fails closed without exposing private detail.
- React scope gateway focused tests: **3 passed**; mock binding projection test: **1 passed**. TypeScript, focused ESLint, i18n key check, contract generation/check, relevant-file Prettier, and live-only production build passed. The OpenAPI contract is additive **0.6.0**, with **47 paths / 48 operations**; 0.5.0 observation catalog behavior is unchanged.
- Codex In-App Browser showed the live-only Rules workspace and first-scope entry while the already-running Console process (still on its pre-0.6.0 code) returned a safe unavailable response for the new route. In Mock mode the registered environment selector loaded, then explicit `test-env` scope showed the application filter and five rule bindings without an observation-catalog failure. SQL tests cover the authoritative empty-catalog case. No Chrome/Edge or full E2E suite was run.
- The repository-wide `npm run format:check` still reports five pre-existing formatting warnings in system source-registration/incident files outside this slice; all files changed for this scope passed focused Prettier checks. Ruff reported legacy `TRY004` findings in pre-existing validation methods, so the focused Ruff check excluded that legacy rule and passed all other enabled checks; Ruff formatting passed for the touched Python files.
- This closes only the Metrics-independent Rules scope implementation slice. Restart/redeployment of the already-running Console and verification against its authoritative SQL bindings, plus the final full T07.1 browser journey, remain open.

## Follow-up verification — 2026-10-15

- A real MySQL 8.4.11 integration test now creates a binding through the authenticated Console ASGI API and reads back its persisted environment/application scope through `GET /api/v2/rules/binding-scopes`: **1 passed**. The repository's disposable MySQL/Consul wrapper removed only the containers it created; exact-name `docker container ls -a` checks returned no leftovers.
- React focused regression: rule binding query logic **6 passed**, independent rule-scope HTTP **3 passed**, and mounted rule workbench/system tabs/unavailable-metrics UI **5 passed**. These checks distinguish an authoritative empty rule directory from an unavailable scope authority, and keep the System tab/page mounted when individual system observations fail.
- Codex In-App Browser against the running live-only preview confirmed that a rule-scope read failure does not replace the Rules workbench: the page offers manual environment entry, accepting an environment continues to the independent binding query, and an empty binding result is not labeled as an observation/metrics failure. System Management remains visible and reports its own Console facts; Realtime Monitoring keeps all six cards and six empty charts with unavailable values. The currently running Console is still the pre-0.6.0 process, so this browser check exercises its safe unsupported-route fallback, not the new live MySQL-backed scope route. No Chrome/Edge or full E2E suite was run.
