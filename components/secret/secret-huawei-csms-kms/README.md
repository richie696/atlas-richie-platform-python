# atlas-richie-secret-huawei-csms-kms

Huawei Cloud CSMS + DEW KMS backend for the Atlas Richie
secret platform. Implements a **3-SPI composite**
(`SecretOperations` via CSMS `ShowSecretVersion` +
`KeyWrappingBackend` via DEW `EncryptData` / `DecryptData`
+ `SecretBootstrapClient` + `SecretProviderSession`); 1:1
functional parity with Java
`atlas-richie-secret-provider-huawei` (post-SDK-refactor).

## Capability matrix (mirrors Java SDK transport)

| Capability            | Huawei backend |
|-----------------------|------------------|
| `SECRET_READ`         | ✅ CSMS `ShowSecretVersion` |
| `SECRET_VERSIONING`   | ✅ CSMS `VersionMetadata.id` |
| `KEY_WRAP`            | ✅ DEW `EncryptData` |
| `KEY_UNWRAP`          | ✅ DEW `DecryptData` |
| `KEY_SIGN`            | ❌ no Sign operation |
| AAD on `unwrap_key`   | ✅ DEW `additionalAuthenticatedData` (Base64) |
| `SECRET_LIST`         | ❌ no list API |
| `SECRET_WRITE`        | ❌ read-only |
| `SECRET_DELETE`       | ❌ read-only |

## SDK approach

The `huaweicloud-sdk-python` package is the official
Huawei Cloud SDK. Two clients are used:

- `huaweicloudsdkcsms.v1.csms_client.CsmsClient` —
  `show_secret_version`
- `huaweicloudsdkkms.v2.kms_client.KmsClient` —
  `encrypt_data` / `decrypt_data`

Authentication uses `BasicCredentials(ak, sk, project_id,
security_token)` (Huawei DEW requirement: `project_id` is
mandatory).

The SDK is opt-in via the `optional-dependency [sdk]`
extra. Importing the wheel does NOT require the SDK;
`HuaweiClientFactory.create_clients` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install
'atlas-richie-secret-huawei-csms-kms[sdk]'` if the SDK is
missing.

## SDK type isolation

The wheel defines two `runtime_checkable` Protocols:

- `CsmsLike` — `show_secret_version(secret_name, version_id) -> HuaweiCsmsGetResponse`
- `KmsLike` — `encrypt_data(key_id, plain_text_b64, aad_b64) -> HuaweiKmsEncryptResponse` /
  `decrypt_data(cipher_text, aad_b64) -> HuaweiKmsDecryptResponse`

The real SDK clients are wrapped in a private
`_HuaweiSdkAdapter` (in `factory.py`) that translates
SDK Request / Response model fields to the framework's
frozen-dataclass responses. SDK types never cross the
public boundary.

## Install

```bash
pip install 'atlas-richie-secret-huawei-csms-kms[sdk]'
```

## Quick start

```python
from atlas_richie.secret_huawei_csms_kms import (
    AuthType,
    HuaweiSecretProperties,
    HuaweiSecretProviderFactory,
)

properties = HuaweiSecretProperties(
    region="cn-north-4",
    project_id="project-1",
    access_key_id="AKID...",
    access_key_secret="...",
    kms_key_bindings={"default-envelope": "key-abc-123"},
)
factory = HuaweiSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
assert session.descriptor.backend.value == "huawei"
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_HUAWEI_`; fields cover
region / project_id / secret_endpoint / kms_endpoint /
auth_type (ACCESS_KEY only) / access_key_id /
access_key_secret / security_token / secrets /
kms_key_bindings / timeouts.

## Legacy REST config rejected

The wheel does NOT accept the legacy `wire.*` / `tls.*`
/ `proxy.*` fields — those are not part of this
Provider's contract. Configuring them is silently
ignored on the Java side too (R-242 SDK refactor
mandate). Python's `HuaweiSecretProperties` simply has
no such fields.

## See also

- `atlas-richie-secret-core` — framework + Protocols +
  `crypto.capability` AAD gate (R-242)
- `atlas-richie-secret-tencent-ssm-kms` — sibling cloud
  backend wheel (similar 3-SPI scope; same SDK pattern)
- `docs/acceptance/R-244-secret-huawei-csms-kms-handoff.md`
  — design + verification
