# B0.1 — Registered configuration-source command HTTP slice

Status: **typed HTTP/application contract implemented; durable authority and provider writes remain open**.

## Contract and boundary

Implements the admin-only `POST /api/v1/system/sources/commands` and original
operation lookup `GET /api/v1/system/sources/operations/{requestKey}`. The
command requires one valid request ID, exact allowed Origin, double-submit
CSRF proof, an active administrator session, and an `Idempotency-Key` exactly
matching the body `requestKey`. The body is a strict register/update union;
updates require both source identity and expected revision. Operation lookup is
admin-only and owner context is passed to the authority.

The typed authority contract receives transient connection input and must own
durable idempotency, CAS, credential protection, source-registry persistence,
audit and provider writes. HTTP receipts contain only request/status/reason and
safe registered-source facts; submitted passwords, ACL tokens and credential
references are never serialized. A missing authority fails closed with 503.
The Console does not provide an in-memory production fallback.

## Focused verification

- Registered-source command contract: **7 passed** (the combined
  command/check, account-command and bootstrap authorize/connectivity suite was
  **33 passed** before the final conditional-update case was added).
- Console package `compileall`, frontend OpenAPI check (**42 paths**) and
  `git diff --check` passed.
- No full browser E2E was run (reserved for final milestone acceptance).
- No durable source mutation authority, secret vault, SQL migration, live
  Nacos/Consul write, production composition or end-to-end page-to-service
  acceptance is claimed. B0.1/B0.3 remain open.
