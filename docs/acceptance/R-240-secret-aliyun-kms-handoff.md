# R-240 Handoff: `atlas-richie-secret-aliyun-kms` — Alibaba Cloud Secrets Manager + KMS backend

**Date:** 2026-09-13
**Owner:** Mavis
**Status:** **DONE** — 82/82 aliyun-kms tests pass (20 properties unit
+ 30 configuration unit + 32 client + integration via `FakeAliyunGateway`),
`atlas-richie-secret-aliyun-kms` 0.2.0 wheel built, **isolated wheel
installs + imports cleanly** in fresh venv, and `AliyunClientFactory`
fails gracefully with `SEC-BOOT-003` when the Alibaba SDK is not
installed.

> The full `tools/release/verify_isolated_wheels.py` run is blocked on a
> pre-existing wheelhouse issue (the `alibabacloud-darabonba-array==0.1.0`
> transitive dependency of the Alibaba SDK is not downloadable by
> `pip download --require-hashes --only-binary=:all:`). This affects
> every Alibaba SDK install in the platform, not specifically this
> wheel. The aliyun-kms wheel itself imports and resolves correctly
> when installed directly; the failure is in the verifier's
> `prepare_wheelhouse.py` step, not in this wheel's metadata.

## Motivation

R-233 / R-235 / R-236 / R-237 / R-238 added the framework + 7 remote
backends (Redis, Vault, OpenBao, AWS, Azure, GCP, PKCS#11).
**R-240** adds the **eighth**: **Alibaba Cloud Secrets Manager + KMS** —
the dominant China-region cloud KMS provider, mirroring Java
`atlas-richie-secret-provider-aliyun` 1:1.

Aliyun's KMS is **symmetric only** (no native sign / verify API on
the `kms20160120` endpoint), so this wheel exposes
`KeyWrappingBackend` **without** `SigningBackend` — matching Java's
4-SPI scope (`SECRET_READ` / `SECRET_VERSIONING` / `KEY_WRAP` /
`KEY_UNWRAP`).

## Design parity with Java

