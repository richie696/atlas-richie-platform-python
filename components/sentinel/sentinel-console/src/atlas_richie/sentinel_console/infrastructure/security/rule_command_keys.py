"""Deployment-owned HMAC keys for rule-command idempotency fingerprints."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .key_ring import KEY_ID_PATTERN, parse_base64_key_ring

_ACTIVE_KEY_ID_ENV = "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"
_KEY_RING_ENV = "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING"


class RuleCommandKeyConfigurationError(ValueError):
    """Rule-command fingerprint key settings are missing or invalid."""


@dataclass(frozen=True, slots=True)
class RuleCommandKeyConfiguration:
    """Active and retained fingerprint keys, hidden from repr and immutable."""

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
            raise RuleCommandKeyConfigurationError(
                "rule-command fingerprint key configuration is invalid"
            )
        object.__setattr__(self, "fingerprint_keys", keys)

    @classmethod
    def from_optional_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RuleCommandKeyConfiguration | None:
        """Load a configured key ring, or return ``None`` when wholly absent.

        A partially specified ring still fails closed through
        :meth:`from_environment`; callers can distinguish an intentionally
        disabled optional capability from invalid deployment input.
        """
        values = os.environ if environment is None else environment
        if _ACTIVE_KEY_ID_ENV not in values and _KEY_RING_ENV not in values:
            return None
        return cls.from_environment(values)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RuleCommandKeyConfiguration:
        """Read a deployment-injected ``key-id=base64;...`` key ring."""
        values = os.environ if environment is None else environment
        try:
            active_key_id = values[_ACTIVE_KEY_ID_ENV]
            encoded_ring = values[_KEY_RING_ENV]
        except KeyError:
            raise RuleCommandKeyConfigurationError(
                "rule-command fingerprint key settings are incomplete"
            ) from None
        try:
            keys = parse_base64_key_ring(
                encoded_ring,
                invalid_message="rule-command fingerprint key ring is invalid",
                minimum_key_bytes=32,
                short_key_message=(
                    "rule-command fingerprint keys must be at least 32 bytes"
                ),
            )
            return cls(active_key_id, keys)
        except ValueError as error:
            raise RuleCommandKeyConfigurationError(str(error)) from None
