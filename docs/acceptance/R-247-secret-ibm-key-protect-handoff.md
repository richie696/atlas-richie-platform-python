# R-247: atlas-richie-secret-ibm-key-protect — handoff

## Status

**Done.** 1:1 functional parity with Java
`atlas-richie-secret-provider-ibm-key-protect` (post-SDK-refactor:
2 main files) translated into a single Python wheel with
4 source files. **KMS-only** (no Secret Store).

## Notable constraint: no official Python SDK on PyPI

Unlike Tencent / Huawei / OCI / Baidu, **IBM Cloud Key
Protect has no official Python SDK on PyPI**. The
`com.ibm.cloud:ibm-key-protect-sdk` Java artifact has
no PyPI counterpart under any of the searched names
(`ibm-key-protect`, `ibm-cloud-key-protect`,
`ibm-key-protect-sdk`, `ibm_key_protect_sdk`,
`ibmcloud-key-protect`, etc. — all 404).

The Python wheel therefore uses a thin REST adapter:

- `ibm-cloud-sdk-core` (opt-in `[sdk]` extra) for the
  `BearerTokenAuthenticator` class, which is **probed at
  init time** only (to verify the IBM IAM token is
  well-formed and the SDK is installed). The actual
  request pipeline uses `httpx`.
- `httpx` (hard dependency) for the HTTP client. A small
  `_BearerTokenHttpxAuth` class wraps the
  `BearerTokenAuthenticator`'s token into
  `httpx.Auth`.

REST endpoints (Key Protect API v2):
- `POST /api/v2/keys/{key_id}/wrap` with body
  `{"plaintext": "<base64>"}` → `{"ciphertext": "..."}`
- `POST /api/v2/keys/{key_id}/unwrap` with body
  `{"ciphertext": "<base64>"}` → `{"plaintext": "..."}`

Headers:
- `bluemix-instance: <instance_id>` — Key Protect instance GUID
- `x-kms-key-ring: <key_ring>` — key ring name
- `Authorization: Bearer <token>` — IBM IAM access token

