# atlas-richie-secret-gcp-kms

Google Cloud Secret Manager + KMS backend for the Atlas Richie
secret platform. Implements the **4-SPI subset** that Java
`atlas-richie-secret-provider-gcp` exposes:

| SPI | Implemented? | Reason |
|---|---|---|
| `SecretOperations` | yes | GCP Secret Manager API read |
| `KeyWrappingBackend` | yes | GCP KMS API encrypt / decrypt |
| `SigningBackend` | **no** | Java side does not expose it |
| `SecretBootstrapClient` | yes | Startup-time batch read |
| `SecretProviderSession` | yes | Provider lifecycle |
| `SecretListable` | **no** | Java side's capability declaration does not include LIST |

Same narrower 4-SPI scope as the Azure wheel (R-236) — Java
`GcpSecretBootstrapProviderFactory` declares only
`SECRET_READ / SECRET_VERSIONING / KEY_WRAP / KEY_UNWRAP`.

## SDKs

- `google-cloud-secret-manager` — `SecretManagerServiceClient` for read
- `google-cloud-kms` — `KeyManagementServiceClient` for crypto
- `google-auth` — `google.auth.default()` for credential chain
  (env / metadata server / `gcloud auth application-default login`)

## Local development

There is no official GCP Secret Manager / KMS emulator. Tests use
`unittest.mock.MagicMock` shaped like the real SDK clients. Real
integration tests are gated by
`ATLAS_RICHIE_SECRET_GCP_TEST_PROJECT_ID`; if it is not set,
integration markers `pytest.skip` gracefully.

## See also

- `atlas-richie-secret-core` — framework + Protocols
- `atlas-richie-secret-vault` / `atlas-richie-secret-aws-kms` /
  `atlas-richie-secret-azure-keyvault` — sibling remote backends
- `docs/acceptance/R-237-secret-gcp-kms-handoff.md`
