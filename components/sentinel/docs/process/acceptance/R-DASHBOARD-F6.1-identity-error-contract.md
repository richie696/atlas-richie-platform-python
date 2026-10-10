# F6.1 Identity invalid-request wire contract

## Scope

Align the malformed `X-Request-ID` response for bootstrap, current-session read,
and logout with the frontend Console error registry. The wire code for HTTP 400
is `invalid_request`; `validation_failed` is reserved for HTTP 422.

## Changes

- `GET /api/v1/system/bootstrap`, `GET /api/v1/auth/me`, and
  `POST /api/v1/auth/logout` return `invalid_request` / 400 for malformed
  request IDs, before accessing their backing authority.
- The frontend identity endpoint schemas admit `invalid_request`; the transport
  preserves that typed code/status instead of downgrading it to a generic
  invalid response.
- The bootstrap error-path test exercises the real Console transport against a
  controlled HTTP response. Python route tests exercise all three endpoints.

## Evidence

- `sentinel-console`: `pytest -q tests/test_bootstrap_api.py
tests/test_session_api.py tests/test_logout_api.py` — **23 passed**.
- `dashboard-prototype`: `npm run test:http:focused -- 'IDENTITY-HTTP: bootstrap invalid_request'`
  — **1 passed**.
- `dashboard-prototype`: `npm run typecheck` — passed.
- `dashboard-prototype`: `npm run contract:check` — 42 OpenAPI paths verified.

## Boundary

This closes only one identity error-code mismatch. It does not complete F6.1's
page-by-page wire audit, nor prove a browser-to-Python E2E flow. Full E2E remains
deferred until implementation work is complete, as requested.
