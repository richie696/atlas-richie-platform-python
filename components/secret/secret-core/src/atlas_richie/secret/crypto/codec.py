"""Secret 加密 envelope 与签名值。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto.CipherEnvelope` /
`SignatureValue`。

- `CipherEnvelope` — 不可变,描述一段 ciphertext 的所有元数据:
  `algorithm` / `nonce` / `aad` / `wrapped_key`(可选) / `signature`(可选)。
  序列化用 `EnvelopeCodec`(见 `envelope.py`)。
- `SignatureValue` — 不可变,持有一次签名结果:`algorithm` / `signature`
  bytes / `signed_at` UTC / `key` 引用(谁签的)。

envelope + signature 解耦:`CipherEnvelope.signature` 是可选字段 —
一些 backend 签整段 envelope(防止 ciphertext + metadata 都被篡改),
另一些只签 ciphertext。

English
--------
Cipher envelope and signature value. Mirrors the Java
`CipherEnvelope` / `SignatureValue`. Both are frozen dataclasses
designed for easy serialization via `EnvelopeCodec`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from atlas_richie.secret.crypto.key import KeyReference, WrappedKey


@dataclass(frozen=True, slots=True)
class SignatureValue:
    """Result of a `SigningService.sign(...)` call.

    Attributes:
        algorithm: Signature algorithm (e.g. ``"ECDSA-P256-SHA256"``).
        signature: Raw signature bytes (DER for ECDSA).
        signed_at: UTC time of signing.
        key: Signing key reference.
    """

    algorithm: str
    signature: bytes
    signed_at: datetime
    key: KeyReference


@dataclass(frozen=True, slots=True)
class CipherEnvelope:
    """Self-describing envelope wrapping a ciphertext.

    Attributes:
        algorithm: Cipher algorithm (e.g. ``"AES-256-GCM"``).
        ciphertext: Encrypted payload bytes.
        nonce: Per-encryption nonce / IV (12 bytes for GCM).
        aad: Optional additional authenticated data bound to the
            cipher (typically the secret reference path).
        wrapped_key: Optional wrapped DEK. If present, the receiving
            side must unwrap via `KeyWrappingBackend.unwrap` before
            decrypting the ciphertext.
        signature: Optional envelope-level signature (signed by a
            `SigningService`). Verifying it before decrypting
            prevents the crypto subsystem from acting on
            attacker-rewritten metadata.
        metadata: Free-form backend-defined tags. Not authenticated
            by the cipher; treated as best-effort context only.
    """

    algorithm: str
    ciphertext: bytes
    nonce: bytes
    aad: Mapping[str, str] = field(default_factory=dict)
    wrapped_key: WrappedKey | None = None
    signature: SignatureValue | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


def now_utc() -> datetime:
    """Stable test seam: callers needing a fixed time should monkey-
    patch this function.
    """
    return datetime.now(tz=timezone.utc)


__all__ = [
    "CipherEnvelope",
    "SignatureValue",
    "now_utc",
]
