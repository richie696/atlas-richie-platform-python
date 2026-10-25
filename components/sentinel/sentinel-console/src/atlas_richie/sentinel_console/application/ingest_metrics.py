"""Validate authenticated Metrics V2 input and request durable acceptance."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from atlas_richie.contracts.reporting.v2 import (
    MetricsReceipt,
    MetricsV2ProtocolError,
    decode_metrics_snapshot,
)

from .metrics_ingest_ports import (
    MetricsHistoryPort,
    MetricsIngestError,
    MetricsIngestErrorCode,
    MetricsReporterDirectory,
    VerifiedMetricsPeer,
)

MAX_METRICS_BODY_BYTES = 65_536


class IngestMetrics:
    """Orchestrate TLS enrollment, strict decode, and commit-before-ACK storage."""

    def __init__(
        self,
        reporter_directory: MetricsReporterDirectory,
        history: MetricsHistoryPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reporter_directory = reporter_directory
        self._history = history
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, peer: VerifiedMetricsPeer | None, body: bytes
    ) -> MetricsReceipt:
        """Accept exact request bytes only when TLS identity and payload agree."""
        if peer is None or not isinstance(peer, VerifiedMetricsPeer):
            raise MetricsIngestError(MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED)
        if (
            not isinstance(body, bytes)
            or not body
            or len(body) > MAX_METRICS_BODY_BYTES
        ):
            raise MetricsV2ProtocolError("payload_too_large")
        binding = await self._reporter_directory.resolve_certificate(
            peer.certificate_sha256
        )
        if binding is None:
            raise MetricsIngestError(MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED)
        snapshot = decode_metrics_snapshot(body)
        if snapshot.reporter_id != binding.reporter_id:
            raise MetricsIngestError(MetricsIngestErrorCode.IDENTITY_MISMATCH)
        received_at = self._clock()
        if (
            not isinstance(received_at, datetime)
            or received_at.tzinfo is None
            or received_at.utcoffset() != UTC.utcoffset(received_at)
        ):
            raise RuntimeError("Collector clock must return an aware UTC instant")
        return await self._history.accept_snapshot(
            binding=binding,
            snapshot=snapshot,
            body=body,
            body_sha256=hashlib.sha256(body).hexdigest(),
            received_at=received_at.astimezone(UTC),
        )


__all__ = ["MAX_METRICS_BODY_BYTES", "IngestMetrics"]
