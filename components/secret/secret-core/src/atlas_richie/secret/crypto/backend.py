"""Secret crypto backend SPI: 密钥包装 / 签名端口。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto.KeyWrappingBackend` /
`SigningBackend`。

`KeyWrappingBackend` Protocol — KMS / HSM / 本地密钥库的密钥包装
能力。`EnvelopeCrypto` 在加密 payload 之前生成 DEK,再用 backend
的 `wrap_key(DEK, KEK)` 拿到 WrappedKey;解密时调 `unwrap_key`。

`SigningBackend` Protocol — 签名能力。`SigningService` 在 envelope
上附加签名,decrypt 前先 `verify` 保证 metadata 未被篡改。

`backend` 与 `cipher` / `signing` / `envelope` 三个 Service 的区别:
- **backend**(本文件)是 KMS / 硬件层的最小 SPI,只做 wrap / unwrap /
  sign / verify。
- **cipher / signing / envelope** Service 是 backend 之上的高阶抽象,
  提供 plaintext 加密 / 签名 / envelope 序列化等便利。

设计:

- 真实生产 backend(AWS KMS / Vault Transit / PKCS#11 HSM / Azure
  Key Vault / ...)实现 `KeyWrappingBackend` + `SigningBackend` 两个
  Protocol,framework 通过组合使用。
- framework 自身提供 `cryptography` 库驱动的本地实现
  (见 `DefaultSecretCipher` / `DefaultSigningService`),不依赖
  远程 KMS;生产应替换为远程 backend。

English
--------
Secret crypto backend SPI. Mirrors the Java `KeyWrappingBackend` /
`SigningBackend`. The two Protocols are the minimum surface that a
real KMS / HSM must implement; the high-level `SecretCipher` /
`SigningService` / `EnvelopeCrypto` Services build on top.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.crypto.codec import SignatureValue
from atlas_richie.secret.crypto.key import CryptoContext, KeyReference, WrappedKey


@runtime_checkable
class KeyWrappingBackend(Protocol):
    """KMS / HSM interface for wrapping and unwrapping DEKs."""

    def wrap_key(
        self,
        dek: bytes,
        kek: KeyReference,
        *,
        algorithm: str | None = None,
    ) -> WrappedKey:
        """Wrap (encrypt) `dek` with `kek`. Returns a `WrappedKey`
        whose `ciphertext` is the encrypted DEK; only an entity
        holding `kek` may unwrap it.
        """
        ...

    def unwrap_key(
        self,
        wrapped: WrappedKey,
        context: CryptoContext,
    ) -> bytes:
        """Unwrap (decrypt) a wrapped DEK. Caller must prove
        authorization via `context.purpose` and the matching
        `KeyPurpose`.
        """
        ...


@runtime_checkable
class SigningBackend(Protocol):
    """KMS / HSM interface for signing and verifying payloads."""

    def sign(
        self,
        payload: bytes,
        key: KeyReference,
        *,
        algorithm: str | None = None,
    ) -> SignatureValue:
        """Sign `payload` with `key`. Backend chooses the actual
        signature algorithm; pass `algorithm` to constrain it.
        """
        ...

    def verify(
        self,
        payload: bytes,
        signature: SignatureValue,
    ) -> bool:
        """Return ``True`` iff the signature is valid for `payload`.
        Must be constant-time; must not leak which byte differs.
        """
        ...


__all__ = [
    "KeyWrappingBackend",
    "SigningBackend",
]
