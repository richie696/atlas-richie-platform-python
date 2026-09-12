# R-248: atlas-richie-secret-baidu-kms — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-baidu` (post-SDK-refactor:
3 main files) translated into a single Python wheel with
4 source files. **KMS-only** (no Secret Store).

## Public symbol list

### `properties.py` (2)
- `AuthType` — StrEnum (`ACCESS_KEY` only)
- `BaiduSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_BAIDU_`

### `configuration.py` (2)
- `ResolvedBaiduConfiguration` — frozen dataclass
- `BaiduConfigurationResolver` — endpoint / auth /
  kms_key_bindings validation, SHA-256 hash (capability
  fingerprint included, R-242)

### `client.py` (4)
- `BaiduKmsEncryptResponse` /
  `BaiduKmsDecryptResponse` — frozen dataclasses
- `KmsLike` — `runtime_checkable` Protocol (2 methods)
- `BaiduSecretClient` — 2-SPI composite
  (`KeyWrappingBackend` + `SecretProviderSession` only;
  `operations` / `writer` / `deletable` return `None`,
  `read` / `metadata` raise `SEC-CAP-001` via
  `assert_can_read`)

### `factory.py` (2)
- `BaiduClientFactory` — `KmsLike` builder
- `BaiduSecretProviderFactory` — framework entry

**Total: 10 public symbols** (matches Java 3-file module
public surface).

## Test count

**36 tests, 36 passed** in 0.11s.

- `test_baidu_client.py` — 18 tests (descriptor /
  operations None / writer & deletable None / configuration
  hash / read raises SEC-CAP-001 / metadata raises
  SEC-CAP-001 / wrap then unwrap / empty DEK / wrong
  algorithm / empty ciphertext / missing key binding /
  AAD raises SEC-CAP-001 / close idempotent / read after
  close / configuration property / factory descriptor /
  factory create with fake)
- `test_baidu_configuration.py` — 18 tests
  (access_key_id required / access_key_secret required /
  region default / endpoint with host OK / endpoint no
  host rejected / endpoint with port / access key blank
  rejected by config resolver / access key secret blank
  rejected by config resolver / blank logical / blank
  physical / hash 64 hex / hash changes with region /
  hash changes with endpoint / hash changes with keys /
  hash stable / hash includes capability fingerprint /
  capability KMS-only / resolved contains provider id)

## SDK approach

The `bce-python-sdk` package (v0.9.79) is the official
Baidu BCE Python SDK. One client is used:

- `baidubce.services.kms.KmsClient` — `encrypt` /
  `decrypt`

Authentication uses
`DefaultBceCredentials(access_key_id, access_key_secret)`
plus `KmsClientConfiguration(endpoint, protocol,
credentials)`. Java's `KmsClientConfiguration` takes
`endpoint.getHost() + (port < 0 ? "" : ":" + port)`;
the Python equivalent is built from `urlparse` of the
configured `kms_endpoint`.

The SDK is opt-in via `optional-dependency [sdk]`.
Importing the wheel does NOT require the SDK;
`BaiduClientFactory.create_kms` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install 'atlas-richie-secret-baidu-kms[sdk]'`
if the SDK is missing.

## Test approach — in-process fake KMS

Tests use `FakeKms` (in-process, real object, not
MagicMock). The fake uses a pass-through round-trip
(`encrypt` stores `plaintext_b64` as ciphertext, `decrypt`
returns the same value); this matches the symmetric
nature of the BCE KMS API for smoke testing. The fake
also records the last call so tests can verify the wire
payload.

## Java → Python translation table

| Java | Python |
|---|---|
| `BaiduSecretProperties.java` (SDK-refactor version) | `BaiduSecretProperties` (pydantic-settings) |
| `BaiduSdkSecretTransport.java` (KMS-only, ~90 lines) | `BaiduSecretClient` + `KmsLike` Protocol + SDK adapter in `factory.py` |
| `BaiduSecretBootstrapProviderFactory.java` (~10 lines post-refactor) | `BaiduSecretProviderFactory` (framework entry) |
| `BaiduSdkSecretTransportTest.java` | `test_baidu_client.py` |

## Notable adaptations (Pythonic 1:1)

1. **Endpoint parsing** — Java's
   `endpoint.getHost() + (port < 0 ? "" : ":" + port)`
   translates to `urlparse(...).hostname` plus optional
   `:port` in the Python factory. The `protocol` field
   is derived from the URL scheme (`http` → `Protocol.HTTP`,
   `https` → `Protocol.HTTPS`).

2. **`AuthType.ACCESS_KEY` only** — matches Java's
   `RemoteProviderProperties.AuthenticationType.ACCESS_KEY`.
   BEARER_TOKEN / API_KEY are rejected (`SEC-BOOT-003`)
   because BCE KMS uses AK + SK signing, not bearer
   tokens.

3. **No AAD support** — Java
   `BaiduSdkSecretTransport.requireNoAad` raises
   `SEC-CAP-001` if `context.attributes()` is non-empty or
   `context.associatedData()` is non-empty. The Python
   client uses the framework's `require_aad_support`
   gate, which provides the same error category
   (SEC-CAP-001) and the same trigger condition.

4. **NotFound boundary** — N/A (KMS-only; the framework
   never calls `read` on a Baidu session because
   `client.operations` returns `None`).

5. **Capability fingerprint in config hash** — R-242
   framework upgrade. KMS-only capability means a
   capability change (e.g. if Baidu later adds a Secret
   Store API) would force a session rebuild via the
   configuration hash change.

6. **`access_key_id` / `access_key_secret` blank
   validation** — moved from pydantic field-level
   validators to the configuration resolver, to match the
   pattern of R-247 IBM and R-245 Volcengine. The
   pydantic `Field(...)` still requires presence (not
   `None`); the resolver rejects blank values with
   `SEC-BOOT-003`.

## Blocked

- **Real Baidu Cloud integration** — requires a Baidu
  Cloud account with `kms:Encrypt` / `kms:Decrypt` IAM
  permissions and an AK / SK pair. Marked as
  `integration` in `pyproject.toml` markers; documented
  in the README; skipped locally without env override.
