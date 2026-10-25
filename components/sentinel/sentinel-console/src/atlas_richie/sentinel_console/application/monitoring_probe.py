"""Application-owned contract for read-only monitoring source probes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from ..domain.monitoring_sources import MonitoringSource


class MonitoringProbeConnection(StrEnum):
    """Finite network outcome for a monitoring source probe."""

    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


class MonitoringProbeQueryApi(StrEnum):
    """Whether the Prometheus-compatible query endpoint is usable."""

    AVAILABLE = "available"
    DENIED = "denied"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class MonitoringProbeProfile(StrEnum):
    """Whether the initial Node Exporter metric families are present."""

    SUPPORTED = "supported"
    MISSING_SAMPLES = "missing_samples"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class MonitoringProbeFailure(StrEnum):
    """Safe finite failure categories; provider messages never cross this port."""

    TARGET_REJECTED = "target_rejected"
    AUTHENTICATION = "authentication"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True, slots=True)
class MonitoringIdentityPreview:
    """Bounded aggregate counts for configured identity labels."""

    observed: int
    unique: int
    missing: int
    conflicting: int

    def __post_init__(self) -> None:
        values = (self.observed, self.unique, self.missing, self.conflicting)
        if any(
            type(value) is not int or value < 0 or value > 10_000 for value in values
        ):
            raise ValueError("monitoring identity counts are out of bounds")
        if self.unique + self.missing + self.conflicting > self.observed:
            raise ValueError("monitoring identity counts are inconsistent")


@dataclass(frozen=True, slots=True)
class MonitoringProbeResult:
    """Secret-free, finite result of one candidate source check."""

    connection: MonitoringProbeConnection
    query_api: MonitoringProbeQueryApi
    profile: MonitoringProbeProfile
    identity: MonitoringIdentityPreview
    failure: MonitoringProbeFailure | None = None


@dataclass(frozen=True, slots=True, repr=False)
class MonitoringProbeCredentials:
    """Short-lived resolved credentials; repr intentionally never exposes them."""

    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        basic_present = self.username is not None or self.password is not None
        bearer_present = self.bearer_token is not None
        if basic_present and (not self.username or self.password is None):
            raise ValueError("monitoring basic credentials are incomplete")
        if basic_present and bearer_present:
            raise ValueError("monitoring credentials must use one authentication mode")
        for value in (self.username, self.password, self.bearer_token):
            if value is not None and (
                not isinstance(value, str)
                or not value
                or len(value) > 4096
                or any(character in value for character in "\r\n\x00")
            ):
                raise ValueError("monitoring credential is invalid")


class MonitoringProbePort(Protocol):
    """Read-only capability requested by the monitoring-source use case."""

    async def probe(
        self,
        source: MonitoringSource,
        credentials: MonitoringProbeCredentials | None = None,
    ) -> MonitoringProbeResult: ...


class MonitoringCredentialReferenceResolver(Protocol):
    """Resolve an opaque deployment-owned reference without persisting its value."""

    async def resolve(self, reference: str) -> MonitoringProbeCredentials | None: ...


class MonitoringCredentialReferenceUnavailable(RuntimeError):
    """Deployment-owned monitoring credential reference authority is unavailable."""


__all__ = [
    "MonitoringCredentialReferenceResolver",
    "MonitoringCredentialReferenceUnavailable",
    "MonitoringIdentityPreview",
    "MonitoringProbeConnection",
    "MonitoringProbeCredentials",
    "MonitoringProbeFailure",
    "MonitoringProbePort",
    "MonitoringProbeProfile",
    "MonitoringProbeQueryApi",
    "MonitoringProbeResult",
]
