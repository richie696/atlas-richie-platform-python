# B0.1 Rule candidate diff

## Scope and boundary

Implement only `POST /api/v1/rulesets/{bindingId}/diff`. This is a non-persistent,
administrator-only comparison of a complete candidate against the exact current
authoritative snapshot. It does not validate provider serialization, authorize
publication, save a draft, or claim the candidate is publishable.

The request's `recordId: null` means a new record. A non-null identity must exist
in the exact baseline. A stale version/checksum/source revision is a conflict;
an unknown record identity is rejected rather than silently treated as an add.
All five existing Sentinel rule value objects remain the sole semantic validator.

`candidateChecksum` is a server-generated opaque `sha256:` identifier over the
strict, typed candidate rules in request order, encoded as compact UTF-8 JSON with
sorted object keys and non-finite numbers forbidden. The client only stores and
returns this opaque value; it does not independently compute it. This checksum
does not assert compatibility with a Nacos or Consul wire codec.

## Risk-to-test matrix

| Risk | Evidence |
| --- | --- |
| Candidate could be compared against a different binding or stale baseline | API tests for path/body mismatch and version/checksum/source-revision conflicts; stale baselines return 409 before a diff is emitted |
| Rule payloads could bypass the typed validation already used by snapshot reads | Positive cases for all five rule kinds and negative cases for unknown fields, wrong rule kind, non-finite values, invalid enum/range and malformed record identity |
| Diff could report incorrect add/remove/replace semantics | Unit/API cases for unchanged, add, remove, replace and mixed changes; stable input order and exact before/after values |
| Read-only POST could be used without administrator browser proof | Anonymous, view-role, invalid Origin, missing CSRF header, and invalid request-id cases; assert authority is not called where applicable |
| Infrastructure failures could be confused with empty diff | Missing authority, not-found, rate-limited and unavailable mapping; no successful empty result on failure |
| Candidate material might be persisted or leak infrastructure detail | Spy authority and response assertions: one read only, no mutation port, bounded error envelope, `no-store` and `Vary: Cookie` |

## Verification record

The focused Python test command and OpenAPI contract check are recorded here after
implementation. No browser E2E is required for this API-only slice; complete
browser journeys remain milestone-only.

- **Implementation:** Added a typed immutable candidate model, strict parsing for
  all five Sentinel rule kinds, exact snapshot/baseline comparison, and the
  authenticated `POST /api/v1/rulesets/{bindingId}/diff` route. The operation
  reads exactly one snapshot and never calls a write port. It returns stable
  add/remove/replace facts and an opaque server SHA-256 candidate identifier.
- **Verification:** Focused Console tests passed (**29 passed**) across this
  route, neighboring snapshot/account/password routes; Python `compileall`,
  88-column audit, `git diff --check`, and `npm run contract:check` (42 paths)
  passed. Checks include path/body and stale-base conflicts, authorization and
  Origin/CSRF, five typed kinds, mixed changes, strict fields, and checksum
  order semantics. No full Console suite or browser E2E was run.
- **Boundary:** The digest is not a provider codec validation receipt and cannot
  authorize publication. Durable validation, Nacos/Consul serialization/CAS,
  production source readers, live UI, and milestone E2E remain open; B0.1 stays
  unchecked.
