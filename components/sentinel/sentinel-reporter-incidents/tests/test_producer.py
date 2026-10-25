from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from atlas_richie.contracts.incidents.v1 import (
    IncidentSeverity,
    ResourcePressureFact,
    ResourcePressureMetric,
    ResponseTimeFact,
)

from atlas_richie.sentinel_reporter_incidents import IncidentEventProducer

_EPOCH = UUID("3cf8a5b6-0126-45d7-9639-39159fc6b92e")
_EVENT_ID = UUID("0c79e702-95b7-4d22-8fdc-f5057e5b1090")


def test_resource_pressure_uses_explicit_inputs_epoch_and_utc_clock() -> None:
    producer = IncidentEventProducer(
        _EPOCH,
        clock=lambda: datetime(2026, 10, 15, 8, 0, tzinfo=timezone(timedelta(hours=8))),
        event_id_factory=lambda: _EVENT_ID,
    )

    event = producer.resource_pressure(
        metric=ResourcePressureMetric.CPU_RATIO,
        value=0.91,
        threshold=0.85,
        severity=IncidentSeverity.WARNING,
    )

    assert isinstance(event.fact, ResourcePressureFact)
    assert event.fact.metric is ResourcePressureMetric.CPU_RATIO
    assert event.fact.value == 0.91
    assert event.fact.threshold == 0.85
    assert event.process_epoch == _EPOCH
    assert event.event_id == _EVENT_ID
    assert event.occurred_at == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)


def test_response_time_event_preserves_caller_threshold_and_severity() -> None:
    producer = IncidentEventProducer(
        _EPOCH,
        clock=lambda: datetime(2026, 10, 15, tzinfo=UTC),
        event_id_factory=lambda: _EVENT_ID,
    )

    event = producer.response_time(
        p95_ms=125.0,
        threshold_ms=100.0,
        severity=IncidentSeverity.CRITICAL,
    )

    assert isinstance(event.fact, ResponseTimeFact)
    assert event.fact.p95_ms == 125.0
    assert event.fact.threshold_ms == 100.0
    assert event.severity is IncidentSeverity.CRITICAL


def test_producer_rejects_invalid_clock_and_event_identity() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        IncidentEventProducer(
            _EPOCH,
            clock=lambda: datetime(2026, 10, 15),
            event_id_factory=lambda: _EVENT_ID,
        ).response_time(
            p95_ms=125.0,
            threshold_ms=100.0,
            severity=IncidentSeverity.WARNING,
        )

    with pytest.raises(TypeError, match="return a UUID"):
        IncidentEventProducer(
            _EPOCH,
            clock=lambda: datetime(2026, 10, 15, tzinfo=UTC),
            event_id_factory=lambda: "not-a-uuid",  # type: ignore[return-value]
        ).response_time(
            p95_ms=125.0,
            threshold_ms=100.0,
            severity=IncidentSeverity.WARNING,
        )


def test_producer_rejects_non_uuid_process_epoch() -> None:
    with pytest.raises(TypeError, match="process_epoch must be a UUID"):
        IncidentEventProducer("epoch")  # type: ignore[arg-type]


@pytest.mark.parametrize("value,threshold", [(0.85, 0.85), (0.8, 0.85)])
def test_resource_pressure_requires_an_actual_threshold_crossing(
    value: float, threshold: float
) -> None:
    producer = IncidentEventProducer(_EPOCH)

    with pytest.raises(ValueError, match="must exceed its threshold"):
        producer.resource_pressure(
            metric=ResourcePressureMetric.CPU_RATIO,
            value=value,
            threshold=threshold,
            severity=IncidentSeverity.WARNING,
        )


@pytest.mark.parametrize("p95_ms,threshold_ms", [(100.0, 100.0), (90.0, 100.0)])
def test_response_time_requires_an_actual_threshold_crossing(
    p95_ms: float, threshold_ms: float
) -> None:
    producer = IncidentEventProducer(_EPOCH)

    with pytest.raises(ValueError, match="must exceed its threshold"):
        producer.response_time(
            p95_ms=p95_ms,
            threshold_ms=threshold_ms,
            severity=IncidentSeverity.WARNING,
        )
