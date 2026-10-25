# B0.2 — Bootstrap source credential key-rotation restart slice

Status: **one isolated SQLite acceptance slice passed; B0.2 remains open**.

## Risk and boundary

Bootstrap stores the initial configuration-source credential encrypted under
the deployment's active AES-GCM key. A later runtime must be able to decrypt
that credential after an active-key rotation, provided the previous key remains
in the configured retained key ring. Credential resolution must remain scoped
to the exact source ID, source revision, and provider; removing the previous
key must fail closed instead of returning corrupted or partial credentials.

This slice runs the production bootstrap transaction and registered-source SQL
adapter against an isolated in-memory SQLite database. It reconstructs the
cipher and adapter objects with a new active key plus the retained previous key
to model a service restart. It does **not** spawn a second OS process, verify
deployment environment delivery/rotation procedures, or prove PostgreSQL/MySQL
behavior.

## Evidence

Test: `tests/test_bootstrap_secret_rotation_acceptance.py`.

The test initializes the database and first administrator/source using key
`source-v1`, then creates a new runtime adapter configured with active key
`source-v2` and retained key `source-v1`. It verifies that the original source
credential resolves exactly for its ID/revision/provider and that another
source ID, revision, or provider cannot retrieve it. It also verifies that the
credential-bearing database row representation and initialization receipt do
not contain the synthetic source/admin passwords, and that deleting the
previous key prevents credential resolution.

Verification on Python 3.13.15:

```text
uv run --extra test --extra sqlite-local pytest -q tests/test_bootstrap_secret_rotation_acceptance.py
1 passed

uv run --extra test --extra sqlite-local pytest -q tests/test_bootstrap_initialization_transaction.py tests/test_registered_source_store_api_integration.py tests/test_bootstrap_secret_rotation_acceptance.py
8 passed

uv run --extra test --extra sqlite-local python -m compileall -q src tests/test_bootstrap_secret_rotation_acceptance.py
passed

git diff --check -- tests/test_bootstrap_secret_rotation_acceptance.py
passed
```

No real database, configuration center, or user credential was accessed. No
container was created.

## Remaining B0.2 boundary

This targeted key-retention proof does not close B0.2. Full production-dialect
bootstrap/lifecycle acceptance, deployment secret delivery and rotation,
multi-worker/shared-mount behavior, and the final React-to-Python browser flow
remain separate acceptance requirements. The full E2E gate remains deferred
until implementation closeout.
