"""Application contract for exchanging a deployment setup code for a grant."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Protocol

_OPAQUE_GRANT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_OPERATOR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,1024}$")


def is_valid_bootstrap_operator_code(value: object) -> bool:
    """Validate the URL-safe operator-code syntax accepted by the authority."""
    return (
        isinstance(value, str)
        and _OPERATOR_CODE_PATTERN.fullmatch(value) is not None
    )


class BootstrapAuthorizationStatus(StrEnum):
    """Finite outcomes of a setup-code exchange."""

    GRANTED = "granted"
    REJECTED = "rejected"
    SETUP_CLOSED = "setup-closed"
    RATE_LIMITED = "rate-limited"


@dataclass(frozen=True, slots=True)
class BootstrapOperatorGrant:
    """Short-lived opaque grant created by the deployment-owned authority."""

    opaque_session: str = field(repr=False, compare=False)
    expires_in_seconds: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.opaque_session, str)
            or _OPAQUE_GRANT_PATTERN.fullmatch(self.opaque_session) is None
            or type(self.expires_in_seconds) is not int
            or not 1 <= self.expires_in_seconds <= 900
        ):
            raise ValueError("bootstrap grant must be opaque and short-lived")


@dataclass(frozen=True, slots=True)
class BootstrapAuthorizationDecision:
    """Finite authorization result; a grant exists only for the granted status."""

    status: BootstrapAuthorizationStatus
    grant: BootstrapOperatorGrant | None = None
    retry_after_ms: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, BootstrapAuthorizationStatus):
            raise ValueError("bootstrap authorization status is invalid")
        if (self.status is BootstrapAuthorizationStatus.GRANTED) != (
            self.grant is not None
        ):
            raise ValueError("bootstrap grant and decision status are inconsistent")
        if (self.status is BootstrapAuthorizationStatus.RATE_LIMITED) != (
            self.retry_after_ms is not None
        ):
            raise ValueError("retry delay is valid only for a rate-limited decision")
        if self.retry_after_ms is not None and (
            type(self.retry_after_ms) is not int
            or not 0 <= self.retry_after_ms <= 300_000
        ):
            raise ValueError("retry delay must be bounded")


class BootstrapAuthorizationAuthority(Protocol):
    """Atomically validate setup state/code, rate-limit, and issue a grant."""

    async def exchange(
        self, operator_code: str, client_address: str
    ) -> BootstrapAuthorizationDecision:
        """Exchange without logging or retaining the submitted code."""

    async def authorize_local(
        self, client_address: str
    ) -> BootstrapAuthorizationDecision:
        """Issue a grant only for a loopback client when local setup is enabled."""
