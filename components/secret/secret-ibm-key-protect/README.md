# atlas-richie-secret-ibm-key-protect

IBM Cloud Key Protect KMS-only backend for the Atlas
Richie secret platform. Implements a **2-SPI composite**
(`KeyWrappingBackend` via Key Protect `wrap` / `unwrap` +
`SecretProviderSession`); 1:1 functional parity with Java
`atlas-richie-secret-provider-ibm-key-protect`
(post-SDK-refactor).

## Capability matrix (mirrors Java SDK transport)

| Capability            | IBM Key Protect backend |
|-----------------------|--------------------------|
| `SECRET_READ`         | ❌ no Secret Store |
| `SECRET_VERSIONING`   | ❌ no Secret Store |
| `KEY_WRAP`            | ✅ Key Protect `wrap` |
| `KEY_UNWRAP`          | ✅ Key Protect `unwrap` |
| `KEY_SIGN`            | ❌ no Sign operation |
| AAD on `wrap`/`unwrap`| ❌ not supported by API (SEC-CAP-001) |
| `SECRET_LIST`         | ❌ no list API |
| `SECRET_WRITE`        | ❌ no write API |
| `SECRET_DELETE`       | ❌ no delete API |

`read` / `metadata` calls raise `SEC-CAP-001` via the
framework's `assert_can_read` gate. `operations` /
`writer` / `deletable` return `None` (matches the Java
SDK transport's KMS-only contract).

## SDK approach — no official Python SDK

**IBM Cloud Key Protect has no official Python SDK on
PyPI.** This wheel uses two libraries to build an
SDK-equivalent adapter:

- `ibm-cloud-sdk-core` — only for the
  `BearerTokenAuthenticator` class, which we probe at
  init time to verify the IBM IAM token is well-formed.
  We do NOT use its request pipeline.
- `httpx` — the actual HTTP client. Each request gets the
  `Authorization: Bearer <token>` header attached by a
  thin `httpx.Auth` wrapper around
  `BearerTokenAuthenticator`'s token.

REST endpoints (Key Protect API v2):
- `POST /api/v2/keys/{key_id}/wrap` with body
  `{"plaintext": "<base64>"}` → `{"ciphertext": "..."}`
- `POST /api/v2/keys/{key_id}/unwrap` with body
  `{"ciphertext": "<base64>"}` → `{"plaintext": "..."}`

Headers:
- `bluemix-instance: <instance_id>` — Key Protect instance GUID
- `x-kms-key-ring: <key_ring>` — key ring name

`ibm-cloud-sdk-core` is opt-in via `optional-dependency
[sdk]`. `httpx` is a hard dependency (the wheel cannot
work without it).

## SDK type isolation

The wheel defines a `runtime_checkable` Protocol:

- `KmsLike` — `wrap(key_id, plaintext_b64) -> IbmKeyProtectWrapResponse` /
  `unwrap(key_id, ciphertext) -> IbmKeyProtectUnwrapResponse`

The real `httpx.Client` is wrapped in a private
`_IbmKeyProtectKmsAdapter` (in `factory.py`) that
translates HTTP responses to the framework's
frozen-dataclass responses. SDK / HTTP types never cross
the public boundary.

## AAD handling

IBM Key Protect's `wrap` / `unwrap` API does not accept
AAD. The framework's `require_aad_support` gate rejects
non-empty `CryptoContext.aad` with `SEC-CAP-001` before
the request is constructed (mirrors the Java
`requireNoAad` check in `IbmKeyProtectSdkSecretTransport`).

## Install

```bash
pip install 'atlas-richie-secret-ibm-key-protect[sdk]'
```

## Quick start

```python
from atlas_richie.secret_ibm_key_protect import (
    AuthType,
    IbmKeyProtectProperties,
    IbmKeyProtectSecretProviderFactory,
)
from atlas_richie.secret.crypto import CryptoContext, KeyPurpose, KeyReference

properties = IbmKeyProtectProperties(
    region="us-south",
    instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    key_ring="default",
    auth_type=AuthType.BEARER_TOKEN,
    bearer_token="...",  # IBM IAM access token
    kms_endpoint="https://us-south.kms.cloud.ibm.com",
    kms_key_bindings={"envelope": "crn:v1:bluemix:public:kms:..."},
)
factory = IbmKeyProtectSecretProviderFactory(properties)
session = factory.create(factory.default_configuration())
kek = KeyReference(provider="ibm-key-protect-us-south", key_id="envelope")
wrapped = session.wrap_key(b"data-key", kek)
session.close()
```

## Environment

Prefix `ATLAS_RICHIE_SECRET_IBM_KP_`; fields cover
region / instance_id / key_ring / auth_type /
bearer_token / kms_endpoint / kms_key_bindings /
timeouts.

## Legacy REST config rejected

The wheel does NOT accept the legacy `wire.*` / `tls.*`
/ `proxy.*` fields — those are not part of this
Provider's contract. Configuring them is silently
ignored on the Java side too (R-242 SDK refactor
mandate). Python's `IbmKeyProtectProperties` simply has
no such fields.

## See also

- `atlas-richie-secret-core` — framework + Protocols +
  `crypto.capability` AAD gate (R-242)
- `atlas-richie-secret-volcengine-kms` — sibling
  KMS-only 2-SPI scope backend (also bce-style with
  no AAD)
- `docs/acceptance/R-247-secret-ibm-key-protect-handoff.md`
  — design + verification
