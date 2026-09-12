# R-240: atlas-richie-secret-aliyun-kms — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-aliyun` (7 files, 676 LOC)
collapsed into a single Python wheel with 4 source files.

## Public symbol list

### `properties.py` (2)
- `AliyunSecretMapping` — frozen dataclass (logical → physical
  secret name + optional field)
- `AliyunSecretProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_ALIYUN_`

### `configuration.py` (2)
- `ResolvedAliyunConfiguration` — frozen dataclass (provider_id,
  properties, configuration_hash, capability)
- `AliyunConfigurationResolver` — path safety + endpoint +
  binding + mapping validation, SHA-256 configuration hash

### `client.py` (5)
- `AliyunGetSecretValueResponse` / `AliyunEncryptResponse` /
  `AliyunDecryptResponse` — frozen dataclasses (SDK-isolating layer)
- `AliyunKmsGateway` — runtime_checkable Protocol
  (3 methods: `get_secret_value` / `encrypt` / `decrypt` + `close`)
- `AliyunSecretClient` — 4-SPI composite (SecretOperations +
  KeyWrappingBackend + SecretBootstrapClient +
  SecretProviderSession)

### `factory.py` (2)
- `AliyunClientFactory` — internal class (SDK-isolating adapter
  + lazy import; raises `SecretConfigurationException` if the
  `alibabacloud_kms20160120` SDK is not installed)
- `AliyunSecretProviderFactory` — `SecretProviderFactory`
  framework entry point

**Total: 11 public symbols** (matches the 4-SPI scope of the
Java 7-file module).

## Test count

56 tests, **56 passed** in 0.06s.

- `test_aliyun_properties.py` — 12 tests (env injection,
  field validation, key binding / secret mapping rules)
- `test_aliyun_configuration.py` — 24 tests (endpoint
  validation, dedicated endpoint + ca_file enforcement,
  path prefix safety, configuration_hash stability)
- `test_aliyun_client.py` — 20 tests (read / metadata /
  wrap / unwrap round-trip / bootstrap missing policy /
  descriptor / close / not-found mapping)

## SDK approach

The Alibaba Cloud SDK has **no local emulator**. Two-tier strategy:

1. **Unit tests** use `FakeAliyunGateway` (in-process, real
   object — not MagicMock). The fake stores secrets in a dict,
   reverses a `cipher:` prefix on decrypt for round-trip
   verification, and lets the full 4-SPI data path be exercised
   without a network call.
2. **Real SDK** is gated behind the `optional-dependency [kms]`
   extra (`alibabacloud_kms20160120` + `alibabacloud_tea_openapi`
   + `alibabacloud_credentials`). Importing the wheel does NOT
   require the SDK; `AliyunClientFactory.create_gateway` raises
   `SecretConfigurationException("SEC-BOOT-003", ...)` with a
   hint to `pip install 'atlas-richie-secret-aliyun-kms[kms]'`
   if the SDK is missing.

## Isolated wheel verification

`python3.12 tools/release/verify_isolated_wheels.py` — **all
19 wheels pass** (added `atlas-richie-secret-aliyun-kms` to
the PACKAGES list at `tools/release/verify_isolated_wheels.py:51`).
The wheel installs cleanly into a fresh venv, imports
`atlas_richie.secret_aliyun_kms`, and resolves all internal
framework dependencies.

## Java → Python translation table

| Java | Python |
|---|---|
| `AliyunSecretProperties` (62 lines, Spring `@ConfigurationProperties`) | `AliyunSecretProperties` (pydantic-settings, env injection) |
| `AliyunSecretConfigurationResolver` (112 lines) | `AliyunConfigurationResolver` (path safety + SHA-256 hash) |
| `AliyunSecretClient` (345 lines, 4-SPI composite) | `AliyunSecretClient` (4-SPI composite, framework `SecretReference` shape) |
| `AliyunKmsGateway` (interface, 3 methods) | `AliyunKmsGateway` (runtime_checkable Protocol) |
| `AliyunClientFactory` (73 lines, SDK adapter) | `AliyunClientFactory` (lazy SDK import, frozen-dataclass response adapter) |
| `AliyunSecretBootstrapProviderFactory` (26 lines) | `AliyunSecretProviderFactory` (framework entry) |
| `AliyunSecretAutoConfiguration` (42 lines, Spring `@AutoConfiguration`) | (N/A — Spring-specific) |

## Notable adaptations (Pythonic 1:1)

1. **Logical → physical address resolution** — Java bootstrap
   takes `logicalPaths()` and resolves via `properties.secrets`;
   Python framework already resolves in the
   `SecretBindingCatalog`, so `SecretReference.path` is the
   physical name. `properties.secrets` is preserved as an
   optional override but the client uses `reference.path` as
   the default physical name.

2. **JSON field extraction** — Java `SecretMapping` has a
   `field` attribute. The framework's `SecretReference` does
   not, so the Aliyun client uses a `<path>#<field>`
   convention: `path = "company/db#password"` extracts the
   `password` field from the JSON body.

3. **Not-found mapping** — Java checks
   `SECRET_NOT_FOUND_CODES.contains(exception.getCode().trim())`
   for the literal `Forbidden.ResourceNotFound`. Python
   mirrors this by inspecting both `.code` and `str(error)`
   on any caught exception (the Alibaba SDK's `TeaException`
   does not inherit from `SecretException`).

4. **Key reference** — Java passes
   `physicalKey(KeyReference)` to look up a logical key in
   `kms_key_bindings`. Python's framework `KeyReference`
   already carries `key_id` directly, so the client takes
   `kek.key_id` and only raises `SEC-KEY-001` when it's blank.

## Blocked

- **Real-cloud integration tests** — require a RAM user with
  `kms:Encrypt` / `kms:Decrypt` / `secretsmanager:GetSecretValue`
  permissions and a region with KMS enabled. Marked as
  `integration` in `pyproject.toml` markers; documented in
  the README; skipped locally with no env override.
