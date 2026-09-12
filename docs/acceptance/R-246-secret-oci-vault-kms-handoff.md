# R-246: atlas-richie-secret-oci-vault-kms — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-oci` (post-SDK-refactor: 2 main
files) translated into a single Python wheel with 4 source
files. **3-SPI composite** (`SecretOperations` via Vault
`getSecretBundle` + `KeyWrappingBackend` via KMS
`encrypt` / `decrypt` + `SecretBootstrapClient` +
`SecretProviderSession`).

## Public symbol list

### `properties.py` (2)
- `AuthType` — StrEnum (`NONE` / `WORKLOAD_IDENTITY_TOKEN_FILE`)
- `OciSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_OCI_`

### `configuration.py` (2)
- `ResolvedOciConfiguration` — frozen dataclass
- `OciConfigurationResolver` — endpoint / auth / secrets /
  kms_key_bindings validation, SHA-256 hash (capability
  fingerprint included, R-242)

### `client.py` (6)
- `OciVaultSecret` / `OciKmsEncryptResponse` /
  `OciKmsDecryptResponse` — frozen dataclasses
- `VaultLike` — `runtime_checkable` Protocol (1 method)
- `KmsLike` — `runtime_checkable` Protocol (2 methods,
  `associated_data: dict[str, str] | None` — matches the
  OCI Python SDK's `EncryptDataDetails.associated_data`
  shape, not a base64 string)
- `OciSecretClient` — 3-SPI composite

### `factory.py` (2)
- `OciClientFactory` — `(VaultLike, KmsLike)` builder
- `OciSecretProviderFactory` — framework entry

**Total: 12 public symbols** (matches Java 2-file module
public surface, expanded per Python idiom with explicit
Protocols and frozen response dataclasses).

## Test count

**47 tests, 47 passed** in 0.15s.

- `test_oci_client.py` — 26 tests (descriptor / operations
  returns self / writer & deletable None / configuration
  hash / read returns value / logical-to-physical mapping /
  unmapped logical fallback / NotFound-via-null integrity /
  HTTP 404 integrity / SEC-PROVIDER-001 on other exceptions /
  metadata / version selectors (STATIC / PINNED_AT_TIME) /
  wrap-then-unwrap with AAD / no AAD round-trip / empty DEK
  raises / wrong algorithm raises / empty ciphertext raises /
  missing key binding raises / close idempotent / read after
  close / configuration property / factory descriptor /
  factory default configuration / factory create with
  fakes)
- `test_oci_configuration.py` — 21 tests (region required /
  blank region rejected / auth type default / https endpoint
  OK / http non-loopback rejected / http loopback allowed /
  kms endpoint https / Instance Principal OK / Resource
  Principal OK / blank logical rejected / blank physical
  rejected / blank logical in bindings / blank physical in
  bindings / hash 64 hex / hash changes with region / hash
  changes with auth / hash changes with secrets / hash
  stable / hash includes capability fingerprint /
  capability SECRET_READ / resolved contains provider id)

## SDK approach

The `oci` package (v2.184.2) is the official OCI Python
SDK. Two clients are used:

- `oci.secrets.SecretsClient` — `get_secret_bundle`
- `oci.key_management.KmsCryptoClient` — `encrypt` /
  `decrypt`

Authentication is forced to one of:
- `NONE` → `InstancePrincipalsAuthenticationDetailsProvider`
  (Java side: `NONE` → `InstancePrincipalsAuthenticationDetailsProvider`)
- `WORKLOAD_IDENTITY_TOKEN_FILE` →
  `ResourcePrincipalAuthenticationDetailsProvider`
  (Java side: same)

API-key auth is rejected (`SEC-BOOT-003`) because the OCI
SDK does not support it the same way as a stand-alone REST
client; the framework also rejects it on the Java side.

