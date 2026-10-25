"""Validated runtime connection-health facts exposed by the Console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from .configuration_source import ConfigurationSourceProvider
from .wire_strings import is_bounded_wire_identifier

_MAX_IDENTIFIER_UNITS = 200
_MAX_CONNECTIONS = 1000
_MIN_SUPPORTED_UTC_YEAR = 1970


class ConnectionKind(StrEnum):
    """Independent backend links shown by the system-observation page."""

    CONFIG_CENTER = "config-center"
    METRICS_BACKEND = "metrics-backend"
    REPORTING_COLLECTOR = "reporting-collector"


class ConnectionState(StrEnum):
    """Finite result of a server-side connection observation."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNCONFIGURED = "unconfigured"
    UNKNOWN = "unknown"


class ConnectionCapability(StrEnum):
    """Capabilities that were verified by the source-side probe."""

    READ = "read"
    CONDITIONAL_WRITE = "conditional-write"
    WATCH = "watch"
    QUERY_METRICS = "query-metrics"
    INGEST = "ingest"


class ConnectionFailureReason(StrEnum):
    """Redacted probe failure categories; arbitrary exception text is excluded."""

    NETWORK = "network"
    AUTHENTICATION = "authentication"
    UNSUPPORTED = "unsupported"
    NOT_CONFIGURED = "not-configured"
    NO_PROBE = "no-probe"


def _valid_identifier(value: str) -> bool:
    return is_bounded_wire_identifier(value, _MAX_IDENTIFIER_UNITS)


def _valid_instant(value: datetime) -> bool:
    return (
        value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
    )


def _valid_latency(value: float) -> bool:
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return False
    try:
        return isfinite(value) and value >= 0
    except OverflowError:
        return False


@dataclass(frozen=True, slots=True)
class ConnectionObservation:
    """One server-side probe result with no raw endpoint or credential fields."""

    id: str
    kind: ConnectionKind
    source_id: str | None
    provider: ConfigurationSourceProvider | None
    state: ConnectionState
    checked_at: datetime | None
    expires_at: datetime | None
    latency_ms: float | None
    capabilities: tuple[ConnectionCapability, ...]
    reason: ConnectionFailureReason | None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _valid_identifier(self.id):
            raise ValueError("connection observation identity is invalid")
        if not isinstance(self.kind, ConnectionKind):
            raise ValueError("connection observation kind is not supported")
        if not isinstance(self.state, ConnectionState):
            raise ValueError("connection observation state is not supported")
        if not isinstance(self.capabilities, tuple) or any(
            not isinstance(value, ConnectionCapability) for value in self.capabilities
        ):
            raise ValueError("connection capabilities must be a finite tuple")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("connection capabilities must be unique")
        if self.provider is not None and not isinstance(
            self.provider, ConfigurationSourceProvider
        ):
            raise ValueError("configuration provider is not supported")
        if self.reason is not None and not isinstance(
            self.reason, ConnectionFailureReason
        ):
            raise ValueError("connection failure reason is not supported")
        self._validate_source_identity()
        self._validate_probe_times()
        if self.latency_ms is not None and not _valid_latency(self.latency_ms):
            raise ValueError("connection latency must be a non-negative number")
        if self.state is ConnectionState.AVAILABLE and (
            self.checked_at is None
            or self.latency_ms is None
            or self.reason is not None
        ):
            raise ValueError("available connection requires a successful probe")

    def _validate_source_identity(self) -> None:
        if self.kind is ConnectionKind.CONFIG_CENTER:
            if self.source_id is None:
                if (
                    self.provider is not None
                    or self.state is not ConnectionState.UNCONFIGURED
                ):
                    raise ValueError(
                        "unregistered configuration center is unconfigured"
                    )
            elif (
                not isinstance(self.source_id, str)
                or not _valid_identifier(self.source_id)
                or self.provider is None
            ):
                raise ValueError("registered configuration center needs safe identity")
        elif self.source_id is not None or self.provider is not None:
            raise ValueError("non-configuration connections cannot name a source")

    def _validate_probe_times(self) -> None:
        if self.checked_at is None:
            if (
                self.expires_at is not None
                or self.latency_ms is not None
                or self.state
                not in (ConnectionState.UNKNOWN, ConnectionState.UNCONFIGURED)
            ):
                raise ValueError("unprobed connection cannot claim health or expiry")
            return
        if (
            not isinstance(self.checked_at, datetime)
            or not _valid_instant(self.checked_at)
            or self.expires_at is None
            or not isinstance(self.expires_at, datetime)
            or not _valid_instant(self.expires_at)
            or self.expires_at < self.checked_at
        ):
            raise ValueError("connection probe timestamps are invalid")


@dataclass(frozen=True, slots=True)
class SystemConnectionsSnapshot:
    """A bounded server read; missing categories remain absent, never healthy."""

    as_of: datetime
    items: tuple[ConnectionObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime) or not _valid_instant(self.as_of):
            raise ValueError("connection snapshot time must be a valid aware instant")
        if not isinstance(self.items, tuple) or len(self.items) > _MAX_CONNECTIONS:
            raise ValueError("connection snapshot must be a bounded tuple")
        if any(not isinstance(item, ConnectionObservation) for item in self.items):
            raise ValueError("connection snapshot items are invalid")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("connection observation identities must be unique")
        if any(
            item.checked_at is not None and item.checked_at > self.as_of
            or item.expires_at is not None and item.expires_at < item.checked_at
            for item in self.items
        ):
            raise ValueError("connection observation times contradict snapshot time")
