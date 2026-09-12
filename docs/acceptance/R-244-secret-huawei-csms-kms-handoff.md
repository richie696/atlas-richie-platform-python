# R-244: atlas-richie-secret-huawei-csms-kms — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-huawei` (post-SDK-refactor:
3 main files) collapsed into a single Python wheel with
4 source files.

## Public symbol list

### `properties.py` (2)
- `AuthType` — StrEnum (`ACCESS_KEY` only)
- `HuaweiSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_HUAWEI_`

### `configuration.py` (2)
- `ResolvedHuaweiConfiguration` — frozen dataclass
- `HuaweiConfigurationResolver` — endpoint / auth /
  project_id / secrets / kms_key_bindings validation,
  SHA-256 hash (includes capability fingerprint, R-242)

### `client.py` (5)
- `HuaweiCsmsGetResponse` / `HuaweiKmsEncryptResponse` /
  `HuaweiKmsDecryptResponse` — frozen dataclasses
- `CsmsLike` / `KmsLike` — `runtime_checkable` Protocols
- `HuaweiSecretClient` — 3-SPI composite (SecretOperations
  via CSMS + KeyWrappingBackend via DEW + SecretBootstrapClient
  + SecretProviderSession)

### `factory.py` (2)
- `HuaweiClientFactory` — `(CsmsLike, KmsLike)` builder
  (lazy SDK import)
- `HuaweiSecretProviderFactory` — framework entry

**Total: 11 public symbols** (matches Java 3-file module).

## Test count

**31 tests, 31 passed** in 0.13s.

- `test_huawei_client.py` — 16 tests (read / metadata /
  binary / unmapped / 404 NotFound / 5xx doesn't-look-like-missing /
  wrap empty / round-trip / AAD / wrong algorithm / missing
  key binding / bootstrap STARTUP / bootstrap OPTIONAL /
  descriptor / writer/deletable None / close idempotent /
  read after close)
- `test_huawei_configuration.py` — 15 tests (region /
  project_id / access_key_id / access_key_secret required /
  endpoint scheme / blank logical / blank physical /
  hash 64 hex / hash changes with region / hash changes
  with project_id / capability)

## SDK approach

The `huaweicloud-sdk-python` package is the official
Huawei Cloud SDK. Two clients are used:

- `huaweicloudsdkcsms.v1.csms_client.CsmsClient` —
  `show_secret_version`
- `huaweicloudsdkkms.v2.kms_client.KmsClient` —
  `encrypt_data` / `decrypt_data`

Authentication uses `BasicCredentials(ak, sk, project_id,
security_token)`. **Note**: Python SDK version on PyPI is
**`1.0.x`** (the `3.1.x` version used by the Java side is
the Java SDK version; the Python SDK is on a different
versioning track). The functional surface is the same.

The SDK is opt-in via `optional-dependency [sdk]`.
Importing the wheel does NOT require the SDK;
`HuaweiClientFactory.create_clients` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install 'atlas-richie-secret-huawei-csms-kms[sdk]'`
if the SDK is missing.

## Test approach — in-process fake SDK clients

Tests use `FakeCsms` / `FakeKms` (in-process, real objects,
not MagicMock). The fake CSMS stores secrets in an internal
dict and raises a 404 `http_status_code` error on missing
entries. The fake KMS uses a `cipher:` prefix round-trip.

## Java → Python translation table

| Java | Python |
|---|---|
| `HuaweiSecretProperties.java` (SDK-refactor version) | `HuaweiSecretProperties` (pydantic-settings) |
| `HuaweiSdkSecretTransport.java` (CSMS + DEW) | `HuaweiSecretClient` (3-SPI composite, `CsmsLike` / `KmsLike` Protocols) |
| `HuaweiSecretBootstrapProviderFactory.java` (~10 lines post-refactor) | `HuaweiSecretProviderFactory` (framework entry) |
| `HuaweiSdkSecretTransportTest.java` | `test_huawei_client.py` |

## Notable adaptations (Pythonic 1:1)

1. **NotFound boundary** — only HTTP 404 maps to
   `null` / `SecretIntegrityException`; all other
   `ServiceResponseException` surface as `SEC-PROVIDER-001`
   (read) or `SEC-CRYPTO-001/002` (wrap/unwrap). A test
   explicitly verifies that an HTTP 500 does NOT
   masquerade as a missing secret (R-242 SDK-refactor
   mandate).

2. **AAD via `additionalAuthenticatedData`** — Huawei DEW
   accepts a base64-encoded AAD string. The framework's
   AAD is `Mapping[str, str]`; the client serializes the
   dict as a deterministic JSON and base64-encodes it.
   No `SEC-CAP-001` is raised for AAD on this backend
   (unlike Azure RSA / IBM Key Protect / Baidu BCE).

3. **`project_id` is mandatory** — Huawei DEW
   `BasicCredentials` requires it; the configuration
   resolver raises `SEC-BOOT-003` if blank. This is a
   **harder** requirement than the Java side (which
   inherits it via `RemoteProviderProperties.projectId`).

4. **Capability fingerprint in config hash** — R-242
   framework upgrade. The configuration hash now
   includes `capability_fingerprint(_huawei_capability())`
   so a capability change forces session rebuild.

5. **Legacy REST config rejected by design** — the wheel
   has NO `wire.*` / `tls.*` / `proxy.*` fields. The Java
   refactor mandates that "config appears active but is
   ignored" must be rejected at startup; in Python, we
   simply don't expose the fields.

## Blocked

- **Real Huawei Cloud integration** — requires an IAM
  user with `csms:secret:list` / `kms:cmk:encrypt` /
  `kms:cmk:decrypt` permissions and a region with CSMS +
  KMS enabled. Marked as `integration` in
  `pyproject.toml` markers; documented in the README;
  skipped locally without env override.