This design deliberately keeps the SDK adapter contained
in `factory.py` (the `KmsLike` Protocol in `client.py`
sees only the framework's frozen-dataclass responses),
so a future swap to an actual IBM Python SDK (or to
`boto3`-style signing) is a 1-file change.

## Public symbol list

### `properties.py` (2)
- `AuthType` — StrEnum (`BEARER_TOKEN` only)
- `IbmKeyProtectProperties` — pydantic-settings, env_prefix
  `ATLAS_RICHIE_SECRET_IBM_KP_`

### `configuration.py` (2)
- `ResolvedIbmKeyProtectConfiguration` — frozen dataclass
- `IbmKeyProtectConfigurationResolver` — endpoint / auth
  / instance_id / kms_key_bindings validation, SHA-256
  hash (capability fingerprint included, R-242)

### `client.py` (5)
- `IbmKeyProtectWrapResponse` /
  `IbmKeyProtectUnwrapResponse` — frozen dataclasses
- `WrapOperation` — StrEnum (wrap / unwrap marker)
- `KmsLike` — `runtime_checkable` Protocol (2 methods)
- `IbmKeyProtectSecretClient` — 2-SPI composite
  (`KeyWrappingBackend` + `SecretProviderSession` only;
  `operations` / `writer` / `deletable` return `None`,
  `read` / `metadata` raise `SEC-CAP-001` via
  `assert_can_read`)

### `factory.py` (2)
- `IbmKeyProtectClientFactory` — `KmsLike` builder
  (REST adapter + Bearer token auth)
- `IbmKeyProtectSecretProviderFactory` — framework entry

**Total: 11 public symbols** (matches Java 2-file module
public surface).

## Test count

**38 tests, 38 passed** in 0.14s.

- `test_ibm_key_protect_client.py` — 19 tests
  (descriptor / operations None / writer & deletable None
  / configuration hash / read raises SEC-CAP-001 /
  metadata raises SEC-CAP-001 / wrap then unwrap / empty
  DEK / wrong algorithm / empty ciphertext / missing key
  binding / AAD raises SEC-CAP-001 / close idempotent /
  read after close / configuration property / factory
  descriptor / factory create with fake)
- `test_ibm_key_protect_configuration.py` — 19 tests
  (region / instance_id required / blank region / blank
  instance_id / key_ring default / https endpoint / http
  non-loopback rejected / http loopback allowed / bearer
  token required / bearer token blank rejected / blank
  logical / blank physical / hash 64 hex / hash changes
  with region / hash changes with instance_id / hash
  changes with keys / hash stable / hash includes
  capability fingerprint / capability KMS-only / resolved
  contains provider id)

## SDK approach (REST + Bearer token)

The wheel is import-safe without the SDK. If a user
opts out of `[sdk]`, the wheel can still be imported
(Properties / Configuration / KmsLike / Response
dataclasses are all SDK-free). The first call to
`IbmKeyProtectClientFactory.create_kms` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with
a hint to `pip install
'atlas-richie-secret-ibm-key-protect[sdk]'` if
`ibm-cloud-sdk-core` is missing.

## Test approach — in-process fake KMS

Tests use `FakeKms` (in-process, real object, not
MagicMock). The fake uses a pass-through round-trip
(`wrap` stores `plaintext_b64` as ciphertext, `unwrap`
returns the same value); this matches the symmetric
nature of the IBM Key Protect KMS API for the purposes
of smoke testing. The fake also records the last call
so tests can verify the wire payload.

## Java → Python translation table

| Java | Python |
|---|---|
| `IbmKeyProtectProperties.java` (SDK-refactor version) | `IbmKeyProtectProperties` (pydantic-settings) |
| `IbmKeyProtectSdkSecretTransport.java` (KMS-only, ~85 lines, uses `IbmKeyProtectApi` SDK) | `IbmKeyProtectSecretClient` + `KmsLike` Protocol + REST adapter in `factory.py` (since no Python SDK exists) |
| `IBMKeyProtectSecretBootstrapProviderFactory.java` (~10 lines post-refactor) | `IbmKeyProtectSecretProviderFactory` (framework entry) |
| `IbmKeyProtectSdkSecretTransportTest.java` | `test_ibm_key_protect_client.py` |

## Notable adaptations (Pythonic 1:1)

1. **No official Python SDK on PyPI** — the Java side
   uses `com.ibm.cloud:ibm-key-protect-sdk`. We
   translated this to `httpx` + `ibm-cloud-sdk-core`'s
   `BearerTokenAuthenticator` (used only for token
   validation, the request pipeline is custom). This
   divergence is forced by PyPI; the wire protocol
   matches the Java SDK exactly.

2. **`AuthType.BEARER_TOKEN` only** — matches Java's
   `RemoteProviderProperties.AuthenticationType.BEARER_TOKEN`.
   ACCESS_KEY / API_KEY are rejected (`SEC-BOOT-003`)
   because IBM Key Protect REST API uses IAM bearer
   tokens, not AWS-style access keys.

3. **`tenant-id` → `instance_id`** — Java uses
   `tenant-id` (a Key Protect term), but in the IBM
   Cloud console it's labeled "Instance ID" and is
   commonly referred to as `instance_id`. We use
   `instance_id` for consistency with the IBM Cloud
   docs; both names refer to the same GUID.

4. **`requireNoAad` → framework gate** — Java
   `IbmKeyProtectSdkSecretTransport.requireNoAad`
   raises `SEC-CAP-001` if `context.attributes()` is
   non-empty or `context.associatedData()` is non-empty.
   The Python client uses the framework's
   `require_aad_support(capability, context=ctx,
   backend_label=...)` gate, which provides the same
   error category (SEC-CAP-001) and the same trigger
   condition.

5. **NotFound boundary** — N/A (KMS-only; the framework
   never calls `read` on an IBM Key Protect session
   because `client.operations` returns `None`).

6. **Capability fingerprint in config hash** — R-242
   framework upgrade. KMS-only capability means a
   capability change (e.g. if IBM later adds a Secret
   Store API) would force a session rebuild via the
   configuration hash change.

## Blocked

- **Real IBM Key Protect integration** — requires an IBM
  Cloud account with a Key Protect instance, an IAM
  access token, and `wrap` / `unwrap` IAM permissions.
  Marked as `integration` in `pyproject.toml` markers;
  documented in the README; skipped locally without
  env override.
