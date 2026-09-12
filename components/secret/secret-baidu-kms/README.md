# atlas-richie-secret-baidu-kms

Baidu Cloud KMS-only backend for the Atlas Richie secret
platform. Implements a **2-SPI composite**
(`KeyWrappingBackend` via BCE KMS `Encrypt` / `Decrypt` +
`SecretProviderSession`); 1:1 functional parity with Java
`atlas-richie-secret-provider-baidu` (post-SDK-refactor).

## Capability matrix (mirrors Java SDK transport)

| Capability            | Baidu backend |
|-----------------------|----------------|
| `SECRET_READ`         | ❌ no Secret Store |
| `SECRET_VERSIONING`   | ❌ no Secret Store |
| `KEY_WRAP`            | ✅ KMS `Encrypt` |
| `KEY_UNWRAP`          | ✅ KMS `Decrypt` |
| `KEY_SIGN`            | ❌ no Sign operation |
| AAD on `wrap`/`unwrap`| ❌ not supported by API (SEC-CAP-001) |
| `SECRET_LIST`         | ❌ no list API |
| `SECRET_WRITE`        | ❌ no write API |
| `SECRET_DELETE`       | ❌ no delete API |

`read` / `metadata` calls raise `SEC-CAP-001` via the
framework's `assert_can_read` gate. `operations` /
`writer` / `deletable` return `None` (matches the Java
SDK transport's KMS-only contract).

## SDK approach

The `bce-python-sdk` package (v0.9.x) is the official
Baidu BCE Python SDK. One client is used:

- `baidubce.services.kms.KmsClient` — `encrypt` /
  `decrypt`

Authentication uses
`DefaultBceCredentials(access_key_id, access_key_secret)`
plus `KmsClientConfiguration(endpoint, protocol,
credentials)`.

The SDK is opt-in via the `optional-dependency [sdk]`
extra. Importing the wheel does NOT require the SDK;
`BaiduClientFactory.create_kms` raises
`SecretConfigurationException("SEC-BOOT-003", ...)` with a
hint to `pip install
'atlas-richie-secret-baidu-kms[sdk]'` if the SDK is
missing.

## SDK type isolation

The wheel defines a `runtime_checkable` Protocol:

- `KmsLike` — `encrypt(key_id, plaintext_b64) -> BaiduKmsEncryptResponse` /
  `decrypt(key_id, ciphertext) -> BaiduKmsDecryptResponse`

The real SDK client is wrapped in a private
`_BceKmsAdapter` (in `factory.py`) that translates SDK
Request / Response model fields to the framework's
frozen-dataclass responses. SDK types never cross the
public boundary.

## AAD handling

BCE KMS `EncryptRequest` / `DecryptRequest` do not
accept AAD. The framework's `require_aad_support` gate
rejects non-empty `CryptoContext.aad` with `SEC-CAP-001`
before the request is constructed (mirrors the Java
`requireNoAad` check in `BaiduSdkSecretTransport`).

## Install

```bash
pip install 'atlas-richie-secret-baidu-kms[sdk]'
```

## Quick start

```python
from atlas_richie.secret_baidu_kms import (
    AuthType,
    BaiduSecretProperties,
    BaiduSecretProviderFactory,
)
from atlas_richie.secret.crypto import CryptoContext, KeyPurpose, KeyReference

properties = BaiduSecretProperties(
    region="bj",
    kms_endpoint="http://bkm.bj.baidubce.com",
    auth_type=AuthType.ACCESS_KEY,
    access_key_id="ak-...",
    access_key_secret="sk-...",
    kms_key_bindings={"envelope": "kms-key-id-abc"},
)
factory = BaiduSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
kek = KeyReference(provider="baidu-kms-bj", key_id="envelope")
wrapped = session.wrap_key(b"data-key", kek)
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_BAIDU_`; fields cover region /
kms_endpoint / auth_type (ACCESS_KEY only) /
access_key_id / access_key_secret / kms_key_bindings /
timeouts.

## Legacy REST config rejected

The wheel does NOT accept the legacy `wire.*` / `tls.*`
/ `proxy.*` fields — those are not part of this
Provider's contract. Configuring them is silently
ignored on the Java side too (R-242 SDK refactor
mandate). Python's `BaiduSecretProperties` simply has
no such fields.

## See also

- `atlas-richie-secret-core` — framework + Protocols +
  `crypto.capability` AAD gate (R-242)
- `atlas-richie-secret-volcengine-kms` — sibling
  KMS-only 2-SPI scope backend (also no-AAD)
- `atlas-richie-secret-ibm-key-protect` — sibling
  KMS-only 2-SPI scope backend (R-247)
- `docs/acceptance/R-248-secret-baidu-kms-handoff.md`
  — design + verification
