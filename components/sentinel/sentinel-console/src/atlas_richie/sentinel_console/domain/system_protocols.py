"""Validated runtime protocol facts exposed by the Console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .wire_strings import is_bounded_wire_identifier

_MAX_IDENTIFIER_UNITS = 200
_MAX_SUPPORTED_VERSIONS = 100
_MIN_SUPPORTED_UTC_YEAR = 1970


class ProtocolBoundary(StrEnum):
    """Independent protocol boundaries known to the dashboard contract."""

    RULE_CONFIG = "rule-config"
    AGENT_REPORTING = "agent-reporting"
    CLUSTER_TOKEN = "cluster-token"


class ProtocolCompatibility(StrEnum):
    """Observed compatibility result; unknown is not treated as compatible."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


def _valid_identifier(value: str) -> bool:
    return is_bounded_wire_identifier(value, _MAX_IDENTIFIER_UNITS)


def _valid_instant(value: datetime) -> bool:
    return (
        value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
    )


@dataclass(frozen=True, slots=True)
class ProtocolObservation:
    """One protocol's supported versions and independently observed deployment facts."""

    kind: ProtocolBoundary
    supported: tuple[str, ...]
    active: str | None
    compatibility: ProtocolCompatibility
    observed_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProtocolBoundary):
            raise ValueError("protocol kind is not supported")
        if not isinstance(self.compatibility, ProtocolCompatibility):
            raise ValueError("protocol compatibility is not supported")
        if (
            not isinstance(self.supported, tuple)
            or len(self.supported) > _MAX_SUPPORTED_VERSIONS
        ):
            raise ValueError("supported protocol versions must be a bounded tuple")
        if any(
            not isinstance(version, str) or not _valid_identifier(version)
            for version in self.supported
        ):
            raise ValueError("supported protocol versions are invalid")
        if len(set(self.supported)) != len(self.supported):
            raise ValueError("supported protocol versions must be unique")
        if self.active is None:
            if self.compatibility is not ProtocolCompatibility.UNKNOWN:
                raise ValueError(
                    "unobserved active version must have unknown compatibility"
                )
        else:
            if (
                not isinstance(self.active, str)
                or not _valid_identifier(self.active)
                or self.observed_at is None
            ):
                raise ValueError(
                    "active protocol fact requires a version and observation time"
                )
            if (
                self.compatibility is not ProtocolCompatibility.UNKNOWN
                and (self.active in self.supported)
                != (self.compatibility is ProtocolCompatibility.COMPATIBLE)
            ):
                raise ValueError(
                    "protocol compatibility contradicts supported versions"
                )
        if self.observed_at is not None and (
            not isinstance(self.observed_at, datetime)
            or not _valid_instant(self.observed_at)
        ):
            raise ValueError("protocol observation time must be a valid aware instant")


@dataclass(frozen=True, slots=True)
class SystemProtocolsSnapshot:
    """A bounded authoritative read; omitted boundaries remain unobserved."""

    as_of: datetime
    items: tuple[ProtocolObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime) or not _valid_instant(self.as_of):
            raise ValueError("snapshot time must be a valid aware instant")
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, ProtocolObservation) for item in self.items
        ):
            raise ValueError("snapshot protocol observations must be a tuple")
        if len(self.items) > len(ProtocolBoundary):
            raise ValueError("snapshot contains too many protocol boundaries")
        if len({item.kind for item in self.items}) != len(self.items):
            raise ValueError("snapshot protocol boundaries must be unique")
        if any(
            item.observed_at is not None
            and item.observed_at > self.as_of
            for item in self.items
        ):
            raise ValueError("protocol observation cannot be after snapshot time")
