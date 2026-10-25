"""Authenticated, per-worker Runtime-to-Collector protocol facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .wire_strings import is_bounded_wire_identifier

MAX_PROTOCOL_VERSION_LENGTH = 200
MAX_PROTOCOL_OBSERVATIONS_PAGE_SIZE = 100
MAX_PROTOCOL_OBSERVATIONS_PAGE = 1_000_000
AGENT_REPORTING_V1 = "atlas-richie.reporting/v1"
INCIDENT_EVENTS_V1 = "atlas-richie.incident-events/v1"
RULE_LOAD_OBSERVATION_V1 = "atlas-richie.sentinel.rule-load-observation/v1"


class NegotiatedCompatibility(StrEnum):
    """Compatibility observed from an authenticated exchange."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProtocolNegotiation:
    """Runtime-declared active version and Collector capabilities for one worker."""

    certificate_principal: str
    reporter_id: str
    environment_id: str
    app_id: str
    instance_id: str
    process_id: str
    runtime_version: str | None
    collector_supported: tuple[str, ...]
    compatibility: NegotiatedCompatibility
    observed_at: datetime | None

    def __post_init__(self) -> None:
        for identity in (
            self.certificate_principal,
            self.reporter_id,
            self.environment_id,
            self.app_id,
            self.instance_id,
            self.process_id,
        ):
            if not is_bounded_wire_identifier(identity, 255):
                raise ValueError("protocol observation identity is invalid")
        if (
            not isinstance(self.collector_supported, tuple)
            or len(self.collector_supported) > 100
        ):
            raise ValueError("collector protocol versions are invalid")
        if any(
            not isinstance(version, str)
            or not is_bounded_wire_identifier(version, MAX_PROTOCOL_VERSION_LENGTH)
            for version in self.collector_supported
        ) or len(set(self.collector_supported)) != len(self.collector_supported):
            raise ValueError("collector protocol versions are invalid")
        if self.runtime_version is None:
            if (
                self.compatibility is not NegotiatedCompatibility.UNKNOWN
                or self.observed_at is not None
            ):
                raise ValueError("unobserved protocol must have unknown compatibility")
        elif (
            not is_bounded_wire_identifier(
                self.runtime_version, MAX_PROTOCOL_VERSION_LENGTH
            )
            or self.observed_at is None
            or self.compatibility is NegotiatedCompatibility.UNKNOWN
            or (self.runtime_version in self.collector_supported)
            != (self.compatibility is NegotiatedCompatibility.COMPATIBLE)
        ):
            raise ValueError("observed protocol negotiation is inconsistent")
        if self.observed_at is not None and (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("protocol observation time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ProtocolNegotiationPage:
    """Bounded page of currently enrolled worker protocol observations."""

    as_of: datetime
    page: int
    page_size: int
    total: int
    items: tuple[ProtocolNegotiation, ...]

    def __post_init__(self) -> None:
        if (
            self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
            or not isinstance(self.page, int)
            or isinstance(self.page, bool)
            or not 1 <= self.page <= MAX_PROTOCOL_OBSERVATIONS_PAGE
            or not isinstance(self.page_size, int)
            or isinstance(self.page_size, bool)
            or not 1 <= self.page_size <= MAX_PROTOCOL_OBSERVATIONS_PAGE_SIZE
            or not isinstance(self.total, int)
            or isinstance(self.total, bool)
            or self.total < 0
            or not isinstance(self.items, tuple)
            or len(self.items) > self.page_size
            or (self.page - 1) * self.page_size + len(self.items) > self.total
        ):
            raise ValueError("protocol observation page is invalid")
        identities = tuple(
            (item.environment_id, item.app_id, item.instance_id) for item in self.items
        )
        if len(set(identities)) != len(identities):
            raise ValueError("worker identities must be unique within a page")
        if any(
            item.observed_at and item.observed_at > self.as_of for item in self.items
        ):
            raise ValueError("protocol observation cannot be after snapshot time")


__all__ = [
    "AGENT_REPORTING_V1",
    "INCIDENT_EVENTS_V1",
    "MAX_PROTOCOL_OBSERVATIONS_PAGE",
    "MAX_PROTOCOL_OBSERVATIONS_PAGE_SIZE",
    "RULE_LOAD_OBSERVATION_V1",
    "NegotiatedCompatibility",
    "ProtocolNegotiation",
    "ProtocolNegotiationPage",
]
