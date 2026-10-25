# B0.1 MySQL rule-binding registration receipt authority

Date: 2026-10-13
Status: targeted real-MySQL/ASGI acceptance passed; B0.1 remains open.

## Scope

Verify the production SQL registration store and authenticated Console routes
against disposable MySQL. A completed registration receipt must remain
readable by its creating administrator after session rotation, while the
original POST remains bound to its creating session and request fingerprint.
Receipt reads must not disclose the operation to another actor or after the
creator loses admin permission.

## Risk-to-test matrix

| Risk | Evidence |
| --- | --- |
| SQL registration does not persist a completed receipt and binding | Authenticated ASGI POST returns `201`; receipt GET returns `completed` and the exact binding identity. |
| Session rotation either blocks legitimate recovery or permits old write replay | A replacement session for the same actor can read the receipt; replaying the POST with that rotated session is denied; changed payload with the original key conflicts. |
| Receipt identifiers leak another operation | Wrong binding/key and another actor receive `not_found` without a binding. |
| Permission is trusted from the stale session | After SQL role demotion to `view`, the same session receives `403`. |

## Verification

```text
tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql pytest -q --tb=short tests/test_mysql_rule_binding_registration_receipt.py
1 passed in 1.52s
uv run --extra test pytest -q --tb=short tests/test_rule_bindings_api.py tests/test_rule_binding_registration_store.py tests/test_rule_binding_registration_openapi_contract.py
23 passed in 3.69s
SENTINEL_CONSOLE_RUN_RULE_BINDING_RECEIPT_ACCEPTANCE=1 tools/with_disposable_e2e_dependencies.sh uv run --extra test --extra mysql pytest -q --tb=short tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_recovers_rule_binding_receipt_after_session_rotation
1 passed in 22.06s
SENTINEL_CONSOLE_RUN_RULE_BINDING_RECEIPT_ACCEPTANCE=1 tools/with_disposable_postgresql_acceptance.sh uv run --extra test --extra postgres pytest -q --tb=short tests/test_installed_cli_bootstrap_acceptance.py::InstalledCliBootstrapAcceptanceTests::test_installed_cli_postgresql_recovers_rule_binding_receipt_after_session_rotation
1 passed in 19.47s
```

The acceptance uses synthetic accounts/source data and deletes its uniquely
identified SQL rows in teardown. The disposable MySQL 8.4.11 and Consul 1.21.1
runner containers were confirmed absent after all runs. The installed-wheel
cases start from an empty runtime locator, install the current Console wheel,
uses the standard two-worker `sentinel-console serve` entry point, initializes
through HTTP, registers a Consul binding through the SQL composition, logs in
again as the same administrator, recovers the receipt, and verifies that the
rotated session cannot replay the original write. This has passed on MySQL
8.4.11 and PostgreSQL 16 disposable instances.

## Boundary

This proves SQL persistence, production composition and ASGI receipt authorization
on MySQL and PostgreSQL, including the installed wheel and standard CLI process. It
does not test the React mounted registration flow, provider write, or full
React→Python E2E, and does not close B0.1 or B0.5.
