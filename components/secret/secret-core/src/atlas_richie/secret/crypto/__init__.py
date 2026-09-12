"""Secret crypto 子包:key / codec / backend SPI / cipher / signing / envelope。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto` + `core.crypto` 全部类。

- `crypto.key` — `KeyPurpose` / `KeyReference` / `WrappedKey` /
  `CryptoContext`
- `crypto.codec` — `CipherEnvelope` / `SignatureValue` / `now_utc`
- `crypto.backend` — `KeyWrappingBackend` / `SigningBackend` SPI
- `crypto.cipher` — `SecretCipher` Protocol + `DefaultSecretCipher`
  (AES-256-GCM,基于 `cryptography` 可选依赖)
- `crypto.signing` — `SigningService` Protocol + `DefaultSigningService`
  (ECDSA-P256-SHA256)
- `crypto.envelope` — `EnvelopeCrypto` Protocol + `DefaultEnvelopeCrypto`
  + `EnvelopeCodec` + `ArseEnvelopeCodec`(base64 + JSON)
- `crypto.capability` — capability 门禁(R-242 SDK 化引入):AAD
  支持 / 读写能力 / capability fingerprint(对位 Java
  `RemoteSecretProviderClient` 的 capability 门禁)

`DefaultSecretCipher` / `DefaultSigningService` 都需要
`atlas-richie-secret-core[crypto]` extra(装 `cryptography` 库);无该
依赖时,导入会抛 `SecretCryptoException` 并给出安装提示。

English
--------
Secret crypto sub-package. Re-exports the key / codec / backend /
cipher / signing / envelope symbols. The default cipher and signing
implementations require the optional `cryptography` package; missing
it raises `SecretCryptoException` with an install hint.
"""

from atlas_richie.secret.crypto.backend import (
    KeyWrappingBackend,
    SigningBackend,
)
from atlas_richie.secret.crypto.capability import (
    assert_can_read,
    assert_can_write,
    assert_capability,
    capability_fingerprint,
    has_aad,
    require_aad_support,
)
from atlas_richie.secret.crypto.cipher import (
    DefaultSecretCipher,
    SecretCipher,
)
from atlas_richie.secret.crypto.codec import (
    CipherEnvelope,
    SignatureValue,
    now_utc,
)
from atlas_richie.secret.crypto.envelope import (
    ArseEnvelopeCodec,
    DefaultEnvelopeCrypto,
    EnvelopeCodec,
    EnvelopeCrypto,
)
from atlas_richie.secret.crypto.key import (
    CryptoContext,
    KeyPurpose,
    KeyReference,
    WrappedKey,
)
from atlas_richie.secret.crypto.signing import (
    DefaultSigningService,
    SigningService,
    generate_ecdsa_keypair,
)

__all__ = [
    "KeyPurpose",
    "KeyReference",
    "WrappedKey",
    "CryptoContext",
    "CipherEnvelope",
    "SignatureValue",
    "now_utc",
    "KeyWrappingBackend",
    "SigningBackend",
    "SecretCipher",
    "DefaultSecretCipher",
    "SigningService",
    "DefaultSigningService",
    "generate_ecdsa_keypair",
    "EnvelopeCrypto",
    "EnvelopeCodec",
    "ArseEnvelopeCodec",
    "DefaultEnvelopeCrypto",
    # capability gates (R-242)
    "require_aad_support",
    "has_aad",
    "assert_can_read",
    "assert_can_write",
    "assert_capability",
    "capability_fingerprint",
]
