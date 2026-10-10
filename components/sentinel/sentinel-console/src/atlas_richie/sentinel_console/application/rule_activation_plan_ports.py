"""Consumer-owned ports for reading persisted rule activation schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain.rule_activation_plans import (
    RuleActivationPlan,
    RuleActivationPlanCollection,
    RuleActivationPlanState,
)
from ..domain.utc_time import is_wire_utc_millisecond_instant
from .mutate_rule_set import RuleOperationRejection


@dataclass(frozen=True, slots=True)
class RuleActivationPlanClaim:
    """One leased, fenced plan phase selected by a scheduler worker."""

    plan: RuleActivationPlan
    claim_token: str
    lease_expires_at: datetime
    attempt: int

    def __post_init__(self) -> None:
        if not isinstance(self.plan, RuleActivationPlan):
            raise ValueError("activation plan claim must contain a plan")
        if self.plan.state not in {
            RuleActivationPlanState.ACTIVATING,
            RuleActivationPlanState.RESTORING,
        }:
            raise ValueError("activation plan claim state is not executable")
        if not isinstance(self.claim_token, str) or not self.claim_token.strip():
            raise ValueError("activation plan claim token is invalid")
        if not is_wire_utc_millisecond_instant(self.lease_expires_at):
            raise ValueError("activation plan lease expiry is invalid")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("activation plan claim attempt is invalid")


class RuleActivationPlanReader(Protocol):
    """Read the complete bounded schedule snapshot for one binding."""

    async def read_rule_activation_plans(
        self, binding_id: str
    ) -> RuleActivationPlanCollection:
        """Return only plans owned by the requested binding."""


class RuleActivationPlanWorkQueue(Protocol):
    """Claim due durable plan phases with database-backed fencing."""

    async def claim_due(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int = 1,
    ) -> tuple[RuleActivationPlanClaim, ...]:
        """Claim due activation/restoration phases or expired in-flight leases."""

    async def renew_claim(
        self,
        claim: RuleActivationPlanClaim,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RuleActivationPlanClaim:
        """Renew exactly the current claim; stale or expired tokens conflict."""

    async def associate_publication(
        self,
        claim: RuleActivationPlanClaim,
        publication_id: str,
        *,
        now: datetime,
    ) -> RuleActivationPlanClaim:
        """Idempotently associate the current phase with one durable publication."""

    async def complete_phase(
        self, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> RuleActivationPlan:
        """Finish a phase only after its exact publication read-back succeeded."""

    async def block_claim(
        self, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> RuleActivationPlan:
        """Move the exact current execution into blocked and release its lease."""


class ScheduledPublicationState(StrEnum):
    """Durable publication operation state observed by the plan scheduler."""

    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ScheduledPublicationEnqueue:
    """Idempotent result of ensuring one plan-phase publication exists."""

    state: ScheduledPublicationState
    publication_id: str | None
    reason: RuleOperationRejection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ScheduledPublicationState):
            raise ValueError("scheduled publication state is unsupported")
        if self.publication_id is not None and (
            not isinstance(self.publication_id, str) or not self.publication_id.strip()
        ):
            raise ValueError("scheduled publication identity is invalid")
        if self.state is ScheduledPublicationState.REJECTED:
            if self.reason is None or self.publication_id is not None:
                raise ValueError("rejected scheduled publication needs a reason")
        elif self.publication_id is None or self.reason is not None:
            raise ValueError("accepted scheduled publication identity is invalid")


class RuleActivationPlanPublicationEnqueuer(Protocol):
    """Ensure one phase's publish operation exists at its stable plan identity."""

    async def enqueue_scheduled_publication(
        self, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> ScheduledPublicationEnqueue:
        """Create or recover the deterministic operation without a browser session."""


class RuleActivationPlanClaimConflict(RuntimeError):
    """The plan claim was lost, expired, or superseded by another worker."""


class RuleActivationPlanAuthorityUnavailable(RuntimeError):
    """The scheduler authority cannot return trustworthy schedule facts."""


class RuleActivationPlanNotFound(LookupError):
    """The requested rule binding is not visible to the current authority."""


class RuleActivationPlanRateLimited(RuntimeError):
    """The schedule authority declined a read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("rule activation plan read rate limited")
