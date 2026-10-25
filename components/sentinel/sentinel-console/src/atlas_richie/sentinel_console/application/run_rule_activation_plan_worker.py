"""Coordinate durable activation-plan claims with the existing publish outbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable

from ..domain.rule_activation_plans import RuleActivationPlanState
from ..domain.utc_time import is_wire_utc_millisecond_instant
from .rule_activation_plan_ports import (
    RuleActivationPlanPublicationEnqueuer,
    RuleActivationPlanWorkQueue,
    ScheduledPublicationState,
)

_MAX_LEASE = timedelta(minutes=5)
_MAX_BATCH = 100


class RuleActivationPlanWorkerOutcome(StrEnum):
    """Observable disposition of each claimed plan phase."""

    ENQUEUED = "enqueued"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class RunRuleActivationPlanWorker:
    """Enqueue or reconcile plan phases; provider effects stay in publish worker."""

    def __init__(
        self,
        *,
        work_queue: RuleActivationPlanWorkQueue,
        publication_enqueuer: RuleActivationPlanPublicationEnqueuer,
        clock: Callable[[], datetime],
        lease_duration: timedelta = timedelta(seconds=60),
    ) -> None:
        if not timedelta(milliseconds=1) <= lease_duration <= _MAX_LEASE:
            raise ValueError("activation plan worker lease duration is invalid")
        if not callable(clock):
            raise ValueError("activation plan worker clock is invalid")
        self._work_queue = work_queue
        self._publication_enqueuer = publication_enqueuer
        self._clock = clock
        self._lease_duration = lease_duration

    async def run_once(
        self, *, limit: int = 1
    ) -> tuple[RuleActivationPlanWorkerOutcome, ...]:
        """Claim due phases, ensure their stable publication, and close verified work."""
        if type(limit) is not int or not 1 <= limit <= _MAX_BATCH:
            raise ValueError("activation plan worker limit is invalid")
        now = _millisecond_instant(self._clock())
        claims = await self._work_queue.claim_due(
            now=now,
            lease_expires_at=now + self._lease_duration,
            limit=limit,
        )
        outcomes: list[RuleActivationPlanWorkerOutcome] = []
        for claimed in claims:
            claim_time = _millisecond_instant(self._clock())
            claim = await self._work_queue.renew_claim(
                claimed,
                now=claim_time,
                lease_expires_at=claim_time + self._lease_duration,
            )
            publication = await self._publication_enqueuer.enqueue_scheduled_publication(
                claim, now=_millisecond_instant(self._clock())
            )
            current_time = _millisecond_instant(self._clock())
            if publication.state is ScheduledPublicationState.REJECTED:
                await self._work_queue.block_claim(claim, now=current_time)
                outcomes.append(RuleActivationPlanWorkerOutcome.BLOCKED)
                continue

            if publication.publication_id is None:
                raise RuntimeError("accepted scheduled publication has no identity")

            associated = await self._work_queue.associate_publication(
                claim, publication.publication_id, now=current_time
            )
            if publication.state is ScheduledPublicationState.COMPLETED:
                await self._work_queue.complete_phase(
                    associated, now=_millisecond_instant(self._clock())
                )
                outcomes.append(RuleActivationPlanWorkerOutcome.COMPLETED)
            else:
                outcomes.append(RuleActivationPlanWorkerOutcome.ENQUEUED)
        return tuple(outcomes)


def _millisecond_instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("activation plan worker clock must return an aware instant")
    normalized = value.astimezone(UTC).replace(microsecond=value.microsecond // 1_000 * 1_000)
    if not is_wire_utc_millisecond_instant(normalized):
        raise ValueError("activation plan worker clock returned an invalid instant")
    return normalized


__all__ = ["RuleActivationPlanWorkerOutcome", "RunRuleActivationPlanWorker"]
