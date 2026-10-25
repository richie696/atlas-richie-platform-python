"""Ports and stable failures for authenticated publication-receipt ingestion."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from atlas_richie.contracts.rules.publication_receipt import RulePublicationReceiptV1

from .metrics_ingest_ports import VerifiedMetricsPeer


class PublicationReceiptIngestErrorCode(StrEnum):
    """Sanitized Collector rejection categories exposed by the HTTP adapter."""

    IDENTITY_NOT_ENROLLED = "identity_not_enrolled"
    IDENTITY_REVOKED = "identity_revoked"
    INVALID_EPOCH = "invalid_epoch"
    STALE_SEQUENCE = "stale_sequence"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    SCOPE_MISMATCH = "scope_mismatch"
    PUBLICATION_NOT_FOUND = "publication_not_found"
    TARGET_MISMATCH = "target_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class PublicationReceiptIngestError(RuntimeError):
    """Safe error classification that contains no request, identity, or SQL data."""

    def __init__(self, code: PublicationReceiptIngestErrorCode) -> None:
        if not isinstance(code, PublicationReceiptIngestErrorCode):
            raise TypeError("publication receipt error code must use its enum")
        self.code = code
        super().__init__(code.value)


class PublicationReceiptInboxPort(Protocol):
    """Commit one authenticated receipt and outbox fact before allowing ACK."""

    async def accept(
        self,
        *,
        peer: VerifiedMetricsPeer,
        receipt: RulePublicationReceiptV1,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> None:
        """Atomically verify authority, deduplicate, persist inbox, and enqueue."""


__all__ = [
    "PublicationReceiptInboxPort",
    "PublicationReceiptIngestError",
    "PublicationReceiptIngestErrorCode",
]
