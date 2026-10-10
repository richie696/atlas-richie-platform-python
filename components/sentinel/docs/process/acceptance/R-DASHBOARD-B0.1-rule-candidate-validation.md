# B0.1 Rule candidate validation API slice

## Implemented

- Added `POST /api/v1/rulesets/{bindingId}/validate` with the existing strict
  complete-candidate parser, authenticated `rules:write` and browser CSRF gates.
- The use case reads the current authoritative `RuleSetSnapshot`, rejects stale
  baseline identity before validation, then invokes the pure
  `RuleCandidateProfileValidator` and persists a server-generated receipt via
  `RuleValidationReceiptWriter`.
- `SqlAlchemyRuleValidationReceiptStore` provides durable receipt read/write.
  Receipt and `rules.validate` audit fact commit atomically; stored fields are
  limited to candidate identity/checksums, bounded issue codes/paths, actor,
  request ID and timestamp. Rule bodies and provider credentials are not stored.
- Added immutable validation receipt/issue DTOs. Publishable receipts must have
  no issues; issue categories and field paths are bounded and cannot carry raw
  exception text or arbitrary provider details.
- Missing/unavailable authority returns `503`; stale candidate returns `409`.
  This route does not pretend an unconfigured validator is successful.

## Verification

- `test_rule_candidate_validation_api.py`,
  `test_rule_candidate_diff_api.py`, and
  `test_rule_validation_receipt_store.py`: **21 passed**.
- `compileall` for Console source/tests: passed.
- Frontend `npm run contract:check`: **42 OpenAPI paths verified**.
- Isolated in-memory SQLite migration/store verification passed. No browser E2E
  or full Console suite was run; no real PostgreSQL/MySQL, production validator,
  Nacos/Consul connection or external service was accessed.

## Remaining boundary

`build_app` exposes the route only when snapshot reader, profile validator and
receipt writer are all supplied; otherwise it returns `503`. Production still
does not provide Nacos/Consul profile validators or final startup composition.
SQLite proves local migration/transaction behavior only, not production SQL
dialect behavior. Freeze must read and recheck the durable receipt; B0.1 remains
open until provider semantics, startup wiring and final milestone E2E pass.
