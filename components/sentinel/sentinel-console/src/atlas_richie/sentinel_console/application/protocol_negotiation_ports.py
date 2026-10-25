"""Consumer-owned ports for authenticated protocol negotiation facts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.protocol_negotiations import (
    NegotiatedCompatibility,
    ProtocolNegotiation,
    ProtocolNegotiationPage,
)
from .metrics_ingest_ports import VerifiedMetricsPeer


class ProtocolNegotiationStore(Protocol):
    """Persist and read the latest verified negotiation for enrolled workers."""

    async def accept_agent_reporting_negotiation(
        self,
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Persist the exchange before the Collector sends its response."""

    async def read_agent_reporting_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        """Return current enrolled worker identities, including unknown handshakes."""


class AgentReportingNegotiationReader(Protocol):
    """Read-only page of per-worker negotiation facts for the Dashboard."""

    async def read_agent_reporting_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        """Return current enrolled worker identities, including unknown handshakes."""


class IncidentEventNegotiationReader(Protocol):
    """Read independently authenticated Incident Event negotiations."""

    async def read_incident_event_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        """Return current enrolled workers and Incident Event compatibility facts."""


class IncidentEventNegotiationStore(Protocol):
    """Persist/read the independently versioned Incident Event negotiation."""

    async def accept_incident_event_negotiation(
        self,
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Persist the authenticated Incident Event exchange before response."""

    async def read_incident_event_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        """Return enrolled workers with unknown or last negotiated status."""


class RuleLoadObservationNegotiationStore(Protocol):
    """Persist the actual authenticated Rule Load Observation exchange."""

    async def accept_rule_load_observation_negotiation(
        self,
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Persist this protocol boundary before acknowledging negotiation."""


__all__ = [
    "AgentReportingNegotiationReader",
    "IncidentEventNegotiationReader",
    "IncidentEventNegotiationStore",
    "ProtocolNegotiationStore",
    "RuleLoadObservationNegotiationStore",
]
