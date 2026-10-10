# B0.2 — Bootstrap configuration-source connectivity-check HTTP slice

Status: **typed HTTP/security boundary implemented; provider connectors and production wiring remain open**.

## Contract and boundary

Implements `POST /api/v1/system/bootstrap/source-check`. The route validates
request ID, exact Origin, double-submit CSRF, the current bootstrap-operator
grant, and the strict Nacos/Consul request union before calling the
consumer-owned `BootstrapSourceChecker` port. Nacos `namespace` and Consul
`datacenter` remain separate wire fields. No-auth, credential-reference and
direct-secret modes are accepted; direct credentials and references are
excluded from dataclass repr/equality. The response contains only
`reachable` or a finite `unreachable` reason, with `Cache-Control: no-store`.

The route does not register a source, read or publish rules, persist candidate
values, or return submitted credentials. An absent checker and a typed checker
outage fail closed with stable 503 responses. The shared bootstrap browser
proof implementation now serves both database and source connectivity checks.

The endpoint parser only provides strict syntax and URL-component validation.
It is **not** an SSRF defense and does not make network requests. A concrete
provider checker must enforce deployment-owned endpoint allowlists, DNS pinning,
TLS identity, redirect prohibition and bounded timeouts before production
wiring. This slice intentionally adds no unrestricted HTTP client or hidden
default target policy.

## Focused verification

- `PYTHONPATH=src .venv/bin/pytest -q tests/test_bootstrap_source_check_api.py tests/test_bootstrap_database_check_api.py`: **11 passed**.
- Python `compileall` passed for the Console package.
- No real Nacos/Consul, production credentials, browser E2E or Console-wide
  suite was used. Provider adapter and production startup acceptance remain
  open; B0.1/B0.2/B0.3 are not closed by this slice.
