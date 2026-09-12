# atlas-richie-secret-azure-keyvault

Azure Key Vault backend for the Atlas Richie secret platform.
Implements the **4-SPI subset** that Java
`atlas-richie-secret-provider-azure` exposes:

| SPI | Implemented? | Reason |
|---|---|---|
| `SecretOperations` | yes | Azure Secrets API read |
| `KeyWrappingBackend` | yes | Azure Keys API wrap / unwrap |
| `SigningBackend` | **no** | Java side does not expose it; the framework's `signing` property on the session returns `None` |
| `SecretBootstrapClient` | yes | Startup-time batch read |
| `SecretProviderSession` | yes | Provider lifecycle |
| `SecretListable` | **no** | Java side's capability declaration does not include LIST |

This narrower scope (vs the AWS wheel) mirrors Java
`atlas-richie-secret-provider-azure` exactly — it is essentially a
`SecretProviderType("azure")` registration + capability declaration
that delegates to `AbstractRemoteProviderFactory`. The Python side
collapses the same surface into 4 source files.

## SDKs

- `azure-identity` — `DefaultAzureCredential` (env / managed
  identity / Azure CLI / etc.)
- `azure-keyvault-secrets` — `SecretClient` for read
- `azure-keyvault-keys` — `KeyClient` for wrap / unwrap

## Environment

Prefix `ATLAS_RICHIE_SECRET_AZURE_`. Required: `VAULT_URL`
(`https://<name>.vault.azure.net/`). The credential chain is
delegated to `DefaultAzureCredential`.

## Local development

There is no official Azure Key Vault emulator. Tests are
written against the SDK's `SecretClient` / `KeyClient` interfaces
with `unittest.mock.MagicMock` so they can run in CI without
Azure credentials. Real-cloud integration tests are gated by
the `ATLAS_RICHIE_SECRET_AZURE_TEST_VAULT_URL` env var; if it is
not set, the integration markers `pytest.skip` gracefully.

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-vault` — sibling remote backend wheel
- `atlas-richie-secret-aws-kms` — sibling cloud backend
- `docs/acceptance/R-236-secret-azure-keyvault-handoff.md`
