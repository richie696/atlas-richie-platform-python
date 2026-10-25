"""Record an authenticated Runtime-to-Collector Agent Reporting negotiation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..domain.protocol_negotiations import (
    AGENT_REPORTING_V1,
    NegotiatedCompatibility,
    ProtocolNegotiation,
)
from .metrics_ingest_ports import VerifiedMetricsPeer
from .protocol_negotiation_ports import ProtocolNegotiationStore

SUPPORTED_AGENT_REPORTING_VERSIONS = (AGENT_REPORTING_V1,)


class ProtocolNegotiationUnavailable(RuntimeError):
    """The Collector cannot establish or persist a trusted negotiation fact."""


class ProtocolNegotiationIdentityUnavailable(ProtocolNegotiationUnavailable):
    """The verified TLS peer is not an active enrolled Reporter."""


class NegotiateAgentReporting:
    """Negotiate only Agent Reporting; never infer another peer boundary."""

    def __init__(
        self,
        store: ProtocolNegotiationStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, peer: VerifiedMetricsPeer | None, runtime_version: str
    ) -> ProtocolNegotiation:
        """Store the verified exchange before returning its durable fact."""
        if peer is None or not isinstance(peer, VerifiedMetricsPeer):
            raise ProtocolNegotiationIdentityUnavailable(
                "reporter identity unavailable"
            )
        if not isinstance(runtime_version, str) or not runtime_version.strip():
            raise ValueError("runtime protocol version is invalid")
        observed_at = self._clock()
        if (
            not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.utcoffset() != UTC.utcoffset(observed_at)
        ):
            raise RuntimeError("Collector clock must return an aware UTC instant")
        supported = SUPPORTED_AGENT_REPORTING_VERSIONS
        compatibility = (
            NegotiatedCompatibility.COMPATIBLE
            if runtime_version in supported
            else NegotiatedCompatibility.INCOMPATIBLE
        )
        return await self._store.accept_agent_reporting_negotiation(
            peer,
            runtime_version=runtime_version,
            collector_supported=supported,
            compatibility=compatibility,
            observed_at=observed_at.astimezone(UTC),
        )


__all__ = [
    "SUPPORTED_AGENT_REPORTING_VERSIONS",
    "NegotiateAgentReporting",
    "ProtocolNegotiationIdentityUnavailable",
    "ProtocolNegotiationUnavailable",
]
