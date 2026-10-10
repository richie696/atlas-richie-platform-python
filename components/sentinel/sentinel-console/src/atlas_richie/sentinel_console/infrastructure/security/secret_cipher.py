"""Versioned AES-GCM envelope for server-side secrets that must be recovered."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_bytes
from types import MappingProxyType
from typing import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretCipherFormat(StrEnum):
    """Stable storage identifiers for authenticated encryption formats."""

    AES_256_GCM_V1 = "aes-256-gcm-v1"


class SecretCipherError(ValueError):
    """A ciphertext, context, key identifier, or key is invalid."""


@dataclass(frozen=True, slots=True)
class SecretContext:
    """Non-secret owner binding authenticated with each ciphertext."""

    owner_kind: str
    owner_id: str
    field_name: str

    def __post_init__(self) -> None:
        for value in (self.owner_kind, self.owner_id, self.field_name):
            if not value or "\x00" in value or len(value) > 128:
                raise ValueError("secret context contains an invalid identifier")

    def associated_data(self) -> bytes:
        """Encode unambiguous AAD; all fields are bounded and exclude secrets."""
        return b"\x00".join(
            (
                SecretCipherFormat.AES_256_GCM_V1.value.encode(),
                self.owner_kind.encode(),
                self.owner_id.encode(),
                self.field_name.encode(),
            )
        )


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    """Authenticated ciphertext envelope; payload is suppressed in repr."""

    format: SecretCipherFormat
    key_id: str
    payload: bytes = field(repr=False)


class AesGcmSecretCipher:
    """Encrypt recoverable secrets using a deployment-owned key ring.

    `active_key_id` is used for new ciphertexts. Older keys remain available
    only to decrypt envelopes created before rotation.
    """

    _NONCE_BYTES = 12

    def __init__(self, active_key_id: str, keys: Mapping[str, bytes]) -> None:
        if not active_key_id or active_key_id not in keys:
            raise ValueError("active secret key id is not present in the key ring")
        copied_keys = dict(keys)
        if any(not key_id or len(key) != 32 for key_id, key in copied_keys.items()):
            raise ValueError("AES-256-GCM keys must contain exactly 32 bytes")
        self._active_key_id = active_key_id
        self._keys = MappingProxyType(copied_keys)
        self._ciphers = MappingProxyType(
            {key_id: AESGCM(key) for key_id, key in copied_keys.items()}
        )

    def encrypt(self, plaintext: str, context: SecretContext) -> EncryptedSecret:
        """Encrypt a server-side credential with context binding."""
        if not isinstance(plaintext, str) or not plaintext:
            raise ValueError("secret must be a non-empty string")
        nonce = token_bytes(self._NONCE_BYTES)
        ciphertext = self._ciphers[self._active_key_id].encrypt(
            nonce, plaintext.encode("utf-8"), context.associated_data()
        )
        return EncryptedSecret(
            format=SecretCipherFormat.AES_256_GCM_V1,
            key_id=self._active_key_id,
            payload=nonce + ciphertext,
        )

    def decrypt(self, envelope: EncryptedSecret, context: SecretContext) -> str:
        """Decrypt only when key, ciphertext, and owner context all match."""
        if envelope.format is not SecretCipherFormat.AES_256_GCM_V1:
            raise SecretCipherError("unsupported secret cipher format")
        cipher = self._ciphers.get(envelope.key_id)
        if cipher is None or len(envelope.payload) <= self._NONCE_BYTES + 16:
            raise SecretCipherError("secret ciphertext is unavailable")
        nonce = envelope.payload[: self._NONCE_BYTES]
        ciphertext = envelope.payload[self._NONCE_BYTES :]
        try:
            plaintext = cipher.decrypt(nonce, ciphertext, context.associated_data())
        except InvalidTag:
            raise SecretCipherError("secret ciphertext authentication failed") from None
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            raise SecretCipherError("secret plaintext encoding is invalid") from None
