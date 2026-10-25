"""Consume Collector rule-load outbox facts into the Console SQL read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .rule_load_observation_projection_ports import (
    RuleLoadObservationProjectionQueue,
    RuleLoadObservationProjectionRejected,
    RuleLoadObservationProjectionUnavailable,
)

_MAX_BATCH_SIZE = 100
_MAX_LEASE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class RuleLoadObservationProjectionBatchResult:
    """Durable state transitions performed during one bounded poll."""

    claimed: int
    delivered: int
    parked: int
    retried: int


class RunRuleLoadObservationProjectionWorker:
    """Project accepted observations with lease fencing and retry-safe writes."""

    def __init__(self, queue: RuleLoadObservationProjectionQueue) -> None:
        self._queue = queue

    async def run_once(
        self,
        *,
        now: datetime,
        lease_duration: timedelta = timedelta(seconds=30),
        batch_size: int = 10,
    ) -> RuleLoadObservationProjectionBatchResult:
        _validate_limits(now, lease_duration, batch_size)
        now = now.astimezone(UTC)
        claims = await self._queue.claim_ready(
            now=now,
            lease_expires_at=now + lease_duration,
            limit=batch_size,
        )
        delivered = parked = retried = 0
        for claim in claims:
            try:
                await self._queue.project(claim, now=now)
            except RuleLoadObservationProjectionRejected as error:
                await self._queue.park(
                    claim, rejection_code=error.code, now=now
                )
                parked += 1
                continue
            except RuleLoadObservationProjectionUnavailable:
                await self._queue.release(
                    claim,
                    available_at=now + _retry_delay(claim.attempt),
                    now=now,
                )
                retried += 1
                continue
            try:
                await self._queue.mark_delivered(claim, now=now)
            except RuleLoadObservationProjectionUnavailable:
                await self._queue.release(
                    claim,
                    available_at=now + _retry_delay(claim.attempt),
                    now=now,
                )
                retried += 1
                continue
            delivered += 1
        return RuleLoadObservationProjectionBatchResult(
            claimed=len(claims),
            delivered=delivered,
            parked=parked,
            retried=retried,
        )


def _validate_limits(
    now: datetime, lease_duration: timedelta, batch_size: int
) -> None:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() != UTC.utcoffset(now)
    ):
        raise ValueError("rule-load projection time must be UTC-aware")
    if (
        not isinstance(lease_duration, timedelta)
        or lease_duration <= timedelta(0)
        or lease_duration > _MAX_LEASE
    ):
        raise ValueError("rule-load projection lease is invalid")
    if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH_SIZE:
        raise ValueError("rule-load projection batch size is invalid")


def _retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(2 ** min(max(attempt - 1, 0), 6), 60))


__all__ = [
    "RuleLoadObservationProjectionBatchResult",
    "RunRuleLoadObservationProjectionWorker",
]
