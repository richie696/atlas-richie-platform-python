# R-237 Handoff: `atlas-richie-secret-gcp-kms` — Google Cloud Secret Manager + KMS

**Date:** 2026-09-12
**Owner:** Mavis
**Status:** **DONE** — 26/26 gcp tests pass (5 properties unit + 4
configuration unit + 17 client integration), all **238/238 secret
tests pass** across all 7 secret wheels (62 core + 20 redis + 56
vault + 6 openbao + 37 aws + 31 azure + 26 gcp),
`atlas-richie-secret-gcp-kms` 0.2.0 wheel built, **16/16 isolated
wheels install + import OK** in fresh venv.

## Motivation

R-233 / R-235 / R-236 added the framework + Vault / OpenBao / AWS
/ Azure backends. **R-237** adds the **sixth remote backend**:
**Google Cloud Secret Manager + KMS**, mirroring Java
`atlas-richie-secret-provider-gcp` 1:1.

Java's GCP module is structurally identical to the Azure module
(R-236) — a thin stub declaring a 4-SPI capability set. The Python
side follows the same narrow scope.

## Design parity with Java

| SPI | Java | Python (R-237) |
|---|---|---|
| `SecretOperations` | yes | yes |
| `KeyWrappingBackend` | yes (KMS encrypt/decrypt) | yes |
| `SigningBackend` | **no** | **no** |
| `SecretBootstrapClient` | yes | yes |
| `SecretProviderSession` | yes | yes |
| `SecretListable` | **no** | **no** |

Java's `GcpSecretBootstrapProviderFactory.providerCapabilities() = Set.of(
SECRET_READ, SECRET_VERSIONING, KEY_WRAP, KEY_UNWRAP)`.

## Java → Python structural mapping

```
components/secret/secret-gcp-kms/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_gcp_kms/
    ├── __init__.py            ← public surface (6 symbols)
    ├── client.py              ← GcpSecretClient (4-SPI composite)
    ├── configuration.py       ← GcpConfigurationResolver + SHA-256 hash
    ├── factory.py             ← GcpSecretProviderFactory + GcpClientFactory
    └── properties.py          ← GcpSecretProperties + GcpKmsAlgorithm
└── tests/
    ├── conftest.py                ← MagicMock SDK clients + real-GCP skip fixture
    ├── test_gcp_properties.py     ← 5 unit tests
    ├── test_gcp_configuration.py ← 4 unit tests
    └── test_gcp_client.py         ← 17 integration tests via MagicMock
```

## Functional surface (6 public symbols)

- `GcpSecretProperties` — pydantic-settings env-injected; prefix
  `ATLAS_RICHIE_SECRET_GCP_`. Carries `project_id` / `kms_location` /
  `kms_key_ring` / `kms_key_bindings`.
- `GcpKmsAlgorithm` — `StrEnum { EXTERNAL, SOFTWARE }` (subset that
  does not require HSM).
- `ResolvedGcpConfiguration` + `GcpConfigurationResolver` — SHA-256
  `configuration_hash` over canonical fields, static
  `SecretCapability` (`can_list=False`).
- `GcpClientFactory` — build `(SecretManagerServiceClient,
  KeyManagementServiceClient)` from `GcpSecretProperties` using
  `google.auth.default()`.
- `GcpSecretProviderFactory` — `SecretProviderFactory` implementation
  (`name = f"gcp-{project_id}"`, `backend = SecretBackend.GCP`).
- `GcpSecretClient` — composite 4-SPI client. `writer` / `deletable` /
  `signing` properties all return `None`.

## SDKs

- `google-cloud-secret-manager` — `SecretManagerServiceClient` for read
- `google-cloud-kms` — `KeyManagementServiceClient` for crypto
- `google-auth` — `google.auth.default()` for ADC chain
  (env / metadata server / `gcloud auth application-default login` /
  workload identity)

## Test strategy: MagicMock

GCP has no local emulator for Secret Manager or KMS. Tests use
`unittest.mock.MagicMock` shaped like the real SDK clients. A
`real_gcp_session` fixture is provided behind
`ATLAS_RICHIE_SECRET_GCP_TEST_PROJECT_ID` for real-cloud
validation (skips if unset).

## Errors

- `google.api_core.exceptions.NotFound` → `SecretIntegrityException`
- `Unauthorized` → `SecretException("SEC-AUTH-001")`
- `PermissionDenied` → `SecretException("SEC-AUTHZ-001")`
- `ResourceExhausted` → `SecretException("SEC-PROVIDER-001")`
- Other `GoogleAPIError` → `SecretException("SEC-PROVIDER-001")` (general)

## Test results

- **Unit**: 9 tests pass
  - `test_gcp_properties.py` — 5
  - `test_gcp_configuration.py` — 4
- **Integration** (mocked SDK): 17 tests pass
  - `test_gcp_client.py` — 17 (get / versioned / metadata / exists /
    missing, KMS wrap+unwrap + tampered, key-bindings, bootstrap
    STARTUP+OPTIONAL, session close + post-close, writer/deletable/
    signing all None)
- **Total per wheel**: 26/26 in 0.04s
- **Total `components/secret/`**: 238/238

## Isolated-wheel verification (16/16)

GCP's transitive dep tree is significantly larger than the other
backends (gRPC + opentelemetry + grpcio-status + googleapis-common-protos
+ pyasn1 + rsa + ...). The wheelhouse now contains all of:

```
atlas-richie-secret-gcp-kms==0.2.0
  → atlas-richie-secret-core==0.2.0
  → atlas-richie-contracts==0.2.0
  → google-cloud-secret-manager==2.30.0
  → google-cloud-kms==3.16.0
  → google-auth==2.58.0
  → google-api-core==2.36.0
  → googleapis-common-protos==1.75.3
  → grpc-google-iam-v1==0.14.5
  → grpcio==1.83.1
  → grpcio-status==1.83.1
  → proto-plus==1.28.4
  → protobuf==7.36.1
  → opentelemetry-api==1.44.0
  → pyasn1==0.6.4
  → pyasn1-modules==0.4.2
  → pydantic==2.13.5
  → pydantic-settings==2.15.0
  → typing-extensions==4.16.0
  → python-dotenv==1.2.3
```

16/16 packages successfully import their public module in fresh
`python -m venv`.

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-gcp-kms` to
  workspace members + sources.
- `versions.toml` — added `atlas-richie-secret-gcp-kms = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added the dep constraint.
- `tools/release/verify_isolated_wheels.py` — added the new entry.
- `tools/sync_versions.py` — synced 17 `pyproject.toml` files
  clean.

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (4-SPI subset)
- [x] Bilingual docstrings on every public module / class / method
- [x] No GCP SDK types in the public facade
- [x] `pytest` 238/238 pass across all 7 secret wheels
- [x] `tools/release/verify_isolated_wheels.py` 16/16 OK
- [x] `tools/sync_versions.py` 17/17 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` / `versions.toml` / `foundation/platform` /
      `verify_isolated_wheels.py` updated
- [x] Handoff doc written
- [ ] Single commit + push
