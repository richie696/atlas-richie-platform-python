# F6.1 rule-binding registration receipt: MySQL acceptance

Status: **the real-MySQL receipt read path passed**.

## Scope

This isolated acceptance verifies that the actual SQL registration store and
Console HTTP routes preserve the registration write's original session and
payload-fingerprint constraints while allowing a same-actor active admin to
read the durable result after cookie rotation. Receipt lookup is correlated by
actor, binding ID, and request key. A different actor or wrong correlation is
not-found; a currently demoted viewer is forbidden.

## Risk-to-test matrix

| Risk | Real-MySQL action | Required evidence |
|---|---|---|
| Receipt is not durable or fresh-session read is tied to old cookie | Register through the ASGI POST route, then GET receipt with a distinct active session for the same actor | POST 201; new-session GET 200 completed and exact binding ID |
| POST replay becomes broader than the original authorization/idempotency contract | Retry the original POST with rotated cookie, then retry changed payload with original cookie | Rotated-cookie POST is forbidden; changed fingerprint is idempotency conflict |
| Receipt can be read across actors or guessed with mismatched target/key | Query as a second active admin and query wrong binding/request key | Cross-actor and mismatched lookup return the same not-found receipt |
| Authorization is stale after role demotion | Change the persisted actor role to view, then query using its still-active session | API returns 403; no receipt body is exposed |

Test fixtures use synthetic IDs and a synthetic password-hash marker, never a
real password or token. The owner-labeled runner creates a random disposable
MySQL/Consul pair, publishes ports only on loopback, and removes only containers
carrying the current run's exact ownership label.

## Command

From `components/sentinel/sentinel-console`:

```sh
./tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql pytest -q tests/test_mysql_rule_binding_registration_receipt.py
```

The test is skipped unless the disposable runner supplies a validated
`mysql+asyncmy` URL targeting a `sentinel_console_test_*` database. No live
Nacos, Consul, PostgreSQL, production database, browser, or E2E suite is used.

## Result

- Focused SQLite store/API contracts plus the opt-in acceptance module without
  the disposable runner: **21 passed, 1 skipped**. The one skip is the expected
  real-MySQL gate when the validated disposable URL is absent.
- Owner-labeled disposable runner command above, MySQL **8.4.11** and Consul
  **1.21.1**: **1 passed** (run ID `082c92bbffaad3aa43c65343679832ae`). The HTTP path created through POST with the original
  session, rejected POST replay from a rotated session, rejected a changed
  payload fingerprint, then recovered the committed binding through GET using
  a separate active session for the same actor. Other actor and wrong binding /
  request key returned not-found; role demotion returned 403.
- The first runner attempt exposed a fixture-only schema mismatch: the generated
  `session_epoch` exceeded the column's 36-character contract. The fixture now
  uses UUID epochs; the corrected acceptance passed. No application schema or
  production data was changed.
- Exact containers from both runner attempts were checked by name after exit;
  all four MySQL/Consul containers were absent. The successful-run pair
  `sentinel-e2e-mysql-082c92bbffaad3aa43c65343679832ae` and
  `sentinel-e2e-consul-082c92bbffaad3aa43c65343679832ae` was explicitly
  rechecked and both were absent. `git diff --check` passed.
- `ruff check` could not run because Ruff is not installed in this project
  environment. Pytest imported and executed the new module successfully.

This closes only the real-MySQL receipt-read persistence/permission slice. It
does not close overall F6.1, the full Dashboard/browser E2E, PostgreSQL
acceptance, or production deployment behavior.
