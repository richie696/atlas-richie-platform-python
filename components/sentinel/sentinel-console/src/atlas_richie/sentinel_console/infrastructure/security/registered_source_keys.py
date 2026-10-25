"""Deployment-owned encryption and idempotency keys for source registry."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .secret_cipher import AesGcmSecretCipher
from .key_ring import KEY_ID_PATTERN, parse_base64_key_ring

_SECRET_ACTIVE_ID = "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID"
_SECRET_RING = "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING"
_FINGERPRINT_ACTIVE_ID = "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID"
_FINGERPRINT_RING = "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING"


@dataclass(frozen=True, slots=True)
class RegisteredSourceKeyConfiguration:
    """Validated key rings; key material is intentionally hidden from repr."""

    active_secret_key_id: str
    secret_keys: Mapping[str, bytes] = field(repr=False)
    active_fingerprint_key_id: str
    fingerprint_keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        secret_keys = MappingProxyType(dict(self.secret_keys))
        fingerprint_keys = MappingProxyType(dict(self.fingerprint_keys))
        _validate_key_ids(secret_keys, self.active_secret_key_id)
        _validate_key_ids(fingerprint_keys, self.active_fingerprint_key_id)
        if any(len(key) != 32 for key in secret_keys.values()):
            raise ValueError("source encryption keys must be 32 bytes")
        if any(len(key) < 32 for key in fingerprint_keys.values()):
            raise ValueError("source fingerprint keys must be at least 32 bytes")
        object.__setattr__(self, "secret_keys", secret_keys)
        object.__setattr__(self, "fingerprint_keys", fingerprint_keys)

    def create_secret_cipher(self) -> AesGcmSecretCipher:
        """Create the cipher configured for writes and retained-key reads."""
        return AesGcmSecretCipher(self.active_secret_key_id, self.secret_keys)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RegisteredSourceKeyConfiguration:
        """Load active and retained keys from deployment environment values.

        Each key ring is ``key-id=base64;key-id=base64``. Raw key material is
        never included in validation errors or the resulting repr.
        """
        values = os.environ if environment is None else environment
        try:
            secret_active_id = values[_SECRET_ACTIVE_ID]
            secret_ring = parse_base64_key_ring(
                values[_SECRET_RING],
                invalid_message="registered-source key ring is invalid",
            )
            fingerprint_active_id = values[_FINGERPRINT_ACTIVE_ID]
            fingerprint_ring = parse_base64_key_ring(
                values[_FINGERPRINT_RING],
                invalid_message="registered-source key ring is invalid",
            )
            return cls(
                active_secret_key_id=secret_active_id,
                secret_keys=secret_ring,
                active_fingerprint_key_id=fingerprint_active_id,
                fingerprint_keys=fingerprint_ring,
            )
        except KeyError:
            raise ValueError(
                "registered-source key configuration is incomplete"
            ) from None


def _validate_key_ids(keys: Mapping[str, bytes], active_key_id: str) -> None:
    if (
        not isinstance(active_key_id, str)
        or KEY_ID_PATTERN.fullmatch(active_key_id) is None
        or not keys
        or active_key_id not in keys
    ):
        raise ValueError("registered-source active key is missing from its key ring")
    if any(
        not isinstance(key_id, str)
        or KEY_ID_PATTERN.fullmatch(key_id) is None
        or not isinstance(key, bytes)
        for key_id, key in keys.items()
    ):
        raise ValueError("registered-source key ring is invalid")
