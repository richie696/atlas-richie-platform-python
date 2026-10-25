# B0.1 — Registered configuration-source command HTTP slice

Status: **typed HTTP/application contract and durable SQL authority implemented; registered-source reads/checks are composed and verified with disposable MySQL/PostgreSQL and Consul; production deployment policy and final React→Python browser acceptance remain open**.

## Contract and boundary

Implements the admin-only `POST /api/v1/system/sources/commands` and original
operation lookup `GET /api/v1/system/sources/operations/{requestKey}`. The
command requires one valid request ID, exact allowed Origin, double-submit
CSRF proof, an active administrator session, and an `Idempotency-Key` exactly
matching the body `requestKey`. The body is a strict register/update union;
updates require both source identity and expected revision. Operation lookup is
admin-only and owner context is passed to the authority.

The typed authority contract receives transient connection input and owns
durable idempotency, CAS, credential protection, source-registry persistence,
and audit. HTTP receipts contain only request/status/reason and safe
registered-source facts; submitted passwords, ACL tokens and credential
references are never serialized. A missing authority fails closed with 503.
The standard SQL/first-run composition supplies the durable registered-source
store; the Console does not provide an in-memory production fallback. Provider
health checks are a separate read-only path, not rule publication writes.

## Focused verification

- Registered-source command contract: **7 passed** (the combined
  command/check, account-command and bootstrap authorize/connectivity suite was
  **33 passed** before the final conditional-update case was added).
- At the time of this initial slice, Console package `compileall`, frontend
  OpenAPI check (**42 paths**) and
  `git diff --check` passed.
- No full browser E2E was run (reserved for final milestone acceptance).
- This original HTTP-contract run did not prove durable source mutation,
  registered-source provider checks, installed-CLI composition, or end-to-end
  page-to-service acceptance. Later implementation/acceptance is recorded in
  the current checklist (§15.1007–§15.1008 and §15.1037–§15.1039): the SQL
  authority is exercised with disposable MySQL/PostgreSQL and registered
  Consul checks, including installed-wheel CLI paths. This does not establish
  production key/Secret delivery or rotation, user ingress/topology, or final
  browser acceptance. B0.1/B0.5 remain open.

## Status reconciliation — later implementation evidence (2026-10-13)

The earlier “durable authority remains open” statement described the initial
HTTP adapter slice and is superseded. `SqlAlchemyRegisteredSourceStore` now
provides register/update persistence, revision CAS, encrypted credentials,
idempotency receipts, and audit. SQL composition reads the safe source
directory and resolves registered credentials for bounded source checks. The
current checklist records disposable MySQL/PostgreSQL and installed-wheel
evidence in §15.1007–§15.1008 and §15.1037–§15.1039. These are scoped local
acceptance results, not production key delivery/rotation, ingress/provider
topology, or final React→Python browser acceptance.
