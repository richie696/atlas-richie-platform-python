"""Authenticate, validate, and durably accept Rule Load Observation V1."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from atlas_richie.contracts.rules.load_observation.v1 import (
    MAX_RULE_LOAD_OBSERVATION_BYTES,
    RuleLoadObservationV1,
    decode_rule_load_observation,
)

from .metrics_ingest_ports import VerifiedMetricsPeer
from .rule_load_observation_ingest_ports import (
    RuleLoadObservationInboxPort,
    RuleLoadObservationIngestError,
    RuleLoadObservationIngestErrorCode,
)


class IngestRuleLoadObservation:
    """Keep strict protocol decoding separate from SQL authority and storage."""

    def __init__(
        self,
        inbox: RuleLoadObservationInboxPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._inbox = inbox
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, peer: VerifiedMetricsPeer | None, body: bytes
    ) -> RuleLoadObservationV1:
        """Return only after exact bytes are authorized and durably committed."""
        if peer is None or not isinstance(peer, VerifiedMetricsPeer):
            raise RuleLoadObservationIngestError(
                RuleLoadObservationIngestErrorCode.IDENTITY_NOT_ENROLLED
            )
        observation = decode_rule_load_observation(body)
        received_at = self._clock()
        if (
            not isinstance(received_at, datetime)
            or received_at.tzinfo is None
            or received_at.utcoffset() != UTC.utcoffset(received_at)
        ):
            raise RuntimeError("Collector clock must return an aware UTC instant")
        await self._inbox.accept(
            peer=peer,
            observation=observation,
            body=body,
            body_sha256=hashlib.sha256(body).hexdigest(),
            received_at=received_at.astimezone(UTC),
        )
        return observation


__all__ = ["MAX_RULE_LOAD_OBSERVATION_BYTES", "IngestRuleLoadObservation"]
