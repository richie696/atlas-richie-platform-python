"""Consumer-owned identity and durable-history contracts for Metrics V2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from atlas_richie.contracts.reporting.v2 import MetricsReceipt, MetricsSnapshot


@dataclass(frozen=True, slots=True)
class VerifiedMetricsPeer:
    """Certificate identity extracted only from a verified mutual-TLS session.

    The ASGI TLS adapter must construct this value from the actual TLS peer
    certificate after handshake validation. Request headers and body fields
    are never accepted as certificate identity.
    """

    certificate_sha256: str


@dataclass(frozen=True, slots=True)
class MetricsReporterBinding:
    """Enrolled process identity and its authorization scope."""

    certificate_principal: str
    certificate_sha256: str
    reporter_id: str
    environment_id: str
    app_id: str
    instance_id: str
    process_id: str


class MetricsIngestErrorCode(StrEnum):
    """Stable internal classifications mapped to the Collector wire errors."""

    IDENTITY_NOT_ENROLLED = "identity_not_enrolled"
    IDENTITY_REVOKED = "identity_revoked"
    IDENTITY_MISMATCH = "identity_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    STALE_SEQUENCE = "stale_sequence"
    INVALID_EPOCH = "invalid_epoch"
    ELAPSED_TIME_REGRESSION = "elapsed_time_regression"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class MetricsIngestError(RuntimeError):
    """Safe ingest rejection without raw body, SQL error, or certificate data."""

    def __init__(self, code: str) -> None:
        try:
            stable_code = MetricsIngestErrorCode(code)
        except ValueError:
            raise ValueError("unregistered Metrics V2 ingest error")
        self.code = stable_code
        super().__init__(stable_code.value)


class MetricsReporterDirectory(Protocol):
    """Resolve a TLS-verified certificate fingerprint to active enrollment."""

    async def resolve_certificate(
        self, certificate_sha256: str
    ) -> MetricsReporterBinding | None:
        """Return one active enrolled process binding, if the certificate is known."""


class MetricsHistoryPort(Protocol):
    """Atomically persist exact accepted bytes, receipt, and reporter baseline."""

    async def accept_snapshot(
        self,
        *,
        binding: MetricsReporterBinding,
        snapshot: MetricsSnapshot,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> MetricsReceipt:
        """Commit a snapshot and return only its durable receipt."""


__all__ = [
    "MetricsHistoryPort",
    "MetricsIngestError",
    "MetricsIngestErrorCode",
    "MetricsReporterBinding",
    "MetricsReporterDirectory",
    "VerifiedMetricsPeer",
]
