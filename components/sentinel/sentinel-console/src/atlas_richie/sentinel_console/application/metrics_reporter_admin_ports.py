"""Management boundary for durable Metrics V2 reporter enrollment."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .metrics_ingest_ports import MetricsReporterBinding


class MetricsReporterAdminErrorCode(StrEnum):
    """Stable classifications for rejected reporter management operations."""

    INVALID_BINDING = "invalid_binding"
    IDENTITY_CONFLICT = "identity_conflict"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class MetricsReporterAdminError(RuntimeError):
    """Safe operator-facing error without SQL or certificate material."""

    def __init__(self, code: MetricsReporterAdminErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class MetricsReporterAdministration(Protocol):
    """Persist active bindings and revoke them without storing private keys."""

    async def enroll_reporter(
        self, binding: MetricsReporterBinding
    ) -> MetricsReporterBinding:
        """Create a binding or return an identical active binding idempotently."""

    async def revoke_reporter(
        self, certificate_principal: str, revoked_at: datetime
    ) -> bool:
        """Revoke a known binding idempotently; return false when unknown."""


__all__ = [
    "MetricsReporterAdminError",
    "MetricsReporterAdminErrorCode",
    "MetricsReporterAdministration",
]
