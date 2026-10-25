from datetime import UTC, datetime
from uuid import uuid4

import pytest
from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MAX_SAFE_INTEGER,
    METRICS_V2_MAX_RECORDS,
    CounterName,
    GaugeName,
    GaugeQuality,
)
from atlas_richie.sentinel.metrics.snapshot import LatencyHistogram, MetricSnapshot
from atlas_richie.sentinel.ports.system_metric_sampler import SystemSnapshot
from atlas_richie.sentinel.reporting import (
    HttpMetricSnapshot,
    MetricCapture,
    MetricCaptureSource,
)
from atlas_richie.sentinel_reporter_v2 import MetricsSnapshotBuilder

_NOW = datetime(2026, 10, 14, tzinfo=UTC)


def _histogram(
    bounds: tuple[int, ...] = HTTP_REQUEST_DURATION_BOUNDARIES_NS,
) -> LatencyHistogram:
    counts = tuple(0 for _ in range(len(bounds) + 1))
    return LatencyHistogram(bounds, counts, 0, 0, None, None)


def _entry(resource: str, admitted: int, blocked: int) -> MetricCapture:
    return MetricCapture(
        MetricCaptureSource.ENTRY,
        MetricSnapshot(
            at_ns=1,
            labels={"resource": resource, "outcome": "success"},
            admitted=admitted,
            blocked=blocked,
        ),
    )


def _build(*captures: MetricCapture, first_sequence: int = 4):
    return MetricsSnapshotBuilder().build(
        captures,
        reporter_id="reporter-a",
        startup_epoch=uuid4(),
        first_sequence=first_sequence,
        captured_at=_NOW,
        capture_elapsed_ns=123,
    )


def test_maps_semantic_counters_and_process_gauges_without_inference() -> None:
    http_histogram = LatencyHistogram(
        HTTP_REQUEST_DURATION_BOUNDARIES_NS,
        (1,) + (0,) * len(HTTP_REQUEST_DURATION_BOUNDARIES_NS),
        1,
        500_000,
        500_000,
        500_000,
    )
    captures = (
        _entry("POST /orders", 3, 2),
        _entry("POST /orders", 4, 1),
        MetricCapture(
            MetricCaptureSource.HTTP,
            HttpMetricSnapshot(1, http_histogram, 99),
        ),
        MetricCapture(
            MetricCaptureSource.SYSTEM,
            SystemSnapshot(
                0.25, None, 1.5, None, 99.0, 100, memory_bytes=4096, memory_ratio=0.5
            ),
        ),
    )

    (batch,) = _build(*captures)
    snapshot = batch.snapshot
    by_name = {(item.name, item.resource): item.value for item in snapshot.counters}
    assert by_name[(CounterName.SENTINEL_ENTRIES_ADMITTED, "POST /orders")] == 7
    assert by_name[(CounterName.SENTINEL_ENTRIES_BLOCKED, "POST /orders")] == 3
    assert by_name[(CounterName.HTTP_REQUESTS_COMPLETED, None)] == 1
    assert CounterName.BUSINESS_TRANSACTIONS_COMPLETED not in {
        item.name for item in snapshot.counters
    }
    gauges = {item.name: item for item in snapshot.gauges}
    assert gauges[GaugeName.PROCESS_CPU_RATIO].value == 0.25
    assert gauges[GaugeName.PROCESS_RSS_BYTES].value == 4096
    assert gauges[GaugeName.EVENT_LOOP_LAG_NS].value == 1_500_000
    assert gauges[GaugeName.PROCESS_MEMORY_RATIO].quality is GaugeQuality.AVAILABLE


def test_missing_process_capture_is_explicitly_unavailable() -> None:
    (batch,) = _build(_entry("GET /health", 1, 0))
    assert all(
        item.quality is GaugeQuality.UNAVAILABLE for item in batch.snapshot.gauges
    )


def test_histogram_with_non_v2_bounds_is_rejected_not_rebucketed() -> None:
    capture = MetricCapture(
        MetricCaptureSource.HTTP,
        HttpMetricSnapshot(0, _histogram((1, 2)), 99),
    )
    with pytest.raises(ValueError, match="frozen Metrics V2 bounds"):
        _build(capture)


def test_more_than_frozen_active_resource_limit_is_rejected() -> None:
    captures = tuple(_entry(f"resource-{index:03}", index, 0) for index in range(257))
    with pytest.raises(ValueError, match="active resource count"):
        _build(*captures)


def test_many_resources_are_split_without_truncation_and_keep_sequence_order() -> None:
    captures = tuple(_entry(f"resource-{index:03}", index, 1) for index in range(130))
    batches = _build(*captures)
    assert len(batches) == 2
    assert tuple(item.snapshot.sequence for item in batches) == (4, 5)
    assert tuple(item.index for item in batches) == (1, 2)
    assert all(
        len(batch.snapshot.counters)
        + len(batch.snapshot.histograms)
        + len(batch.snapshot.gauges)
        <= METRICS_V2_MAX_RECORDS
        for batch in batches
    )
    assert sum(
        item.value
        for batch in batches
        for item in batch.snapshot.counters
        if item.name is CounterName.SENTINEL_ENTRIES_ADMITTED
    ) == sum(range(130))


def test_split_snapshot_sequence_range_cannot_overflow_safe_integer() -> None:
    captures = tuple(_entry(f"resource-{index:03}", index, 0) for index in range(126))
    with pytest.raises(ValueError, match="sequence range exceeds safe integer"):
        _build(*captures, first_sequence=MAX_SAFE_INTEGER)
