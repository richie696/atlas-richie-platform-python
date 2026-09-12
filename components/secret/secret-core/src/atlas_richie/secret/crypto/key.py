"""Secret 加密密钥模型。

中文
----
对位 Java `cn.richie696.component.secret.api.crypto.KeyPurpose` /
`KeyReference` / `WrappedKey` / `CryptoContext`。

- `KeyPurpose` — StrEnum,标识密钥用途(数据加密 / 密钥包装 / 签名)。
  KMS 端的 policy 决定用途切换是否被允许。
- `KeyReference` — 不可变,标识一个 KMS / 本地密钥:
  `(provider_name, key_id, version)`,可选 `algorithm` 约束。
- `WrappedKey` — 不可变,持有被包装的 DEK + 包装它的 KEK 引用:
  实际场景下 `ciphertext` 仍是加密形式,只有持有 KEK 的 backend 才
  能 unwrap。
- `CryptoContext` — 不可变,描述一次 crypto 操作的上下文:主密钥 +
  purpose + AAD(additional authenticated data)。

`KeyReference` 是 hashable + frozen,可作 cache key;`WrappedKey` 同
样。`CryptoContext` 不参与 cache,只作操作时的隐式参数。

English
--------
Secret crypto key model. Mirrors the Java
`KeyPurpose` / `KeyReference` / `WrappedKey` / `CryptoContext`. All
three are frozen dataclasses so they are safe to share across
threads and to use as cache keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class KeyPurpose(StrEnum):
    """Intended use of a key. Used by KMS-side policy enforcement."""

    ENCRYPT = "encrypt"
    WRAP = "wrap"
    SIGN = "sign"
    DERIVE = "derive"


@dataclass(frozen=True, slots=True)
class KeyReference:
    """Identifies a key managed by some backend (KMS, local, HSM).

    Attributes:
        provider: Name of the key-management backend.
        key_id: Backend-defined key identifier.
        version: Optional version pin; ``None`` means "latest".
        algorithm: Optional algorithm constraint (e.g. ``"AES-256"``,
            ``"EC-P256"``). The crypto subsystem will reject
            mismatched algorithms with `SecretCryptoException`.
    """

    provider: str
    key_id: str
    version: int | None = None
    algorithm: str | None = None


@dataclass(frozen=True, slots=True)
class WrappedKey:
    """A DEK encrypted by a KEK (Key Encryption Key).

    The `ciphertext` here is the encrypted DEK bytes; the plaintext
    DEK only materializes inside the crypto backend that holds the
    KEK. Cross-backend portability: a WrappedKey created by backend A
    can be decrypted by backend B if both backends agree on the
    KEK reference and the wrap algorithm.

    Attributes:
        kek_reference: The KEK that protects this DEK.
        ciphertext: Encrypted DEK bytes.
        algorithm: Wrap algorithm identifier (e.g. ``"AES-KW-256"``).
        nonce: Optional nonce / IV used during wrapping.
        aad: Optional additional authenticated data bound to the
            wrap operation (typically the DEK's metadata).
    """

    kek_reference: KeyReference
    ciphertext: bytes
    algorithm: str
    nonce: bytes | None = None
    aad: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CryptoContext:
    """Per-operation crypto context.

    Attributes:
        primary_key: Key used to encrypt / wrap the payload.
        purpose: Intended use; backend should reject mismatches.
        aad: Additional authenticated data bound to the operation.
            For envelope encryption, AAD typically includes the
            secret reference / path so an attacker cannot move a
            ciphertext between paths.
    """

    primary_key: KeyReference
    purpose: KeyPurpose
    aad: Mapping[str, str] = field(default_factory=dict)


__all__ = [
    "KeyPurpose",
    "KeyReference",
    "WrappedKey",
    "CryptoContext",
]
