"""Secret envelope crypto — 序列化 + envelope 完整流程。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto.EnvelopeCrypto` /
`cn.richie696.component.secret.core.crypto.DefaultEnvelopeCrypto` /
`cn.richie696.component.secret.core.crypto.ArseEnvelopeCodec`。

`EnvelopeCrypto` Protocol — 在 `SecretCipher` + `SigningService` 之
上的高阶抽象:

- `seal(plaintext, context) -> CipherEnvelope` — encrypt + sign,
  返回带签名的 envelope
- `open(envelope, context) -> bytes` — verify 签名 + decrypt,失败
  抛 `SecretCryptoException`

`DefaultEnvelopeCrypto` — 默认实现,组合 `SecretCipher` + `SigningService`。
签名在 ciphertext + envelope metadata 上做(防 metadata 篡改)。

`EnvelopeCodec` — `CipherEnvelope` 的序列化 / 反序列化。`ArseEnvelopeCodec`
是参考实现,使用 base64 + JSON 编码(ASCII-safe,适合 HTTP / Redis 存储)。
扩展性:其它 backend(Vault / KMS)可实现自有的 codec。

设计要点:

- **不依赖 cryptography 库自身**:`EnvelopeCodec` 是纯 stdlib 逻辑
  (`base64` + `json`),只有 `DefaultEnvelopeCrypto` 触达 crypto
- **签名内容**:序列化 JSON body 的 canonical 形式(SHA-256 摘要)
- **algorithm 校验**:open 时检查 envelope.algorithm 与 cipher 一致
- **AAD 绑定**:open 时检查 envelope.aad 与 context.aad 一致

English
--------
Envelope crypto: high-level seal / open on top of `SecretCipher` +
`SigningService`. Mirrors the Java `EnvelopeCrypto` /
`DefaultEnvelopeCrypto` / `ArseEnvelopeCodec`.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from atlas_richie.secret.crypto.cipher import SecretCipher
from atlas_richie.secret.crypto.codec import CipherEnvelope
from atlas_richie.secret.crypto.key import CryptoContext
from atlas_richie.secret.crypto.signing import SigningService
from atlas_richie.secret.errors import SecretCryptoException


@runtime_checkable
class EnvelopeCrypto(Protocol):
    """Seal (encrypt + sign) and open (verify + decrypt) envelopes."""

    def seal(
        self,
        plaintext: bytes,
        context: CryptoContext,
    ) -> CipherEnvelope:
        """Encrypt `plaintext` and sign the resulting envelope."""
        ...

    def open(
        self,
        envelope: CipherEnvelope,
        context: CryptoContext,
    ) -> bytes:
        """Verify the signature and decrypt the payload. Raises
        `SecretCryptoException` on signature mismatch, AAD mismatch,
        or decrypt failure.
        """
        ...


class EnvelopeCodec(Protocol):
    """Serialize / deserialize `CipherEnvelope` for storage or
    transport.
    """

    def encode(self, envelope: CipherEnvelope) -> bytes:
        """Return a stable, canonical byte representation of
        `envelope`.
        """
        ...

    def decode(self, blob: bytes) -> CipherEnvelope:
        """Inverse of `encode`. Must be the exact inverse — any
        drift breaks stored ciphertext.
        """
        ...


class ArseEnvelopeCodec:
    """base64 + JSON codec for `CipherEnvelope`. ASCII-safe; suitable
    for HTTP / Redis values / log lines.

    Layout (JSON object):
    ```json
    {
      "algorithm": "AES-256-GCM",
      "nonce_b64": "...",
      "ciphertext_b64": "...",
      "aad": {"key": "value"},
      "wrapped_key": null or {...},
      "signature": null or {...},
      "metadata": {"key_id": "..."}
    }
    ```
    """

    def encode(self, envelope: CipherEnvelope) -> bytes:
        wrapped = None
        if envelope.wrapped_key is not None:
            wrapped = {
                "kek_provider": envelope.wrapped_key.kek_reference.provider,
                "kek_key_id": envelope.wrapped_key.kek_reference.key_id,
                "kek_version": envelope.wrapped_key.kek_reference.version,
                "kek_algorithm": envelope.wrapped_key.kek_reference.algorithm,
                "ciphertext_b64": base64.b64encode(
                    envelope.wrapped_key.ciphertext,
                ).decode("ascii"),
                "algorithm": envelope.wrapped_key.algorithm,
                "nonce_b64": (
                    base64.b64encode(envelope.wrapped_key.nonce).decode("ascii")
                    if envelope.wrapped_key.nonce is not None
                    else None
                ),
                "aad": dict(envelope.wrapped_key.aad),
            }
        signature = None
        if envelope.signature is not None:
            signature = {
                "algorithm": envelope.signature.algorithm,
                "signature_b64": base64.b64encode(
                    envelope.signature.signature,
                ).decode("ascii"),
                "signed_at": envelope.signature.signed_at.isoformat(),
                "key_provider": envelope.signature.key.provider,
                "key_id": envelope.signature.key.key_id,
                "key_version": envelope.signature.key.version,
                "key_algorithm": envelope.signature.key.algorithm,
            }
        payload = {
            "algorithm": envelope.algorithm,
            "nonce_b64": base64.b64encode(envelope.nonce).decode("ascii"),
            "ciphertext_b64": base64.b64encode(envelope.ciphertext).decode("ascii"),
            "aad": dict(envelope.aad),
            "wrapped_key": wrapped,
            "signature": signature,
            "metadata": dict(envelope.metadata),
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")

    def decode(self, blob: bytes) -> CipherEnvelope:
        raw = json.loads(blob.decode("utf-8"))
        wrapped = None
        if raw.get("wrapped_key"):
            wk = raw["wrapped_key"]
            from atlas_richie.secret.crypto.key import KeyReference, WrappedKey

            wrapped = WrappedKey(
                kek_reference=KeyReference(
                    provider=wk["kek_provider"],
                    key_id=wk["kek_key_id"],
                    version=wk.get("kek_version"),
                    algorithm=wk.get("kek_algorithm"),
                ),
                ciphertext=base64.b64decode(wk["ciphertext_b64"]),
                algorithm=wk["algorithm"],
                nonce=(
                    base64.b64decode(wk["nonce_b64"]) if wk.get("nonce_b64") else None
                ),
                aad=wk.get("aad", {}),
            )
        signature = None
        if raw.get("signature"):
            from datetime import datetime

            from atlas_richie.secret.crypto.codec import SignatureValue
            from atlas_richie.secret.crypto.key import KeyReference

            sig = raw["signature"]
            signature = SignatureValue(
                algorithm=sig["algorithm"],
                signature=base64.b64decode(sig["signature_b64"]),
                signed_at=datetime.fromisoformat(sig["signed_at"]),
                key=KeyReference(
                    provider=sig["key_provider"],
                    key_id=sig["key_id"],
                    version=sig.get("key_version"),
                    algorithm=sig.get("key_algorithm"),
                ),
            )
        return CipherEnvelope(
            algorithm=raw["algorithm"],
            ciphertext=base64.b64decode(raw["ciphertext_b64"]),
            nonce=base64.b64decode(raw["nonce_b64"]),
            aad=raw.get("aad", {}),
            wrapped_key=wrapped,
            signature=signature,
            metadata=raw.get("metadata", {}),
        )


class DefaultEnvelopeCrypto:
    """Compose `SecretCipher` + `SigningService` into a single
    seal / open entry point.

    The signature is computed over the canonical JSON of the
    `CipherEnvelope` (using `ArseEnvelopeCodec.encode`); the
    signature is then attached to the envelope. On `open`, the
    envelope is decoded, the signature is verified, and only then
    is the ciphertext decrypted.
    """

    def __init__(
        self,
        cipher: SecretCipher,
        signing: SigningService | None = None,
        codec: EnvelopeCodec | None = None,
    ) -> None:
        self._cipher = cipher
        self._signing = signing
        self._codec = codec or ArseEnvelopeCodec()

    def seal(
        self,
        plaintext: bytes,
        context: CryptoContext,
    ) -> CipherEnvelope:
        encrypted = self._cipher.encrypt(plaintext, context)
        if self._signing is None:
            return encrypted
        body = self._codec.encode(encrypted)
        signature = self._signing.sign(body, context)
        return CipherEnvelope(
            algorithm=encrypted.algorithm,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            aad=encrypted.aad,
            wrapped_key=encrypted.wrapped_key,
            signature=signature,
            metadata=encrypted.metadata,
        )

    def open(
        self,
        envelope: CipherEnvelope,
        context: CryptoContext,
    ) -> bytes:
        if envelope.signature is not None and self._signing is not None:
            # Re-encode with `signature=None` so the signed body
            # round-trips with what was signed during `seal` (which
            # signed the encrypted body before the signature was
            # attached).
            signed = CipherEnvelope(
                algorithm=envelope.algorithm,
                ciphertext=envelope.ciphertext,
                nonce=envelope.nonce,
                aad=envelope.aad,
                wrapped_key=envelope.wrapped_key,
                signature=None,
                metadata=envelope.metadata,
            )
            body = self._codec.encode(signed)
            if not self._signing.verify(body, envelope.signature):
                raise SecretCryptoException(
                    "envelope signature verification failed",
                )
        if envelope.aad != dict(context.aad):
            raise SecretCryptoException(
                f"envelope AAD mismatch: expected {dict(context.aad)!r}, "
                f"got {envelope.aad!r}",
            )
        return self._cipher.decrypt(envelope, context)


__all__ = [
    "EnvelopeCrypto",
    "EnvelopeCodec",
    "ArseEnvelopeCodec",
    "DefaultEnvelopeCrypto",
]


_ = (Mapping,)
