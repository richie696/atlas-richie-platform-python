# atlas-richie-secret-barbican

OpenStack Barbican secret backend for the Atlas Richie
secret platform. Implements a **3-SPI composite**
(`SecretOperations` via Barbican REST + `SecretBootstrapClient`
+ `SecretProviderSession`); 1:1 functional parity with Java
`atlas-richie-secret-provider-barbican`.

## Scope

Barbican is a **secret store** (OpenStack Key Manager v1
API), not a KMS:

- ✅ `SecretOperations` — `GET /v1/secrets/{id}` for metadata,
  `GET /v1/secrets/{id}/payload` for raw bytes
- ✅ `SecretBootstrapClient` — load logical paths
- ✅ `SecretProviderSession`
- ❌ `KeyWrappingBackend` — Barbican has no KMS wrap API
- ❌ `SecretWriter` / `SecretDeletable` — read-only backend

The session's `writer` / `deletable` properties both
return `None`, matching the R-238 PKCS#11 HSM pattern.

## HTTP

`BarbicanSecretClient` uses `httpx.Client` (vs Java's
JDK `HttpClient`). Two-step read:

1. `GET /v1/secrets/{id}` — JSON metadata (also 404s to
   `None` for missing secrets)
2. `GET /v1/secrets/{id}/payload` — raw bytes
   (`Accept: application/octet-stream`)

Auth headers: `X-Auth-Token` (Keystone token) and
optional `X-Project-Id`. Error mapping mirrors Java
`providerFailure`:

| HTTP status | Framework code |
|-------------|----------------|
| 401         | `SEC-AUTH-001`  |
| 403         | `SEC-AUTHZ-001` |
| 404         | `SEC-STORE-001` |
| other       | `SEC-PROVIDER-001` |

## Install

```bash
pip install atlas-richie-secret-barbican
```

## Quick start

```python
from atlas_richie.secret_barbican import (
    AuthType,
    BarbicanSecretMapping,
    BarbicanSecretProperties,
    BarbicanSecretProviderFactory,
)

properties = BarbicanSecretProperties(
    endpoint="https://keystone.example:5000",
    project_id="project-1",
    auth_type=AuthType.TOKEN,
    auth_token="keystone-token-abc",
    secrets={
        "db-password": BarbicanSecretMapping(id="sec-123-uuid"),
    },
)
factory = BarbicanSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_BARBICAN_`; fields cover
endpoint / project_id / auth_type / auth_token /
auth_token_file / secrets / timeouts.

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-vault` — sibling HashiCorp Vault
  backend (similar 3-SPI scope)
- `docs/acceptance/R-242-secret-barbican-handoff.md` —
  design + verification
