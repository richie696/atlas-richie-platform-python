# atlas-richie-secret-vault

HashiCorp Vault backend for the Atlas Richie secret platform. Implements
the `SecretProviderFactory` + `SecretBackend` (read/write via KV v2) +
`KeyWrappingBackend` (Transit encrypt/decrypt) + `SigningBackend`
(Transit sign/verify) + `SecretBootstrapClient` (catalog resolution)
SPI roles over a single `hvac` client; mirrors Java
`atlas-richie-secret-provider-vault` 1:1.

## Quick start

```python
from atlas_richie.secret_vault import (
    AuthType,
    VaultSecretProperties,
    VaultSecretProviderFactory,
)

properties = VaultSecretProperties(
    url="https://vault.example.internal:8200",
    auth_type=AuthType.TOKEN,
    token=os.environ["VAULT_TOKEN"],
    kv_mount="secret",
    transit_mount="transit",
)

factory = VaultSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
# session.operations is a SecretOperations (KV v2 read/write)
# session.key_wrapping is a KeyWrappingBackend (Transit)
# session.signing is a SigningBackend (Transit)
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_VAULT_` (see `properties.py` for full list).

Required: `URL`, `TOKEN` (or K8s role / AppRole credentials).

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-redis` — sibling backend wheel
- `docs/acceptance/R-233-2-secret-vault-handoff.md` — design + verification
