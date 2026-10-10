"""Deployment-owned HMAC key rotation settings for account commands."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .key_ring import KEY_ID_PATTERN, parse_base64_key_ring

_ACTIVE_KEY_ID_ENV = "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_ACTIVE_KEY_ID"
_KEY_RING_ENV = "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_KEY_RING"


class AccountCommandKeyConfigurationError(ValueError):
    """Account-command HMAC key settings are missing or invalid."""


@dataclass(frozen=True, slots=True)
class AccountCommandKeyConfiguration:
    """Active and retained fingerprint keys with immutable, hidden key bytes."""

    active_fingerprint_key_id: str
    fingerprint_keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        keys = MappingProxyType(dict(self.fingerprint_keys))
        if (
            not isinstance(self.active_fingerprint_key_id, str)
            or KEY_ID_PATTERN.fullmatch(self.active_fingerprint_key_id) is None
            or not keys
            or self.active_fingerprint_key_id not in keys
            or any(
                not isinstance(key_id, str)
                or KEY_ID_PATTERN.fullmatch(key_id) is None
                or not isinstance(key, bytes)
                or len(key) < 32
                for key_id, key in keys.items()
            )
        ):
            raise AccountCommandKeyConfigurationError(
                "account-command fingerprint key configuration is invalid"
            )
        object.__setattr__(self, "fingerprint_keys", keys)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> AccountCommandKeyConfiguration:
        """Load a ``key-id=base64;...`` ring without echoing key material."""
        values = os.environ if environment is None else environment
        try:
            active_key_id = values[_ACTIVE_KEY_ID_ENV]
            key_ring = parse_base64_key_ring(
                values[_KEY_RING_ENV],
                invalid_message="account-command fingerprint key ring is invalid",
                minimum_key_bytes=32,
                short_key_message=(
                    "account-command fingerprint keys must be at least 32 bytes"
                ),
            )
            return cls(active_key_id, key_ring)
        except KeyError:
            raise AccountCommandKeyConfigurationError(
                "account-command fingerprint key settings are incomplete"
            ) from None
        except ValueError as error:
            raise AccountCommandKeyConfigurationError(str(error)) from None
