"""Negotiate the independently versioned Rule Load Observation protocol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..domain.protocol_negotiations import (
    RULE_LOAD_OBSERVATION_V1,
    NegotiatedCompatibility,
    ProtocolNegotiation,
)
from .metrics_ingest_ports import VerifiedMetricsPeer
from .negotiate_agent_reporting import ProtocolNegotiationIdentityUnavailable
from .protocol_negotiation_ports import RuleLoadObservationNegotiationStore

SUPPORTED_RULE_LOAD_OBSERVATION_VERSIONS = (RULE_LOAD_OBSERVATION_V1,)


class NegotiateRuleLoadObservation:
    """Persist only the authenticated Runtime↔Collector negotiation fact."""

    def __init__(
        self,
        store: RuleLoadObservationNegotiationStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, peer: VerifiedMetricsPeer | None, runtime_version: str
    ) -> ProtocolNegotiation:
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
        supported = SUPPORTED_RULE_LOAD_OBSERVATION_VERSIONS
        compatibility = (
            NegotiatedCompatibility.COMPATIBLE
            if runtime_version in supported
            else NegotiatedCompatibility.INCOMPATIBLE
        )
        return await self._store.accept_rule_load_observation_negotiation(
            peer,
            runtime_version=runtime_version,
            collector_supported=supported,
            compatibility=compatibility,
            observed_at=observed_at.astimezone(UTC),
        )


__all__ = [
    "SUPPORTED_RULE_LOAD_OBSERVATION_VERSIONS",
    "NegotiateRuleLoadObservation",
]