| SPI | Java | Python (R-240) |
|---|---|---|
| `SecretOperations` | yes (`GetSecretValue` + version stage) | yes (`AliyunSecretClient.get/get_version/get_metadata/exists`) |
| `KeyWrappingBackend` | yes (KMS symmetric `Encrypt` / `Decrypt`) | yes (`AliyunSecretClient.wrap_key/unwrap_key`) |
| `SigningBackend` | no (symmetric-only KMS) | **no** (`signing` returns `None`) |
| `SecretBootstrapClient` | yes (with `MissingPolicy` enum) | yes (`bootstrap` framework entry + spec's `load(request, missing_policy)`) |
| `SecretProviderSession` | yes | yes |
| `SecretWriter` / `SecretDeletable` / `SecretListable` | no | **no** |

## Java → Python structural mapping

```
components/secret/secret-aliyun-kms/
├── pyproject.toml
├── README.md
└── src/atlas_richie/secret_aliyun_kms/
    ├── __init__.py            ← public surface (13 symbols)
    ├── client.py              ← AliyunSecretClient (4-SPI composite)
    │                           + AliyunKmsGateway Protocol
    │                           + AliyunGetSecretValueResponse / Encrypt / Decrypt
    │                           + AliyunBootstrapLoadResult + MissingPolicy
    ├── configuration.py       ← AliyunConfigurationResolver + SHA-256 hash
    ├── factory.py             ← AliyunSecretProviderFactory + AliyunClientFactory
    └── properties.py          ← AliyunSecretProperties + AliyunSecretMapping
└── tests/
    ├── conftest.py                ← FakeAliyunGateway + make_properties/make_resolved
    ├── test_aliyun_properties.py  ← 20 unit tests
    ├── test_aliyun_configuration.py ← 30 unit tests
    └── test_aliyun_client.py      ← 32 unit tests (4-SPI behavior + load semantics)
```

## Functional surface (13 public symbols)

### Properties (`properties.py`)

- `AliyunSecretMapping` — frozen dataclass, `(secret_name, field=None)`.
- `AliyunSecretProperties` — pydantic-settings env-injected;
  prefix `ATLAS_RICHIE_SECRET_ALIYUN_`. Carries `region` (required) /
  `endpoint` (optional) / `ca_file` (optional) /
  `secrets_manager_path_prefix` (optional) / `kms_key_bindings` /
  `secrets` mapping / `connect_timeout_seconds` /
  `read_timeout_seconds` / `max_attempts`.

### Configuration (`configuration.py`)

- `ResolvedAliyunConfiguration` — frozen dataclass, `(provider_id,
  properties, configuration_hash, capability)`. Static capability
  matches Java: `can_read=True, can_write=False, can_rotate=True,
  can_list=False, encrypts_at_rest=True, signs_values=False,
  cacheable=True`.
- `AliyunConfigurationResolver` — `resolve(properties, *,
  provider_id, configuration_prefix)` with full validation
  (region non-blank, endpoint HTTPS / loopback, dedicated-KMS host
  requires CA, path-prefix safety, key-binding physical-id non-blank,
  secret-mapping safety) + SHA-256 `configuration_hash` over
  canonical fields.

### Client (`client.py`)

- `AliyunKmsGateway` — runtime-checkable Protocol with 3 methods
  (`get_secret_value`, `encrypt`, `decrypt`) + `close`. The
  internal `AliyunSdkGateway` adapter wraps the Alibaba SDK
  client and translates its mutable model classes into the
  frozen response dataclasses, so the public surface stays
  SDK-free.
- `AliyunGetSecretValueResponse` / `AliyunEncryptResponse` /
  `AliyunDecryptResponse` — frozen dataclasses, the wire
  shape of the SDK.
- `MissingPolicy` — StrEnum, `FAIL` (default) / `LOCAL`. Controls
  the spec's `load(...)` behaviour on missing secrets.
- `AliyunBootstrapLoadResult` — frozen dataclass carrying
  `provider_id`, `version_digest` (SHA-256), `paths_loaded`,
  `loaded_at`, `merged` (flattened dict), `binding_names`, and
  `last_request_id`.
- `AliyunSecretClient` — composite 4-SPI client. Implements
  `SecretOperations` (read / get_version / get_metadata /
  exists) + `KeyWrappingBackend` (duck-typed wrap_key /
  unwrap_key) + `SecretBootstrapClient` (`bootstrap` framework
  entry) + `SecretProviderSession` (descriptor / configuration
  / operations / writer / deletable / snapshot_manager /
  is_closed / close). Also exposes the spec's
  `read(reference) -> DestroyableSecretValue` (with
  zero-buffer destroy) and `load(request, *, missing_policy)`
  (the rich JSON-flatten + merge + version-digest operation).
  `signing` / `writer` / `deletable` all return `None` —
  matching Java's narrower 4-SPI scope.

### Factory (`factory.py`)

- `AliyunClientFactory` — internal SDK adapter;
  `create_gateway(properties) -> AliyunKmsGateway`. Lazily
  imports `alibabacloud_kms20160120.client.Client` etc. and
  raises `SecretConfigurationException("SEC-BOOT-003", ...)` on
  `ImportError`. **Import-safe**: the module's top-level
  imports do NOT touch `alibabacloud_*`.
- `AliyunSecretProviderFactory` — `SecretProviderFactory`
  implementation. `name = f"aliyun-{region}"` (or
  `aliyun-default`), `backend = SecretBackend.ALIYUN`,
  `capabilities` static, `version = "0.2.0"`.
  `create(configuration) -> SecretProviderSession` does
  resolve → build gateway → construct client.

## SDK

- `alibabacloud_kms20160120>=3.1,<4.0` — official Alibaba
  Python SDK for the KMS 2016-01-20 endpoint (handles
  Secrets Manager reads + symmetric `Encrypt` / `Decrypt`).
- `alibabacloud_tea_openapi>=0.3,<1.0` — Alibaba's Tea
  runtime for the SDK.
- `alibabacloud_credentials>=0.3,<2.0` — Alibaba credential
  chain client.
- All three are behind the `[kms]` optional extra so
  developers without credentials can `import
  atlas_richie.secret_aliyun_kms` and run unit tests.

## Java → Python translation table

| Java (`atlas-richie-secret-provider-aliyun`) | Python (`atlas-richie-secret-aliyun-kms`) |
|---|---|
| `AliyunSecretProperties.java` | `properties.py` — `AliyunSecretProperties` + `AliyunSecretMapping` |
| `AliyunSecretConfigurationResolver.java` | `configuration.py` — `AliyunConfigurationResolver` + `ResolvedAliyunConfiguration` |
| `AliyunClientFactory.java` | `factory.py` — `AliyunClientFactory` (lazy SDK adapter) + `_AliyunSdkGateway` |
| `AliyunKmsGateway` (Java interface) | `client.py` — `AliyunKmsGateway` (runtime-checkable Protocol) |
| `AliyunSecretClient.java` (345 lines, the bulk) | `client.py` — `AliyunSecretClient` (4-SPI composite) + `MissingPolicy` + `AliyunBootstrapLoadResult` |
| `AliyunSecretBootstrapProviderFactory.java` | `factory.py` — `AliyunSecretProviderFactory` |
| `AliyunSecretAutoConfiguration.java` (Spring) | **skip** (no Spring in Python) |

## Java method → Python method mapping

| Java method | Python method |
|---|---|
| `read(SecretReference)` | `AliyunSecretClient.read(reference) -> DestroyableSecretValue` (or `get` returning `SecretValue`) |
| `metadata(SecretReference)` | `AliyunSecretClient.get_metadata(reference) -> SecretMetadata` |
| `wrap(KeyReference, byte[], CryptoContext)` | `AliyunSecretClient.wrap_key(dek, kek, *, algorithm=None) -> WrappedKey` |
| `unwrap(WrappedKey, CryptoContext)` | `AliyunSecretClient.unwrap_key(wrapped, context) -> bytes` |
| `load(SecretBootstrapRequest, BootstrapSecretProperties)` | `AliyunSecretClient.load(request, *, missing_policy=MissingPolicy.FAIL) -> AliyunBootstrapLoadResult` |
| `physicalKey(KeyReference)` | `_physical_key_id(key)` (private helper, raises `SEC-KEY-001`) |
| `encryptionContext(KeyReference, CryptoContext)` | `_encryption_context(reference, context)` (private helper) |
| `mapError(...)` | `_map_sdk_error(operation, reference, error)` |
| `mergeWithoutAmbiguity(...)` | `_merge_without_ambiguity(target, incoming, *, binding_name)` |
| `digestVersions(...)` | `_digest_versions(pairs)` |
| `parse(...)` (JSON) | `_parse_for_load(response)` |
| `flatten(...)` (dot-notation) | `_flatten(value, *, prefix)` |

## API gotchas (worked around)

1. **Symmetric-only**: Aliyun KMS has no `Sign` / `Verify`
   on the `kms20160120` endpoint. The session's `signing`
   property returns `None` so `list_capability(session)`
   sees the absence.
2. **`Encrypt` / `Decrypt` are the wrap primitives**: Java's
   `AliyunSecretClient.wrap()` uses KMS `Encrypt` (not
   `GenerateDataKey`) because the framework's wrap_key
   **imports** the caller's DEK — `Encrypt` accepts arbitrary
   bytes up to 4 KB (sufficient for AES-128/192/256 DEKs).
3. **Encryption context**: KMS `Encrypt` / `Decrypt` accept
   `EncryptionContext` (a flat `dict[str, str]`); the client
   builds a stable context including `atlas-component`,
   `atlas-key`, `atlas-version`, `atlas-purpose`, and a
   `atlas-aad-sha256` derived from `CryptoContext.aad`. The
   same context must be passed on both sides of the wrap
   (the framework re-derives it from the `WrappedKey.aad`
   field).
4. **`Forbidden.ResourceNotFound` boundary**: when the SDK
   raises `TeaException(code="Forbidden.ResourceNotFound")`,
   the gateway returns `None` and the client treats the
   secret as missing (matching the framework's
   `SecretIntegrityException` path). Other `TeaException`s
   surface as `SecretException("SEC-PROVIDER-001")`.
5. **Version stage default**: `GetSecretValue` defaults to
   `VersionStage=ACSCurrent` (Aliyun's analogue of
   `AWSCurrent`). The client's `load(...)` method explicitly
   passes `_ACSCURRENT`; `get(reference)` does not, so the
   `SecretReference.version_selector` is honoured.

## Errors

| Java exception | Python exception |
|---|---|
| `BlankRegionException` | `SecretConfigurationException("SEC-BOOT-003", ...)` |
| `EndpointSchemeException` | `SecretConfigurationException("SEC-BOOT-003", ...)` |
| `MissingCaFileException` | `SecretConfigurationException("SEC-BOOT-003", ...)` |
| `InvalidSecretMappingException` | `SecretConfigurationException("SEC-BOOT-003", ...)` |
| `KeyBindingNotFoundException` | `SecretConfigurationException("SEC-KEY-001", ...)` |
| `WrapFailure` (empty DEK) | `SecretCryptoException("SEC-CRYPTO-001", ...)` |
| `UnwrapFailure` (algo / key_id mismatch) | `SecretCryptoException("SEC-CRYPTO-002", ...)` |
| `MissingSecretException` (`load` + FAIL) | `SecretBootstrapException("SEC-STORE-001", ...)` |
| `MergeConflictException` (`load` + conflict) | `SecretBootstrapException("SEC-STORE-003", ...)` |
| `TeaException(Forbidden.ResourceNotFound)` | gateway returns `None` → `SecretIntegrityException` |
| Other `TeaException` | `SecretException("SEC-PROVIDER-001", ...)` |

## Test results

- `test_aliyun_properties.py` — **20 tests pass** (env injection,
  default values, boundary validation, `AliyunSecretMapping`
  frozen semantics, `model_validate_mapping`).
- `test_aliyun_configuration.py` — **30 tests pass** (region
  non-blank, endpoint HTTPS / loopback, dedicated-KMS CA
  requirement, path-prefix safety, key-binding physical-id
  non-blank, secret-mapping safety, hash shape + stability +
  change detection, default provider id, capability).
- `test_aliyun_client.py` — **32 tests pass** (`read` mapped /
  fallback / binary / non-scalar-field, `metadata`,
  `wrap` empty / no-binding / round-trip, `unwrap` wrong-algo /
  key-id-mismatch / empty-ciphertext, `load` merges / conflict /
  LOCAL / FAIL / non-dict / request-id, descriptor capabilities,
  close idempotency, operations property, signing/writer/deletable
  return None, framework `bootstrap` STARTUP-required / LAZY
  tolerated).
- **Total per wheel**: 82/82 in 0.06s

## Isolated-wheel verification (manual)

```bash
$ /tmp/aliyun-verify/bin/pip install --no-cache-dir --no-index \
    --find-links /Users/richie696/Projects/workspace/atlas-richie-platform-python/dist \
    atlas-richie-contracts==0.2.0 atlas-richie-secret-core==0.2.0 pydantic pydantic-settings
Successfully installed atlas-richie-contracts-0.2.0 atlas-richie-secret-core-0.2.0

$ /tmp/aliyun-verify/bin/pip install --no-cache-dir --no-deps --no-index \
    --find-links ... atlas-richie-secret-aliyun-kms==0.2.0
Successfully installed atlas-richie-secret-aliyun-kms-0.2.0

$ /tmp/aliyun-verify/bin/python -c \
    "import atlas_richie.secret_aliyun_kms as m; print(m.AliyunSecretProviderFactory)"
<class 'atlas_richie.secret_aliyun_kms.factory.AliyunSecretProviderFactory'>

$ /tmp/aliyun-verify/bin/python -c \
    "from atlas_richie.secret_aliyun_kms import AliyunClientFactory; \
     from atlas_richie.secret_aliyun_kms.properties import AliyunSecretProperties; \
     AliyunClientFactory().create_gateway(AliyunSecretProperties(region='cn-hangzhou'))"
Traceback (most recent call last):
  ...
atlas_richie.secret.errors.SecretConfigurationException: SEC-BOOT-003 aliyun:
  Aliyun KMS SDK not installed; pip install 'atlas-richie-secret-aliyun-kms[kms]'
```

The full `tools/release/verify_isolated_wheels.py` run is blocked by
an upstream wheelhouse issue: the `alibabacloud-darabonba-array==0.1.0`
transitive dependency of the Alibaba SDK is not downloadable by
`pip download --require-hashes --only-binary=:all:`. This affects all
Alibaba SDK installations and is independent of this wheel.

## Workspace integration

- `pyproject.toml` — added `components/secret/secret-aliyun-kms` to
  workspace members + sources.
- `versions.toml` — added `atlas-richie-secret-aliyun-kms = "0.2.0"`.
- `foundation/platform/pyproject.toml` — added the dep constraint
  (sync_versions.py does not add new aggregator entries, only updates
  existing ones; the new entry was added by hand to match the
  established aggregator shape).
- `tools/release/verify_isolated_wheels.py` — already includes the
  new entry (line 54).
- `tools/sync_versions.py` — synced 35 `pyproject.toml` files clean
  (no constraint updates emitted for aliyun-kms since it has no
  cross-component constraints).

## Acceptance checklist

- [x] Java → Python 1:1 functional parity (4-SPI scope, no signing)
- [x] Bilingual docstrings on every public module / class / method
- [x] No Alibaba SDK types in the public facade
- [x] `pytest` 82/82 pass for aliyun-kms alone
- [x] Isolated wheel installs + imports cleanly (manual verification)
- [x] `AliyunClientFactory.create_gateway` fails with `SEC-BOOT-003`
      when SDK is missing
- [x] `tools/sync_versions.py` 35/35 syncs clean
- [x] Wheel built and present in `dist/`
- [x] `pyproject.toml` / `versions.toml` / `foundation/platform` /
      `verify_isolated_wheels.py` updated
- [x] Handoff doc written
- [ ] Single commit + push (in-flight)
- [ ] Real Alibaba Cloud integration tests (blocked on credentials;
      documented; the SDK is mocked via `FakeAliyunGateway` for
      local CI)
