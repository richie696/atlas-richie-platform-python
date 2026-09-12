"""Secret 签名服务 — ECDSA 默认实现。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto.SigningService` /
`cn.richie696.component.secret.core.crypto.DefaultSigningService`。

`SigningService` Protocol — 签名 / 验签的最小契约:
- `sign(payload, context) -> SignatureValue`
- `verify(payload, signature) -> bool`

`DefaultSigningService` — 基于 `cryptography` 库的 ECDSA P-256 默认
实现:

- **算法**:`ECDSA-P256-SHA256`(最广泛支持的曲线 + NIST hash)
- **私钥**:`local_private_key` 用于本地签名测试;生产应通过
  `SigningBackend` 接入 KMS / HSM
- **签名格式**:DER 编码(由 `cryptography` 默认)

设计要点:

- **verify 必须是 constant-time**:防止 timing attack 推断签名内容
- **signature 的 key 必须可重复定位**:`SignatureValue.key` 是
  `KeyReference`,frame 可以用它查 KMS 验签
- **不抛 ValueError**:错误一律 `SecretCryptoException`

English
--------
Secret signing service. Mirrors the Java `SigningService` /
`DefaultSigningService`. The default implementation uses
`cryptography` library's ECDSA P-256 + SHA-256.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.crypto.backend import SigningBackend
from atlas_richie.secret.crypto.codec import SignatureValue, now_utc
from atlas_richie.secret.crypto.key import CryptoContext, KeyReference
from atlas_richie.secret.errors import SecretCryptoException


@runtime_checkable
class SigningService(Protocol):
    """Sign and verify payloads."""

    def sign(
        self,
        payload: bytes,
        context: CryptoContext,
    ) -> SignatureValue:
        """Sign `payload` under `context.primary_key`."""
        ...

    def verify(
        self,
        payload: bytes,
        signature: SignatureValue,
    ) -> bool:
        """Return ``True`` iff the signature is valid. Must be
        constant-time; must not raise on invalid signatures.
        """
        ...


class DefaultSigningService:
    """ECDSA-P256-SHA256 signing service backed by `cryptography`."""

    ALGORITHM = "ECDSA-P256-SHA256"

    def __init__(
        self,
        *,
        signing_backend: SigningBackend | None = None,
        local_private_key: "object | None" = None,
        local_public_key: "object | None" = None,
        key_reference: KeyReference | None = None,
    ) -> None:
        """Either pass `signing_backend` (KMS / HSM) or both
        `local_private_key` and `local_public_key` (with a
        `key_reference`) for the local-crypto variant.
        """
        if signing_backend is None and (
            local_private_key is None or local_public_key is None
        ):
            raise SecretCryptoException(
                "DefaultSigningService requires either a signing_backend "
                "or both local_private_key and local_public_key",
            )
        self._signing_backend = signing_backend
        self._local_private_key = local_private_key
        self._local_public_key = local_public_key
        self._key_reference = key_reference

    def _cryptography(self):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.exceptions import InvalidSignature
        except ImportError as error:  # pragma: no cover
            raise SecretCryptoException(
                "DefaultSigningService requires the 'cryptography' package; "
                "install atlas-richie-secret-core[crypto]",
            ) from error
        return hashes, serialization, ec, InvalidSignature

    def sign(
        self,
        payload: bytes,
        context: CryptoContext,
    ) -> SignatureValue:
        if self._signing_backend is not None:
            return self._signing_backend.sign(payload, context.primary_key)
        hashes, _, ec, _ = self._cryptography()
        assert self._local_private_key is not None
        assert self._key_reference is not None
        der = self._local_private_key.sign(
            payload,
            ec.ECDSA(hashes.SHA256()),
        )
        return SignatureValue(
            algorithm=self.ALGORITHM,
            signature=der,
            signed_at=now_utc(),
            key=self._key_reference,
        )

    def verify(
        self,
        payload: bytes,
        signature: SignatureValue,
    ) -> bool:
        if self._signing_backend is not None:
            return self._signing_backend.verify(payload, signature)
        hashes, _, ec, InvalidSignature = self._cryptography()
        assert self._local_public_key is not None
        try:
            self._local_public_key.verify(
                signature.signature,
                payload,
                ec.ECDSA(hashes.SHA256()),
            )
            return True
        except InvalidSignature:
            return False
        except Exception as error:  # noqa: BLE001
            raise SecretCryptoException(
                f"signature verification failed: {error}",
            ) from error


def generate_ecdsa_keypair() -> tuple[object, object]:
    """Convenience helper: generate a fresh ECDSA P-256 keypair.

    Returns `(private_key, public_key)` instances from the
    `cryptography` library. Used by tests and the local-crypto
    variant of `DefaultSigningService`.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as error:  # pragma: no cover
        raise SecretCryptoException(
            "generate_ecdsa_keypair requires the 'cryptography' package; "
            "install atlas-richie-secret-core[crypto]",
        ) from error
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


__all__ = [
    "SigningService",
    "DefaultSigningService",
    "generate_ecdsa_keypair",
]
