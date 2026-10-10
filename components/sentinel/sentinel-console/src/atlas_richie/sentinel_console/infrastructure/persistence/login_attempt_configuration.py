"""Deployment configuration for SQL-backed authentication attempt limits."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from .login_attempt_limiter import LoginAttemptLimitPolicy

_FAILURE_THRESHOLD_ENV = "SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD"
_FAILURE_WINDOW_SECONDS_ENV = "SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS"
_BLOCK_DURATION_SECONDS_ENV = "SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS"
_POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")
_MAX_POLICY_INTEGER = 2_147_483_647
_MAX_POLICY_TEXT = str(_MAX_POLICY_INTEGER)


class LoginAttemptLimitConfigurationError(ValueError):
    """Required authentication-attempt throttling settings are invalid."""


@dataclass(frozen=True, slots=True)
class LoginAttemptLimitConfiguration:
    """Validated shared policy without secrets or implicit defaults.

    The historical ``LOGIN_*`` environment names are retained for deployment
    compatibility. Login and own-password use separate HMAC subject buckets
    while sharing this configured threshold, window, and block duration.
    """

    failure_threshold: int
    failure_window_seconds: int
    block_duration_seconds: int

    def __post_init__(self) -> None:
        for value in (
            self.failure_threshold,
            self.failure_window_seconds,
            self.block_duration_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= _MAX_POLICY_INTEGER
            ):
                raise LoginAttemptLimitConfigurationError(
                    "login-attempt policy values must be positive bounded integers"
                )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> LoginAttemptLimitConfiguration:
        """Read every required value; never silently disable throttling."""
        values = os.environ if environment is None else environment
        return cls(
            failure_threshold=_positive_integer(values, _FAILURE_THRESHOLD_ENV),
            failure_window_seconds=_positive_integer(
                values, _FAILURE_WINDOW_SECONDS_ENV
            ),
            block_duration_seconds=_positive_integer(
                values, _BLOCK_DURATION_SECONDS_ENV
            ),
        )

    def to_policy(self) -> LoginAttemptLimitPolicy:
        """Create the application-independent policy consumed by the limiter."""
        return LoginAttemptLimitPolicy(
            failure_threshold=self.failure_threshold,
            window=timedelta(seconds=self.failure_window_seconds),
            block_duration=timedelta(seconds=self.block_duration_seconds),
        )


def _positive_integer(environment: Mapping[str, str], name: str) -> int:
    value = environment.get(name)
    if (
        not isinstance(value, str)
        or _POSITIVE_INTEGER_PATTERN.fullmatch(value) is None
    ):
        raise LoginAttemptLimitConfigurationError(
            "required login-attempt policy setting is missing or invalid"
        )
    if len(value) > len(_MAX_POLICY_TEXT) or (
        len(value) == len(_MAX_POLICY_TEXT) and value > _MAX_POLICY_TEXT
    ):
        raise LoginAttemptLimitConfigurationError(
            "login-attempt policy setting exceeds its supported range"
        )
    parsed = int(value)
    return parsed
