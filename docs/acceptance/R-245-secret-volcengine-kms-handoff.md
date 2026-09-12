# R-245: atlas-richie-secret-volcengine-kms — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-volcengine` (post-SDK-refactor:
3 main files) collapsed into a single Python wheel with
4 source files. **KMS-only** (no Secret Store).

## Public symbol list

### `properties.py` (2)
- `AuthType` — StrEnum (`ACCESS_KEY` only)
- `VolcengineSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_VOLCENGINE_`

### `configuration.py` (2)
- `ResolvedVolcengineConfiguration` — frozen dataclass
- `VolcengineConfigurationResolver` — endpoint / auth /
  namespace / kms_key_bindings validation, SHA-256 hash

### `client.py` (3)
- `VolcengineKmsEncryptResponse` /
  `VolcengineKmsDecryptResponse` — frozen dataclasses
- `KmsLike` — `runtime_checkable` Protocol (2 methods)
- `VolcengineSecretClient` — 2-SPI composite
  (`KeyWrappingBackend` + `SecretProviderSession` only;
  `operations` / `writer` / `deletable` return `None`)

### `factory.py` (2)
- `VolcengineClientFactory` — `KmsLike` builder
- `VolcengineSecretProviderFactory` — framework entry

**Total: 9 public symbols** (matches Java 3-file module).

## Test count

**22 tests, 22 passed** in 0.11s.

- `test_volcengine_client.py` — 8 tests (descriptor /
  operations/writer/deletable None / wrap empty /
  round-trip with AAD / wrong algorithm / missing key
  binding / close idempotent / wrap after close)
- `test_volcengine_configuration.py` — 14 tests
  (region / namespace / access_key_id / access_key_secret
  required / endpoint scheme / blank logical / blank
  physical / hash 64 hex / hash changes with namespace /
  hash changes with region / capability KMS-only)

## SDK approach

The `volcengine-python-sdk` package is the official
Volcengine SDK. One client is used:

- `volcengine.kms.KmsApi.KmsApi` — `encrypt` / `decrypt`

Authentication uses `StaticCredentialProvider(ak, sk,
security_token)`.

The SDK is opt-in via `optional-dependency [sdk]`.
Importing the wheel does NOT require the SDK;
`VolcengineClientFactory.create_kms` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install 'atlas-richie-secret-volcengine-kms[sdk]'`
if the SDK is missing.

## Test approach — in-process fake KMS

Tests use `FakeKms` (in-process, real object, not
MagicMock). The fake uses a `cipher:` prefix round-trip
similar to the R-235 AWS wheel.

## Java → Python translation table

| Java | Python |
|---|---|
| `VolcengineSecretProperties.java` (SDK-refactor version) | `VolcengineSecretProperties` (pydantic-settings) |
| `VolcengineSdkSecretTransport.java` (KMS-only, ~100 lines) | `VolcengineSecretClient` (2-SPI composite, `KmsLike` Protocol) |
| `VolcengineSecretBootstrapProviderFactory.java` (~10 lines post-refactor) | `VolcengineSecretProviderFactory` (framework entry) |
| `VolcengineSdkSecretTransportTest.java` | `test_volcengine_client.py` |

## Notable adaptations (Pythonic 1:1)

1. **NotFound boundary** — N/A (KMS-only; the framework
   never calls `read` on a Volcengine session because
   `client.operations` returns `None`).

2. **`SEC-CAP-001` capability gate** — the Java transport's
   `read` method throws `SEC-CAP-001` because Volcengine
   has no Secret Store. The Python client achieves the
   same effect declaratively: `operations` returns `None`,
   so the framework's `list_capability(session)` probe
   observes `None` and never tries to call `read`.

3. **AAD via `encryptionContext` map** — Volcengine KMS
   `encryptionContext` is a `Map<String, String>`. The
   framework's AAD `Mapping[str, str]` is passed through
   directly (no base64 needed, since both are string maps).

4. **`namespace` is mandatory** — the Volcengine
   `EncryptRequest` requires a `keyringName` (Java calls
   it `keyringName`; the Python `volcengine-python-sdk`
   mirrors this as `keyring_name`). The configuration
   resolver raises `SEC-BOOT-003` if blank.

5. **Capability fingerprint in config hash** — R-242
   framework upgrade. KMS-only capability means a
   capability change (e.g. if Volcengine later adds a
   Secret Store API) would force a session rebuild via
   the configuration hash change.

## Blocked

- **Real Volcengine integration** — requires a Volcengine
  account with `kms:Encrypt` / `kms:Decrypt` IAM
  permissions and a region with KMS enabled. Marked as
  `integration` in `pyproject.toml` markers; documented
  in the README; skipped locally without env override.
