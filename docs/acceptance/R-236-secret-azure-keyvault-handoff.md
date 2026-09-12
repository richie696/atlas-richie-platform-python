# R-236 Handoff: `atlas-richie-secret-azure-keyvault` — Azure Key Vault backend

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 31/31 azure tests pass (7 properties unit + 6
configuration unit + 18 client integration), all **212/212 secret
tests pass** across all 6 secret wheels (62 core + 20 redis + 56
vault + 6 openbao + 37 aws + 31 azure),
`atlas-richie-secret-azure-keyvault` 0.2.0 wheel built, **15/15
isolated wheels install + import OK** in fresh venv.

## Motivation

R-233 / R-235 shipped the framework + Redis / Vault / OpenBao /
AWS backends. **R-236** adds the **fifth remote backend**: **Azure
Key Vault**, mirroring Java
`atlas-richie-secret-provider-azure` 1:1.

Unlike AWS (SecretsManager + KMS = two services), Azure combines
secrets and crypto in **one** vault, but the surface is narrower
than AWS:

| SPI | AWS (R-235) | Azure (R-236) |
|---|---|---|
| `SecretOperations` | yes | yes |
| `KeyWrappingBackend` | yes (KMS) | yes (Keys API) |
| `SigningBackend` | yes (KMS) | **no** (Java side does not declare) |
| `SecretBootstrapClient` | yes | yes |
| `SecretProviderSession` | yes | yes |
| `SecretListable` | no (Java omits) | **no** (Java omits) |

The narrower scope mirrors Java's
`AzureSecretBootstrapProviderFactory.providerCapabilities() = Set.of(
SECRET_READ, SECRET_VERSIONING, KEY_WRAP, KEY_UNWRAP)`.

## Java → Python structural mapping

Java has `cn.richie696.component.secret.provider.azure.*` as a thin
stub — the actual capability declaration lives in
`AbstractRemoteProviderFactory`. Python is one wheel
(`atlas-richie-secret-azure-keyvault`) with **4 source files** that
implement the 4-SPI surface against the Azure SDK:

```
components/secret/secret-azure-keyvault/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_azure_keyvault/
    ├── __init__.py            ← public surface (6 symbols)
    ├── client.py              ← AzureSecretClient (4-SPI composite)
    ├── configuration.py       ← AzureConfigurationResolver + path safety + SHA-256
    ├── factory.py             ← AzureSecretProviderFactory + AzureClientFactory
    └── properties.py          ← AzureSecretProperties + AzureKeyWrapAlgorithm
└── tests/
    ├── conftest.py                ← mock Azure SDK clients + real-Azure skip fixture
    ├── test_azure_properties.py   ← 7 unit tests (env injection)
    ├── test_azure_configuration.py ← 6 unit tests (path safety + hash)
    └── test_azure_client.py       ← 18 integration tests via MagicMock
```

## Functional surface (6 public symbols)

- `AzureSecretProperties` — pydantic-settings env-injected
  configuration; prefix `ATLAS_RICHIE_SECRET_AZURE_`. Carries
  `vault_url` / `key_bindings` / `default_key_wrap_algorithm`.
- `AzureKeyWrapAlgorithm` — `StrEnum { RSA_OAEP, RSA_OAEP_256, RSA1_5 }`.
- `ResolvedAzureConfiguration` + `AzureConfigurationResolver` —
  URL safety validation, static `SecretCapability` declaration
  (`can_list=False`), SHA-256 `configuration_hash`.
- `AzureClientFactory` — build `(SecretClient, KeyClient)` from
  `AzureSecretProperties` using `DefaultAzureCredential`.
- `AzureSecretProviderFactory` — `SecretProviderFactory` implementation
  (`name = f"azure-{vault_url_hash8}"`, `backend = SecretBackend.AZURE`).
- `AzureSecretClient` — composite implementation of 4 SPI roles:
  - `SecretOperations` — Secrets API get / get_version /
    get_metadata / exists
  - `KeyWrappingBackend` (duck-typed) — Keys API wrap_key / unwrap_key
  - `SecretBootstrapClient` (`bootstrap` resolves a
    `SecretBindingCatalog`)
  - `SecretProviderSession` (descriptor / configuration /
    operations / writer=None / deletable=None / signing=None /
    snapshot_manager / is_closed / close)
  The session's `writer` / `deletable` / `signing` properties all
  return `None`, mirroring Java's narrower 4-SPI surface.

