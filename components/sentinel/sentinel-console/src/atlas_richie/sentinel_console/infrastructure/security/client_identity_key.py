"""Deployment-provided key used to pseudonymize login client identities."""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_CLIENT_IDENTITY_KEY_ENV = "SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY"


class ClientIdentityKeyConfigurationError(ValueError):
    """The deployment-owned client identity key is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ClientIdentityKeyConfiguration:
    """Validated HMAC key; secret bytes are excluded from object repr."""

    hmac_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.hmac_key, bytes) or len(self.hmac_key) < 32:
            raise ClientIdentityKeyConfigurationError(
                "client identity HMAC key must contain at least 32 bytes"
            )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> ClientIdentityKeyConfiguration:
        """Read a base64-encoded secret without returning it in errors."""
        values = os.environ if environment is None else environment
        encoded_key = values.get(_CLIENT_IDENTITY_KEY_ENV)
        if not isinstance(encoded_key, str) or not encoded_key:
            raise ClientIdentityKeyConfigurationError(
                "client identity HMAC key is required"
            )
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError):
            raise ClientIdentityKeyConfigurationError(
                "client identity HMAC key encoding is invalid"
            ) from None
        return cls(key)
