# atlas-richie-secret-openbao

OpenBao backend for the Atlas Richie secret platform. OpenBao is
a community fork of HashiCorp Vault with a 1:1 HTTP API surface
(KV v2 + Transit), so this wheel is a **thin wrapper** over
`atlas-richie-secret-vault`: it re-uses the hvac 2.x client, the
5-SPI composite, and the same retry / request-id machinery, but
advertises the session under `SecretBackend.OPENBAO` instead of
`SecretBackend.VAULT` so the framework can route or audit by
brand.

The wheel exists for three reasons:

1. **Brand attribution** — `SecretProviderDescriptor.backend` carries
   the actual deployment, so observability / policy tooling can
   distinguish OpenBao from Vault.
2. **Future OpenBao-specific features** — once OpenBao diverges
   (e.g. `bao audit log` headers, server-side rate-limit hints,
   `seal wrap` for hardware-backed root tokens), they can be
   added here without polluting `atlas-richie-secret-vault`.
3. **Per-deployment wiring** — separate wheel = separate
   `provider_id` prefix (`openbao-*` vs `vault-*`), which makes
   the secret registry's listing cleaner when both engines are
   used in the same cluster.

## Quick start

```python
from atlas_richie.secret_openbao import (
    OpenBaoSecretProperties,
    OpenBaoSecretProviderFactory,
)

properties = OpenBaoSecretProperties(
    url="https://openbao.example.internal:8200",
    token=os.environ["OPENBAO_TOKEN"],
)

factory = OpenBaoSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
assert session.descriptor.backend.value == "openbao"
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_VAULT_` (inherited from
`VaultSecretProperties`); same field set, same auth strategies
(Token / Kubernetes / AppRole).

## See also

- `atlas-richie-secret-vault` — the underlying engine
- `atlas-richie-secret-core` — framework + Protocols
- `docs/acceptance/R-234-secret-openbao-handoff.md` — design + verification
