"""Bounded leased-work contracts for projecting Collector receipt facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from atlas_richie.contracts.rules.publication_receipt import RulePublicationReceiptV1


@dataclass(frozen=True, slots=True)
class PublicationReceiptProjectionClaim:
    """One immutable inbox fact under a fenced outbox lease."""

    receipt: RulePublicationReceiptV1
    received_at: datetime
    body_sha256: str
    lease_token: str
    attempt: int


class PublicationReceiptProjectionRejected(RuntimeError):
    """Permanent sanitized projection rejection suitable for parking."""

    def __init__(self, code: str) -> None:
        if code not in {
            "identity_revoked",
            "stale_epoch",
            "scope_mismatch",
            "publication_not_found",
            "target_mismatch",
            "digest_mismatch",
            "stale_sequence",
            "idempotency_conflict",
            "invalid_inbox",
        }:
            raise ValueError("unregistered projection rejection code")
        self.code = code
        super().__init__(code)


class PublicationReceiptProjectionUnavailable(RuntimeError):
    """Transient SQL/authority failure; the claim must be released for retry."""

    def __init__(self) -> None:
        super().__init__("publication receipt projection unavailable")


class PublicationReceiptProjectionQueue(Protocol):
    """Claim receipts and advance their SQL read-model delivery state."""

    async def claim_ready(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> tuple[PublicationReceiptProjectionClaim, ...]: ...

    async def project(
        self, claim: PublicationReceiptProjectionClaim, *, now: datetime
    ) -> None:
        """Commit one receipt projection; safe to call again after a lost ACK."""

    async def mark_delivered(
        self, claim: PublicationReceiptProjectionClaim, *, now: datetime
    ) -> None: ...

    async def park(
        self,
        claim: PublicationReceiptProjectionClaim,
        *,
        rejection_code: str,
        now: datetime,
    ) -> None: ...

    async def release(
        self,
        claim: PublicationReceiptProjectionClaim,
        *,
        available_at: datetime,
        now: datetime,
    ) -> None: ...


__all__ = [
    "PublicationReceiptProjectionClaim",
    "PublicationReceiptProjectionQueue",
    "PublicationReceiptProjectionRejected",
    "PublicationReceiptProjectionUnavailable",
]