## SDKs

- `azure-identity` — `DefaultAzureCredential` (env / managed
  identity / Azure CLI / VS Code auth)
- `azure-keyvault-secrets` — `SecretClient` for read
- `azure-keyvault-keys` — `KeyClient` for wrap / unwrap (local
  cryptographic ops, no remote round-trip needed)

## Test strategy: MagicMock (no emulator)

Azure has **no official local emulator** for Key Vault (Azurite
covers Storage / Service Bus, not KV). The `tests/conftest.py`
fixtures use `unittest.mock.MagicMock` shaped like the real
`SecretClient` / `KeyClient` interfaces. Tests configure per-test
return values via `mock.get_secret.return_value = ...` and
`mock.method.side_effect = ResourceNotFoundError(...)`.

A `real_azure_session` fixture is provided for users who want to
run against a real Azure Key Vault (gated by the
`ATLAS_RICHIE_SECRET_AZURE_TEST_VAULT_URL` env var; tests skip
gracefully otherwise). This is the documented escape hatch for
production validation.

## Errors

- `azure.core.exceptions.ResourceNotFoundError` →
  `SecretIntegrityException` (404 equivalent)
- `azure.core.exceptions.ClientAuthenticationError` →
  `SecretException("SEC-AUTH-001")`
- `azure.core.exceptions.HttpResponseError` 401 →
  `SecretException("SEC-AUTH-001")`
- 403 → `SEC-AUTHZ-001`
- 404 (on KeyClient) → `SecretCryptoException("SEC-KEY-001")`
- 5xx → `SecretException("SEC-PROVIDER-001")`

## Test results

- **Unit** (no Azure): 13 tests pass
  - `test_azure_properties.py` — 7
  - `test_azure_configuration.py` — 6
- **Integration** (mocked Azure SDK clients): 18 tests pass
  - `test_azure_client.py` — 18 (SecretOperations get / versioned /
    metadata / exists / missing, KeyWrappingBackend wrap+unwrap +
    tampered, key-bindings, bootstrap STARTUP+OPTIONAL, session
    close + post-close, writer/deletable/signing all None)
- **Total per wheel**: 31/31 in 0.12s
- **Total `components/secret/`**: 212/212 in 1.81s

## Isolated-wheel verification (15/15)

```
atlas-richie-secret-azure-keyvault==0.2.0
  → atlas-richie-secret-core==0.2.0
  → atlas-richie-contracts==0.2.0
  → azure-identity==1.25.3
  → azure-keyvault-secrets==4.11.2
  → azure-keyvault-keys==4.11.2
  → azure-core==1.41.0
  → msal==1.38.0
  → msal-extensions==1.3.1
  → pyjwt==2.14.0
  → isodate==0.7.2
  → pydantic==2.13.5
  → pydantic-settings==2.15.0
  → typing-extensions==4.16.0
  → python-dotenv==1.2.3
```

15/15 packages successfully import their public module in fresh
`python -m venv`.

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-azure-keyvault`
  to `tool.uv.workspace.members` + `tool.uv.sources`.
- `versions.toml` — added `atlas-richie-secret-azure-keyvault = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added the dep constraint.
- `tools/release/verify_isolated_wheels.py` — added the new entry.
- `tools/sync_versions.py` — synced 16 `pyproject.toml` files
  clean.

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (4-SPI subset matching
      Java's `providerCapabilities`)
- [x] Bilingual docstrings on every public module / class / method
- [x] No Azure SDK types in the public facade
- [x] `pytest` 212/212 pass across all 6 secret wheels
- [x] `tools/release/verify_isolated_wheels.py` 15/15 OK
- [x] `tools/sync_versions.py` 16/16 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` / `versions.toml` / `foundation/platform` /
      `verify_isolated_wheels.py` updated
- [x] Handoff doc written
- [ ] Single commit + push
