# atlas-richie-secret-tencent-ssm-kms

Tencent Cloud SSM + KMS backend for the Atlas Richie
secret platform. Implements a **3-SPI composite**
(`SecretOperations` via SSM `GetSecretValue` +
`KeyWrappingBackend` via KMS `Encrypt` / `Decrypt` +
`SecretBootstrapClient` + `SecretProviderSession`); 1:1
functional parity with Java
`atlas-richie-secret-provider-tencent` (post-SDK-refactor).

## Capability matrix (mirrors Java SDK transport)

| Capability            | Tencent backend |
|-----------------------|------------------|
| `SECRET_READ`         | ✅ SSM `GetSecretValue` |
| `SECRET_VERSIONING`   | ✅ SSM `VersionId` |
| `KEY_WRAP`            | ✅ KMS `Encrypt` |
| `KEY_UNWRAP`          | ✅ KMS `Decrypt` |
| `KEY_SIGN`            | ❌ no Sign operation |
| AAD on `unwrap_key`   | ❌ `SEC-CAP-001` (Tencent KMS `EncryptionContext` accepts attributes only) |
| `SECRET_LIST`         | ❌ no list API |
| `SECRET_WRITE`        | ❌ read-only |
| `SECRET_DELETE`       | ❌ read-only |

## SDK approach

The `tencentcloud-sdk-python` package is the official
Tencent Cloud SDK (TC3 signing built in). It is the
**only** way this wheel calls Tencent Cloud APIs. Two
clients are used:

- `tencentcloud-sdk-python-ssm` — `SsmClient.GetSecretValue`
- `tencentcloud-sdk-python-kms` — `KmsClient.Encrypt` /
  `Decrypt`

The SDK is opt-in via the `optional-dependency [sdk]`
extra. Importing the wheel does NOT require the SDK;
`TencentClientFactory.create_clients` raises
`SecretConfigurationException("SEC-BOOT-003", ...)`
with a hint to `pip install
'atlas-richie-secret-tencent-ssm-kms[sdk]'` if the SDK
is missing.

## SDK type isolation

The wheel defines two `runtime_checkable` Protocols:

- `SsmLike` — `get_secret_value(secret_name, version_id) -> TencentSsmGetResponse`
- `KmsLike` — `encrypt(key_id, plaintext_b64, encryption_context) -> TencentKmsEncryptResponse` /
  `decrypt(ciphertext_blob, encryption_context) -> TencentKmsDecryptResponse`

The real SDK clients are wrapped in a private
`_TencentSdkAdapter` (in `factory.py`) that translates
SDK Request / Response model fields to the framework's
frozen-dataclass responses. SDK types never cross the
public boundary.

## Install

```bash
pip install 'atlas-richie-secret-tencent-ssm-kms[sdk]'
```

## Quick start

```python
from atlas_richie.secret_tencent_ssm_kms import (
    AuthType,
    TencentSecretProperties,
    TencentSecretProviderFactory,
)

properties = TencentSecretProperties(
    region="ap-guangzhou",
    access_key_id="AKID...",
    access_key_secret="...",
    kms_key_bindings={"default-envelope": "alias/orders"},
)
factory = TencentSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
assert session.descriptor.backend.value == "tencent"
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_TENCENT_`; fields cover
region / secret_endpoint / kms_endpoint / auth_type
(ACCESS_KEY only) / access_key_id / access_key_secret /
security_token / secrets / kms_key_bindings / timeouts.

## Legacy REST config rejected

The wheel does NOT accept the legacy `wire.*` / `tls.*`
/ `proxy.*` fields — those are not part of this
Provider's contract. Configuring them is silently
ignored on the Java side too (R-242 SDK refactor
mandate: "config appears active but is ignored" is
rejected at startup). Python's `TencentSecretProperties`
simply has no such fields.

## See also

- `atlas-richie-secret-core` — framework + Protocols +
  `crypto.capability` AAD gate (R-242)
- `atlas-richie-secret-aws-kms` — sibling cloud backend
  wheel (similar 3-SPI scope)
- `docs/acceptance/R-243-secret-tencent-ssm-kms-handoff.md`
  — design + verification
