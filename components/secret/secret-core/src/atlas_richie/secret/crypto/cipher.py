"""Secret cipher — 对称加密/解密的最小契约 + AES-GCM 默认实现。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto.SecretCipher` /
`cn.richie696.component.secret.core.crypto.DefaultSecretCipher`。

`SecretCipher` Protocol — 加密 / 解密的最小契约:

- `encrypt(plaintext, context) -> CipherEnvelope`
- `decrypt(envelope, context) -> bytes`

`DefaultSecretCipher` — 基于 `cryptography` 库的 AES-256-GCM 实现:

- **算法**:`AES-256-GCM`,12 字节 nonce,16 字节 auth tag
  (`cryptography` 库把 tag 拼在 ciphertext 尾部)
- **AAD**:把 `context.aad` 序列化成稳定字节流(按 key 排序,UTF-8 编码)
  作为 AAD;接收方用同样的 AAD 才能通过 GCM 校验
- **后端兼容**:可注入 `KeyWrappingBackend` 启用 envelope 模式;无
  时退回 raw key(本地 key,无 KMS 交互)

设计要点:

- **不抛 ValueError**:所有错误用 `SecretCryptoException` 包装
- **AAD 序列化必须稳定**:用 JSON(按 key 排序)而不是 repr
- **nonce 随机性**:用 `os.urandom(12)`,绝不从 key 派生
- **AAD 缺失**:frame 在 `context.aad` 上用 `KeyReference.provider /
  key_id / version / algorithm` 字段填充,避免 AAD 漂移

English
--------
Secret cipher: symmetric encrypt / decrypt. Mirrors the Java
`SecretCipher` / `DefaultSecretCipher`. The default implementation
uses `cryptography` library's AES-256-GCM; injectable
`KeyWrappingBackend` for envelope mode.
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

from atlas_richie.secret.crypto.backend import KeyWrappingBackend
from atlas_richie.secret.crypto.codec import CipherEnvelope
from atlas_richie.secret.crypto.key import CryptoContext, KeyReference
from atlas_richie.secret.errors import SecretCryptoException


@runtime_checkable
class SecretCipher(Protocol):
    """Symmetric encryption / decryption contract."""

    def encrypt(
        self,
        plaintext: bytes,
        context: CryptoContext,
    ) -> CipherEnvelope:
        """Encrypt `plaintext` under `context.primary_key`; return a
        self-describing `CipherEnvelope`.
        """
        ...

    def decrypt(
        self,
        envelope: CipherEnvelope,
        context: CryptoContext,
    ) -> bytes:
        """Decrypt `envelope` under `context.primary_key`; return
        the original plaintext. Raises `SecretCryptoException` on
        authentication failure.
        """
        ...


def _aad_bytes(aad: dict[str, str]) -> bytes:
    """Stable AAD serialization: JSON with sorted keys, UTF-8."""
    return json.dumps(aad, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _aad_from_context(context: CryptoContext) -> bytes:
    """Build the wire AAD: includes key fingerprint + user-provided
    AAD. This binds the ciphertext to the key it was encrypted
    under, so an attacker cannot move a ciphertext between keys.
    """
    base: dict[str, str] = {
        "provider": context.primary_key.provider,
        "key_id": context.primary_key.key_id,
        "purpose": context.purpose.value,
    }
    if context.primary_key.algorithm:
        base["algorithm"] = context.primary_key.algorithm
    if context.primary_key.version is not None:
        base["version"] = str(context.primary_key.version)
    base.update(context.aad)
    return _aad_bytes(base)


class DefaultSecretCipher:
    """AES-256-GCM cipher backed by `cryptography` library.

    Optional `wrapping_backend` enables envelope mode: each
    `encrypt()` generates a fresh DEK, wraps it via the backend, and
    attaches the `WrappedKey` to the returned envelope. Without a
    wrapping backend, the cipher assumes a local symmetric key
    (intended for unit tests and the local-crypto variant; not for
    production secrets).
    """

    ALGORITHM = "AES-256-GCM"
    NONCE_BYTES = 12
    KEY_BYTES = 32  # AES-256

    def __init__(
        self,
        *,
        wrapping_backend: KeyWrappingBackend | None = None,
        local_key: bytes | None = None,
    ) -> None:
        if wrapping_backend is None and local_key is None:
            raise SecretCryptoException(
                "DefaultSecretCipher requires either a wrapping_backend or a local_key",
            )
        if local_key is not None and len(local_key) != self.KEY_BYTES:
            raise SecretCryptoException(
                f"local_key must be {self.KEY_BYTES} bytes (AES-256); got {len(local_key)}",
            )
        self._wrapping_backend = wrapping_backend
        self._local_key = local_key

    def _cryptography(self):
        # Lazy import so the module can be imported without the
        # optional crypto extra installed.
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as error:  # pragma: no cover - exercised only when extra missing
            raise SecretCryptoException(
                "DefaultSecretCipher requires the 'cryptography' package; "
                "install atlas-richie-secret-core[crypto]",
            ) from error
        return AESGCM

    def encrypt(
        self,
        plaintext: bytes,
        context: CryptoContext,
    ) -> CipherEnvelope:
        aesgcm = self._cryptography()
        nonce = os.urandom(self.NONCE_BYTES)
        # The authenticated AAD is the context's aad merged with key
        # identity. It is bound to the ciphertext; the decrypt side
        # reconstructs it from the envelope's `aad` (since that is
        # what the sender stored) — so any tamper with `envelope.aad`
        # is detected as a tag mismatch.
        envelope_aad = dict(context.aad)
        full_aad = self._auth_aad(context, envelope_aad)
        if self._wrapping_backend is not None:
            dek = os.urandom(self.KEY_BYTES)
            wrapped = self._wrapping_backend.wrap_key(dek, context.primary_key)
            cipher = aesgcm(dek)
        else:
            assert self._local_key is not None  # checked in __init__
            cipher = aesgcm(self._local_key)
            wrapped = None
        ciphertext_with_tag = cipher.encrypt(nonce, plaintext, full_aad)
        # cryptography's AESGCM returns ciphertext || 16-byte tag. Keep
        # the joined form; decrypt handles the split transparently.
        return CipherEnvelope(
            algorithm=self.ALGORITHM,
            ciphertext=ciphertext_with_tag,
            nonce=nonce,
            aad=envelope_aad,
            wrapped_key=wrapped,
            signature=None,
            metadata={"key_id": context.primary_key.key_id},
        )

    def decrypt(
        self,
        envelope: CipherEnvelope,
        context: CryptoContext,
    ) -> bytes:
        if envelope.algorithm != self.ALGORITHM:
            raise SecretCryptoException(
                f"unsupported algorithm: {envelope.algorithm!r}",
            )
        aesgcm = self._cryptography()
        if self._wrapping_backend is not None and envelope.wrapped_key is not None:
            unwrap_ctx = CryptoContext(
                primary_key=context.primary_key,
                purpose=context.purpose,
                aad=envelope.aad,
            )
            dek = self._wrapping_backend.unwrap_key(envelope.wrapped_key, unwrap_ctx)
            cipher = aesgcm(dek)
        elif self._local_key is not None:
            cipher = aesgcm(self._local_key)
        else:
            raise SecretCryptoException(
                "envelope uses a wrapped DEK but no wrapping_backend configured",
            )
        full_aad = self._auth_aad(context, dict(envelope.aad))
        try:
            return cipher.decrypt(envelope.nonce, envelope.ciphertext, full_aad)
        except Exception as error:  # cryptography raises InvalidTag
            raise SecretCryptoException(
                f"decryption failed (bad key or tampered ciphertext): {error}",
            ) from error

    def _auth_aad(
        self,
        context: CryptoContext,
        envelope_aad: "dict[str, str]",
    ) -> bytes:
        """Build the wire AAD. Includes the key identity so an
        attacker cannot move a ciphertext between keys, and binds
        the envelope's `aad` so any tamper with metadata invalidates
        the tag.
        """
        merged: dict[str, str] = {
            "provider": context.primary_key.provider,
            "key_id": context.primary_key.key_id,
            "purpose": context.purpose.value,
        }
        if context.primary_key.algorithm:
            merged["algorithm"] = context.primary_key.algorithm
        if context.primary_key.version is not None:
            merged["version"] = str(context.primary_key.version)
        merged.update(envelope_aad)
        return _aad_bytes(merged)


__all__ = [
    "SecretCipher",
    "DefaultSecretCipher",
]


_ = (KeyReference,)
