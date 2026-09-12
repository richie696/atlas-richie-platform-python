# atlas-richie-secret-volcengine-kms

Volcengine KMS-only backend for the Atlas Richie secret
platform. Implements a **2-SPI composite**
(`KeyWrappingBackend` via KMS `Encrypt` / `Decrypt` +
`SecretProviderSession`); 1:1 functional parity with Java
`atlas-richie-secret-provider-volcengine` (post-SDK-refactor).

## Capability matrix (mirrors Java SDK transport)

| Capability            | Volcengine backend |
|-----------------------|---------------------|
| `SECRET_READ`         | ❌ no Secret Store |
| `SECRET_VERSIONING`   | ❌ no Secret Store |
| `KEY_WRAP`            | ✅ KMS `Encrypt` |
| `KEY_UNWRAP`          | ✅ KMS `Decrypt` |
| `KEY_SIGN`            | ❌ no Sign operation |
| AAD on `unwrap_key`   | ✅ `encryptionContext` attributes |
| `SECRET_LIST`         | ❌ no list API |
| `SECRET_WRITE`        | ❌ no write API |
| `SECRET_DELETE`       | ❌ no delete API |

`read` / `metadata` calls raise `SEC-CAP-001` via the
framework's `assert_can_read` gate. `writer` / `deletable`
return `None` (matches the Java SDK transport's read-only
+ KMS-only contract).

## SDK approach

The `volcengine-python-sdk` package is the official
Volcengine SDK. One client is used:

- `volcengine.kms.KmsApi.KmsApi` — `encrypt` / `decrypt`

Authentication uses `StaticCredentialProvider(ak, sk,
security_token)`.

The SDK is opt-in via the `optional-dependency [sdk]`
extra. Importing the wheel does NOT require the SDK;
`VolcengineClientFactory.create_kms` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install
'atlas-richie-secret-volcengine-kms[sdk]'` if the SDK is
missing.

## SDK type isolation

The wheel defines a `runtime_checkable` Protocol:

- `KmsLike` — `encrypt(keyring_name, key_name, plaintext_b64, encryption_context) -> VolcengineKmsEncryptResponse` /
  `decrypt(ciphertext_blob, encryption_context) -> VolcengineKmsDecryptResponse`

The real SDK client is wrapped in a private
`_VolcengineSdkAdapter` (in `factory.py`) that translates
SDK Request / Response model fields to the framework's
frozen-dataclass responses. SDK types never cross the
public boundary.

## Install

```bash
pip install 'atlas-richie-secret-volcengine-kms[sdk]'
```

## Quick start

```python
from atlas_richie.secret_volcengine_kms import (
    AuthType,
    VolcengineSecretProperties,
    VolcengineSecretProviderFactory,
)

properties = VolcengineSecretProperties(
    region="cn-beijing",
    namespace="atlas-orders",
    access_key_id="AKID...",
    access_key_secret="...",
    kms_key_bindings={"default-envelope": "key-abc-123"},
)
factory = VolcengineSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
assert session.descriptor.backend.value == "volcengine"
# `read` would raise `SEC-CAP-001` because Volcengine is KMS-only.
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_VOLCENGINE_`; fields cover
region / kms_endpoint / namespace / auth_type
(ACCESS_KEY only) / access_key_id / access_key_secret /
security_token / kms_key_bindings / timeouts.

## Legacy REST config rejected

The wheel does NOT accept the legacy `wire.*` / `tls.*`
/ `proxy.*` fields — those are not part of this
Provider's contract. Configuring them is silently
ignored on the Java side too (R-242 SDK refactor
mandate). Python's `VolcengineSecretProperties` simply
has no such fields.

## See also

- `atlas-richie-secret-core` — framework + Protocols +
  `crypto.capability` AAD gate (R-242)
- `atlas-richie-secret-pkcs11` — sibling 2-SPI scope
  backend (also KMS-only)
- `docs/acceptance/R-245-secret-volcengine-kms-handoff.md`
  — design + verification
