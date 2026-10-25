"""Ports and stable failures for authenticated rule-load observations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from atlas_richie.contracts.rules.load_observation.v1 import RuleLoadObservationV1

from .metrics_ingest_ports import VerifiedMetricsPeer


class RuleLoadObservationIngestErrorCode(StrEnum):
    """Safe Collector classifications for rule-load observation rejection."""

    IDENTITY_NOT_ENROLLED = "identity_not_enrolled"
    IDENTITY_REVOKED = "identity_revoked"
    INVALID_EPOCH = "invalid_epoch"
    STALE_SEQUENCE = "stale_sequence"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    SCOPE_MISMATCH = "scope_mismatch"
    BINDING_NOT_FOUND = "binding_not_found"
    PROFILE_MISMATCH = "profile_mismatch"
    STORAGE_UNAVAILABLE = "storage_unavailable"


class RuleLoadObservationIngestError(RuntimeError):
    """Sanitized storage or authorization rejection."""

    def __init__(self, code: RuleLoadObservationIngestErrorCode) -> None:
        if not isinstance(code, RuleLoadObservationIngestErrorCode):
            raise TypeError("rule-load ingest error must use its enum")
        self.code = code
        super().__init__(code.value)


class RuleLoadObservationInboxPort(Protocol):
    """Atomically authorize, deduplicate, persist and enqueue one observation."""

    async def accept(
        self,
        *,
        peer: VerifiedMetricsPeer,
        observation: RuleLoadObservationV1,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> None:
        """Commit the durable inbox/outbox transaction before returning."""


__all__ = [
    "RuleLoadObservationInboxPort",
    "RuleLoadObservationIngestError",
    "RuleLoadObservationIngestErrorCode",
]
