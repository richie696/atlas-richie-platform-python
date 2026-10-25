"""Authenticated Reporter and durable event ports for Incident Event V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from atlas_richie.contracts.incidents.v1 import IncidentEventReceiptV1, IncidentEventV1

from .metrics_ingest_ports import VerifiedMetricsPeer


@dataclass(frozen=True, slots=True)
class IncidentReporterBinding:
    """Enrollment-derived identity and current process incarnation."""

    certificate_principal: str
    reporter_id: str
    environment_id: str
    app_id: str
    instance_id: str
    process_id: str
    current_epoch: str


class IncidentIngestErrorCode(StrEnum):
    """Stable internal error classifications for event ingestion."""

    IDENTITY_NOT_ENROLLED = "identity_not_enrolled"
    IDENTITY_MISMATCH = "identity_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class IncidentIngestError(RuntimeError):
    """Safe failure classification that never includes event or SQL contents."""

    def __init__(self, code: str) -> None:
        try:
            stable_code = IncidentIngestErrorCode(code)
        except ValueError:
            raise ValueError("unregistered incident ingest error")
        self.code = stable_code
        super().__init__(stable_code.value)


class IncidentReporterDirectory(Protocol):
    """Resolve verified TLS identity to an active, non-revoked Reporter."""

    async def resolve_incident_peer(
        self, peer: VerifiedMetricsPeer
    ) -> IncidentReporterBinding | None:
        """Return the current enrollment when this certificate is authorized."""


class IncidentEventHistoryPort(Protocol):
    """Commit an event and its receipt before allowing an ACK to be returned."""

    async def accept_incident_event(
        self,
        *,
        binding: IncidentReporterBinding,
        event: IncidentEventV1,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> IncidentEventReceiptV1:
        """Persist one exact event or return the prior receipt for a retry."""


__all__ = [
    "IncidentEventHistoryPort",
    "IncidentIngestError",
    "IncidentIngestErrorCode",
    "IncidentReporterBinding",
    "IncidentReporterDirectory",
]