The SDK is opt-in via `optional-dependency [sdk]`.
Importing the wheel does NOT require the SDK;
`OciClientFactory.create` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install 'atlas-richie-secret-oci-vault-kms[sdk]'`
if the SDK is missing.

## Test approach — in-process fake Vault + KMS

Tests use `FakeVault` / `FakeKms` (in-process, real
objects, not MagicMock). The fake KMS uses a `wrap:<key>:<plaintext>`
prefix round-trip to verify AAD and unwrap semantics, the
same pattern as R-235 AWS / R-245 Volcengine.

## Java → Python translation table

| Java | Python |
|---|---|
| `OciSecretProperties.java` (SDK-refactor version) | `OciSecretProperties` (pydantic-settings) |
| `OciSdkSecretTransport.java` (3-SPI scope, ~85 lines) | `OciSecretClient` + `VaultLike` / `KmsLike` Protocols + SDK adapter methods in `factory.py` |
| `OciSecretBootstrapProviderFactory.java` (~10 lines post-refactor) | `OciSecretProviderFactory` (framework entry) |
| `OciSdkSecretTransportTest.java` | `test_oci_client.py` |

## Notable adaptations (Pythonic 1:1)

1. **AAD via `associatedData` map** — the OCI Python SDK's
   `EncryptDataDetails.associated_data` is `dict[str, str]`
   (NOT bytes as the Java SDK accepts the same shape but the
   internal `aad` helper base64-encodes raw bytes). The
   framework's `CryptoContext.aad` is also `Mapping[str, str]`,
   so the values are passed through unchanged (sorted by key
   for stability). No base64 / JSON canonicalization is
   applied — both sides already agree on the string-map
   shape.

2. **NotFound boundary** — Java transport returns `null`
   on HTTP 404; the Python client maps `BmcException.status
   == 404` to `SecretIntegrityException` to keep the
   framework's "missing secret" path uniform across all
   backends. The framework never calls `session.read()`
   expecting `None` — the unified contract treats
   `SecretIntegrityException` as the only legitimate
   "missing" signal.

3. **`AuthType.NONE` for Instance Principal** — matches
   Java's `RemoteProviderProperties.AuthenticationType.NONE`
   naming. The SDK auto-discovers the instance's OCI
   identity; no token file is read. The Python SDK's
   `InstancePrincipalsAuthenticationDetailsProvider` does
   the same SDK calls as the Java SDK.

4. **`AuthType.WORKLOAD_IDENTITY_TOKEN_FILE` for Resource
   Principal** — matches Java's
   `WORKLOAD_IDENTITY_TOKEN_FILE`. The actual token file
   path is NOT read by the SDK (the OCI runtime provides the
   credentials); the env var is just a marker.

5. **Stage selector via Java `GetSecretBundleRequest.Stage`
   enum** — the Python client converts the framework's
   LATEST / STATIC / PINNED_AT_TIME selectors to
   `(version_number, stage, secret_version_name)` kwargs
   for `VaultLike.get_secret_bundle`. STAGE selector is
   NOT exposed by the framework; the OCI client falls
   back to LATEST for both `LATEST` and `PINNED_AT_TIME`
   selectors (same as R-245 Volcengine fallback).

6. **Capability fingerprint in config hash** — R-242
   framework upgrade. The OCI capability (can_read=True /
   can_write=False / can_rotate=True) is part of the
   hash; a future capability change would force a
   session rebuild via the configuration hash.

## Blocked

- **Real OCI integration** — requires an OCI tenancy with
  Vault + KMS permissions and either Instance Principal or
  Resource Principal configured. Marked as `integration`
  in `pyproject.toml` markers; documented in the README;
  skipped locally without env override.

- **OCI SDK `associatedData` is dict[str, str], not
  bytes** — diverges from the Java SDK's
  `Map<String, String> aad()` helper that base64-encodes
  `context.associatedData()` raw bytes. The framework's
  AAD is already a `Mapping[str, str]`, so this is
  internally consistent on the Python side. If we ever
  need to round-trip with a Java client that uses
  `atlas.secret.aad` byte encoding, we add a one-liner
  adapter here.
