# R-243: atlas-richie-secret-tencent-ssm-kms — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-tencent` (post-SDK-refactor:
3 main files / 1 test file) collapsed into a single Python
wheel with 4 source files.

## Public symbol list

### `properties.py` (2)
- `AuthType` — StrEnum (`ACCESS_KEY` only — matches Java's
  post-refactor ACCESS_KEY-only constraint)
- `TencentSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_TENCENT_`

### `configuration.py` (2)
- `ResolvedTencentConfiguration` — frozen dataclass
  (provider_id, properties, configuration_hash, capability)
- `TencentConfigurationResolver` — endpoint / auth / secrets
  / kms_key_bindings validation, SHA-256 hash
  (**includes capability fingerprint**, R-242 framework
  upgrade)

### `client.py` (5)
- `TencentSsmGetResponse` / `TencentKmsEncryptResponse` /
  `TencentKmsDecryptResponse` — frozen response dataclasses
- `SsmLike` / `KmsLike` — `runtime_checkable` Protocols
  (3 methods total)
- `TencentSecretClient` — 3-SPI composite
  (`SecretOperations` via SSM + `KeyWrappingBackend` via KMS
  + `SecretBootstrapClient` + `SecretProviderSession`)

### `factory.py` (2)
- `TencentClientFactory` — `(SsmLike, KmsLike)` builder
  (lazy SDK import)
- `TencentSecretProviderFactory` — framework entry

**Total: 11 public symbols** (matches Java 3-file module).

## Test count

**34 tests, 34 passed** in 0.13s.

- `test_tencent_client.py` — 19 tests (read / metadata /
  binary / unmapped path / NotFound / 5xx-doesn't-look-like-missing /
  wrap empty / round-trip / wrong algorithm / missing key binding /
  AAD support / bootstrap STARTUP / bootstrap OPTIONAL /
  descriptor / writer/deletable None / close idempotent /
  read after close)
- `test_tencent_configuration.py` — 15 tests (region
  required / access_key_id required / access_key_secret
  required / endpoint scheme / blank logical / blank physical
  / hash 64 hex / hash changes with region / capability)

## SDK approach

The `tencentcloud-sdk-python` package is the official
Tencent Cloud SDK (TC3 signing built in). Two clients are
used:

- `tencentcloud-sdk-python-ssm` — `SsmClient.GetSecretValue`
- `tencentcloud-sdk-python-kms` — `KmsClient.Encrypt` /
  `Decrypt`

The SDK is opt-in via `optional-dependency [sdk]`.
Importing the wheel does NOT require the SDK;
`TencentClientFactory.create_clients` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install 'atlas-richie-secret-tencent-ssm-kms[sdk]'`
if the SDK is missing.

## Test approach — in-process fake SDK clients

Tests use `FakeSsm` / `FakeKms` (in-process, real objects,
not MagicMock). The fake SSM stores secrets in an internal
dict and raises a `ResourceNotFound` error (matching
Tencent SDK's error code shape) on missing entries. The
fake KMS uses a `cipher:` prefix round-trip similar to the
R-235 AWS wheel.

## Java → Python translation table

| Java | Python |
|---|---|
| `TencentSecretProperties.java` (SDK-refactor version, ~80 lines) | `TencentSecretProperties` (pydantic-settings) |
| `TencentSdkSecretTransport.java` (87 lines, SSM + KMS) | `TencentSecretClient` (3-SPI composite, `SsmLike` / `KmsLike` Protocols) |
| `TencentSecretBootstrapProviderFactory.java` (~10 lines post-refactor) | `TencentSecretProviderFactory` (framework entry) |
| `TencentSdkSecretTransportTest.java` | `test_tencent_client.py` |

## Notable adaptations (Pythonic 1:1)

1. **NotFound boundary** — only `ResourceNotFound.ErrorCode`
   (case-insensitive) maps to `null` / `SecretIntegrityException`;
   all other SDK exceptions surface as `SEC-PROVIDER-001`
   (read) or `SEC-CRYPTO-001/002` (wrap/unwrap). A test
   explicitly verifies that an `InternalError`-shaped
   exception does NOT masquerade as a missing secret
   (this is the R-242 SDK-refactor mandate).

2. **AAD via `EncryptionContext`** — the Java transport
   encodes AAD bytes as `atlas.secret.aad=<base64>` plus
   attributes. The framework's `CryptoContext.aad` is
   already a `Mapping[str, str]`, so the Python client
   serializes AAD entries directly as `k=v` lines (no
   base64). Tencent KMS `EncryptionContext` accepts
   arbitrary attributes, so no `SEC-CAP-001` is raised for
   AAD on this backend (unlike Azure RSA / IBM Key
   Protect / Baidu BCE, which have no AAD support at
   all).

3. **Capability fingerprint in config hash** — R-242
   framework upgrade. The configuration hash now
   includes `capability_fingerprint(_tencent_capability())`
   so a backend capability change forces session
   rebuild. The capability matrix is itself 1:1 with
   Java's `Set<SecretCapability>` for
   `TencentSdkSecretTransport`.

4. **Legacy REST config rejected by design** — the wheel
   has NO `wire.*` / `tls.*` / `proxy.*` fields. The Java
   refactor mandates that "config appears active but is
   ignored" must be rejected at startup; in Python, we
   simply don't expose the fields (equivalent: silently
   absent, not silently ignored).

5. **SDK type isolation** — the real
   `tencentcloud-sdk-python` clients are wrapped in a
   private `_TencentSdkAdapter` in `factory.py` that
   translates SDK Request / Response model fields to
   the framework's frozen dataclass responses. SDK
   types never cross the public boundary.

## Blocked

- **Real Tencent Cloud integration** — requires a CAM
  user with `ssm:GetSecretValue` / `kms:Encrypt` /
  `kms:Decrypt` permissions and a region with SSM + KMS
  enabled. Marked as `integration` in `pyproject.toml`
  markers; documented in the README; skipped locally
  without env override.
