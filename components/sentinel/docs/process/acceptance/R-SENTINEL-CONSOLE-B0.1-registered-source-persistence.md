# B0.1 — Registered configuration-source persistence

Status: **SQLite-tested persistence, exact-revision credential resolution, and deployment key-ring composition implemented; production service composition and provider connectivity remain open**.

## Ownership and persistence contract

`SqlAlchemyRegisteredSourceStore` implements the existing registry read and
mutation ports. It owns a single relational transaction covering administrator
and session/CSRF revalidation, source register or compare-and-set update,
idempotency receipt, and audit fact. Update requires the exact stored revision;
stale revisions persist a finite conflict receipt without changing the source.
Operation receipts are visible only to the original actor and session.

The registry stores safe source facts separately from credentials. Direct Nacos
username/password, Consul ACL tokens, and credential references are serialized
only transiently and encrypted with the existing AES-256-GCM cipher, using
source identity and field as authenticated associated data. `keep` preserves
the existing ciphertext only for the same provider and a matching source
revision. HMAC fingerprints allow safe idempotent replay without storing the
source command or its credentials; the active and retained key ring supports
fingerprint-key rotation. Audit and operation receipt rows contain no raw
request body or secret.

Migration `0006_registered_sources` adds registry and operation tables with
finite-state and encrypted-envelope consistency constraints. For a `keep`
source check, the application use case asks the store for credentials using the
exact `source_id + revision + provider`, decrypts them with source-bound AAD,
and merges only the submitted endpoint/location into the ephemeral probe input.
A stale/missing revision fails closed with a generic service-unavailable
response. Secrets remain repr/equality-hidden and are not returned in HTTP
output. The store does not call Nacos/Consul or resolve external credential
references. No default/in-memory production authority is introduced.

Deployment-owned encryption and fingerprint key rings are parsed by
`RegisteredSourceKeyConfiguration`; active and retained keys are validated and
kept out of `repr`. `compose_registered_source_store` wires the configured
cipher and HMAC key ring into the SQL adapter. It accepts an already
constructed `AsyncEngine`; it does not open a database connection, run
migrations, read keys from a KMS, or build the full Console application.

## Risk-to-evidence matrix

| Risk | Evidence |
| --- | --- |
| Migration/model mismatch | SQLite in-memory upgrade through Alembic head and store integration suite |
| Secret at rest or context substitution | Inspect encrypted DB envelope, decrypt only with source-bound AAD, reject wrong owner context |
| Duplicate side effect or key reuse | Same request replay returns original result; changed input conflicts; source/receipt/audit counts remain one |
| Lost update | Exact-revision update changes revision; stale revision returns conflict and leaves current source unchanged |
| Privilege/session race | Transaction rechecks active session, admin role, expiry and CSRF digest; denied operations leave no source row |
| Cross-session receipt disclosure | A different valid administrator session cannot read another session's operation receipt |

## Focused verification

- Registered-source persistence, its composed ASGI→SQLite→decrypt→checker path,
  command API and source-check API: **21 passed** across four focused test modules.
- Key-ring parser and store composition: **3 passed**, including active/retained
  rotation keys, malformed/missing configuration rejection, repr suppression,
  and AES-GCM round-trip using the active key.
- Console package `compileall` and `git diff --check` passed.
- No full browser E2E, external database, KMS, Nacos/Consul endpoint, or production
  startup was used. PostgreSQL/MySQL concurrency, production key injection and
  rotation rehearsal, external credential-reference resolution, provider probe/write, and real
  React → Python → DB/config-center acceptance remain open.
