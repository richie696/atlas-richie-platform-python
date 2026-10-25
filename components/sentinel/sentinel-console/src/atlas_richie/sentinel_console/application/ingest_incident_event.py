"""Authenticate, validate, and durably accept one Incident Event V1 fact."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from atlas_richie.contracts.incidents.v1 import (
    IncidentEventReceiptV1,
    IncidentProtocolError,
    IncidentProtocolErrorCode,
    decode_incident_event,
)

from .incident_ingest_ports import (
    IncidentEventHistoryPort,
    IncidentIngestError,
    IncidentIngestErrorCode,
    IncidentReporterDirectory,
)
from .metrics_ingest_ports import VerifiedMetricsPeer

MAX_INCIDENT_EVENT_BODY_BYTES = 16 * 1024


class IngestIncidentEvent:
    """Orchestrate verified identity, strict event decoding, and durable ACK."""

    def __init__(
        self,
        reporter_directory: IncidentReporterDirectory,
        history: IncidentEventHistoryPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reporter_directory = reporter_directory
        self._history = history
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, peer: VerifiedMetricsPeer | None, body: bytes
    ) -> IncidentEventReceiptV1:
        """Return only a durable receipt for the current authenticated process."""
        if peer is None or not isinstance(peer, VerifiedMetricsPeer):
            raise IncidentIngestError(IncidentIngestErrorCode.IDENTITY_NOT_ENROLLED)
        if not isinstance(body, bytes) or len(body) > MAX_INCIDENT_EVENT_BODY_BYTES:
            raise IncidentProtocolError(IncidentProtocolErrorCode.PAYLOAD_TOO_LARGE)
        binding = await self._reporter_directory.resolve_incident_peer(peer)
        if binding is None:
            raise IncidentIngestError(IncidentIngestErrorCode.IDENTITY_NOT_ENROLLED)
        event = decode_incident_event(body)
        if str(event.process_epoch) != binding.current_epoch:
            raise IncidentIngestError(IncidentIngestErrorCode.IDENTITY_MISMATCH)
        received_at = self._clock()
        if (
            not isinstance(received_at, datetime)
            or received_at.tzinfo is None
            or received_at.utcoffset() != UTC.utcoffset(received_at)
        ):
            raise RuntimeError("Collector clock must return an aware UTC instant")
        return await self._history.accept_incident_event(
            binding=binding,
            event=event,
            body=body,
            body_sha256=hashlib.sha256(body).hexdigest(),
            received_at=received_at.astimezone(UTC),
        )


__all__ = ["MAX_INCIDENT_EVENT_BODY_BYTES", "IngestIncidentEvent"]
