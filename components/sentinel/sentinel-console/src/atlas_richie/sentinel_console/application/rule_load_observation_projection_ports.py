"""Durable delivery contract for Console rule-load state projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from atlas_richie.contracts.rules.load_observation.v1 import RuleLoadObservationV1


@dataclass(frozen=True, slots=True)
class RuleLoadObservationProjectionClaim:
    """One immutable Collector fact fenced by an outbox lease."""

    observation: RuleLoadObservationV1
    received_at: datetime
    body_sha256: str
    lease_token: str
    attempt: int


class RuleLoadObservationProjectionRejected(RuntimeError):
    """Permanent projection rejection with a safe, registered reason."""

    def __init__(self, code: str) -> None:
        if code not in {
            "identity_revoked",
            "stale_epoch",
            "binding_unavailable",
            "scope_mismatch",
            "profile_mismatch",
            "invalid_inbox",
            "stale_sequence",
            "idempotency_conflict",
        }:
            raise ValueError("unregistered rule-load projection rejection")
        self.code = code
        super().__init__(code)


class RuleLoadObservationProjectionUnavailable(RuntimeError):
    """Transient storage failure; a claimed row should be retried."""

    def __init__(self) -> None:
        super().__init__("rule-load observation projection unavailable")


class RuleLoadObservationProjectionQueue(Protocol):
    """Claim durable facts and update the Console current-state projection."""

    async def claim_ready(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> tuple[RuleLoadObservationProjectionClaim, ...]: ...

    async def project(
        self, claim: RuleLoadObservationProjectionClaim, *, now: datetime
    ) -> None: ...

    async def mark_delivered(
        self, claim: RuleLoadObservationProjectionClaim, *, now: datetime
    ) -> None: ...

    async def park(
        self,
        claim: RuleLoadObservationProjectionClaim,
        *,
        rejection_code: str,
        now: datetime,
    ) -> None: ...

    async def release(
        self,
        claim: RuleLoadObservationProjectionClaim,
        *,
        available_at: datetime,
        now: datetime,
    ) -> None: ...


__all__ = [
    "RuleLoadObservationProjectionClaim",
    "RuleLoadObservationProjectionQueue",
    "RuleLoadObservationProjectionRejected",
    "RuleLoadObservationProjectionUnavailable",
]
