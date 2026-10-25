"""Build Incident Event V1 facts from explicit Runtime trigger facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlas_richie.contracts.incidents.v1 import (
    IncidentEventV1,
    IncidentSeverity,
    ResourcePressureFact,
    ResourcePressureMetric,
    ResponseTimeFact,
)

IncidentFact = ResourcePressureFact | ResponseTimeFact


class IncidentEventProducer:
    """Create typed, process-scoped events without evaluating alert policy.

    The host Runtime calls a creation method only after its own explicit
    decision that an incident fact occurred. Thresholds and severity are
    required inputs; this producer never samples metrics or invents policy.
    The returned immutable event can be retained and retried with the same
    ``event_id`` through :class:`IncidentEventReporter` after an uncertain
    delivery result.
    """

    __slots__ = ("_clock", "_epoch", "_event_id_factory")

    def __init__(
        self,
        process_epoch: UUID,
        *,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if type(process_epoch) is not UUID:
            raise TypeError("process_epoch must be a UUID")
        if not callable(event_id_factory):
            raise TypeError("event_id_factory must be callable")
        self._epoch = process_epoch
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_id_factory = event_id_factory

    def resource_pressure(
        self,
        *,
        metric: ResourcePressureMetric,
        value: float,
        threshold: float,
        severity: IncidentSeverity,
    ) -> IncidentEventV1:
        """Create an explicit CPU or memory-ratio pressure event."""
        fact = ResourcePressureFact(
            metric=metric,
            value=value,
            threshold=threshold,
        )
        if fact.value <= fact.threshold:
            raise ValueError("resource pressure value must exceed its threshold")
        return self._create(
            fact=fact,
            severity=severity,
        )

    def response_time(
        self,
        *,
        p95_ms: float,
        threshold_ms: float,
        severity: IncidentSeverity,
    ) -> IncidentEventV1:
        """Create an explicit p95 threshold event from a Runtime decision."""
        fact = ResponseTimeFact(p95_ms=p95_ms, threshold_ms=threshold_ms)
        if fact.p95_ms <= fact.threshold_ms:
            raise ValueError("response time p95 must exceed its threshold")
        return self._create(
            fact=fact,
            severity=severity,
        )

    def _create(
        self, *, fact: IncidentFact, severity: IncidentSeverity
    ) -> IncidentEventV1:
        event_id = self._event_id_factory()
        occurred_at = self._clock()
        if type(event_id) is not UUID:
            raise TypeError("event_id_factory must return a UUID")
        if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
            raise ValueError("incident clock must return a timezone-aware instant")
        if occurred_at.utcoffset() is None:
            raise ValueError("incident clock must return a timezone-aware instant")
        return IncidentEventV1(
            event_id=event_id,
            process_epoch=self._epoch,
            occurred_at=occurred_at.astimezone(UTC),
            severity=severity,
            fact=fact,
        )


__all__ = ["IncidentEventProducer"]
