"""Map local Sentinel metric captures to frozen Metrics V2 snapshots."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MAX_SAFE_INTEGER,
    METRICS_V2_MAX_ACTIVE_RESOURCES,
    METRICS_V2_MAX_RECORDS,
    CounterName,
    CounterReading,
    GaugeName,
    GaugeQuality,
    GaugeReading,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
)
from atlas_richie.sentinel.metrics.snapshot import MetricSnapshot
from atlas_richie.sentinel.ports.system_metric_sampler import SystemSnapshot
from atlas_richie.sentinel.reporting import (
    HttpMetricSnapshot,
    MetricCapture,
    MetricCaptureSource,
)

_GLOBAL_RECORD_COUNT = 6
_RESOURCE_RECORD_COUNT = 2
_RESOURCES_PER_BATCH = (
    METRICS_V2_MAX_RECORDS - _GLOBAL_RECORD_COUNT
) // _RESOURCE_RECORD_COUNT
_NANOSECONDS_PER_MILLISECOND = 1_000_000


@dataclass(frozen=True, slots=True)
class SnapshotBatch:
    """One immutable wire snapshot within a single capture cycle."""

    index: int
    count: int
    snapshot: MetricsSnapshot


class MetricsSnapshotBuilder:
    """Build deterministic, bounded snapshots without sampling or I/O.

    Sentinel snapshots are cumulative and may be split across multiple wire
    snapshots when necessary to honor the protocol's record limit. Global
    HTTP/system readings are repeated in each batch; resource counters are
    partitioned without truncation. The caller assigns a distinct sequence to
    each returned snapshot.
    """

    def build(
        self,
        captures: Iterable[MetricCapture],
        *,
        reporter_id: str,
        startup_epoch: UUID,
        first_sequence: int,
        captured_at: datetime,
        capture_elapsed_ns: int,
    ) -> tuple[SnapshotBatch, ...]:
        """Aggregate one capture cycle into deterministic protocol batches."""
        if type(first_sequence) is not int or first_sequence < 1:
            raise ValueError("first_sequence must be a positive integer")
        entry_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        http_capture: HttpMetricSnapshot | None = None
        system_capture: SystemSnapshot | None = None

        for capture in captures:
            if not isinstance(capture, MetricCapture):
                raise TypeError("captures must contain MetricCapture values")
            if capture.source is MetricCaptureSource.ENTRY:
                snapshot = capture.snapshot
                assert isinstance(snapshot, MetricSnapshot)
                resource = snapshot.labels.get("resource", "")
                totals = entry_totals[resource]
                totals[0] += snapshot.admitted
                totals[1] += snapshot.blocked
            elif capture.source is MetricCaptureSource.HTTP:
                http_capture = capture.snapshot  # latest coalesced process capture
                assert isinstance(http_capture, HttpMetricSnapshot)
            elif capture.source is MetricCaptureSource.SYSTEM:
                system_capture = capture.snapshot  # latest coalesced process capture
                assert isinstance(system_capture, SystemSnapshot)

        resources = tuple(sorted(entry_totals))
        if len(resources) > METRICS_V2_MAX_ACTIVE_RESOURCES:
            raise ValueError("active resource count exceeds Metrics V2 limit")
        for resource in resources:
            if not resource:
                raise ValueError("Sentinel entry metrics require a resource identity")

        base_counters, base_histograms, gauges = self._global_readings(
            http_capture, system_capture
        )
        groups = [
            resources[offset : offset + _RESOURCES_PER_BATCH]
            for offset in range(0, len(resources), _RESOURCES_PER_BATCH)
        ] or [()]
        if first_sequence + len(groups) - 1 > MAX_SAFE_INTEGER:
            raise ValueError("snapshot sequence range exceeds safe integer limit")
        batches: list[SnapshotBatch] = []
        for index, group in enumerate(groups, start=1):
            counters = list(base_counters)
            for resource in group:
                admitted, blocked = entry_totals[resource]
                counters.extend(
                    (
                        CounterReading(
                            CounterName.SENTINEL_ENTRIES_ADMITTED,
                            admitted,
                            resource,
                        ),
                        CounterReading(
                            CounterName.SENTINEL_ENTRIES_BLOCKED,
                            blocked,
                            resource,
                        ),
                    )
                )
            snapshot = MetricsSnapshot(
                reporter_id=reporter_id,
                startup_epoch=startup_epoch,
                sequence=first_sequence + index - 1,
                captured_at=captured_at,
                capture_elapsed_ns=capture_elapsed_ns,
                counters=tuple(counters),
                histograms=base_histograms,
                gauges=gauges,
            )
            batches.append(SnapshotBatch(index, len(groups), snapshot))
        return tuple(batches)

    @staticmethod
    def _global_readings(
        http_capture: HttpMetricSnapshot | None,
        system_capture: SystemSnapshot | None,
    ) -> tuple[
        tuple[CounterReading, ...],
        tuple[HistogramReading, ...],
        tuple[GaugeReading, ...],
    ]:
        counters: list[CounterReading] = []
        histograms: list[HistogramReading] = []
        if http_capture is not None:
            histogram = http_capture.latency_histogram
            if histogram.boundaries_ns != HTTP_REQUEST_DURATION_BOUNDARIES_NS:
                raise ValueError("HTTP histogram must use the frozen Metrics V2 bounds")
            counters.append(
                CounterReading(
                    CounterName.HTTP_REQUESTS_COMPLETED,
                    http_capture.completed_requests,
                )
            )
            histograms.append(
                HistogramReading(
                    HistogramName.HTTP_REQUEST_DURATION,
                    histogram.boundaries_ns,
                    histogram.bucket_counts,
                    histogram.sample_count,
                    histogram.total_ns,
                    histogram.min_ns,
                    histogram.max_ns,
                )
            )

        gauges = tuple(
            MetricsSnapshotBuilder._gauge(name, value)
            for name, value in (
                (
                    GaugeName.PROCESS_CPU_RATIO,
                    None if system_capture is None else system_capture.cpu_usage,
                ),
                (
                    GaugeName.PROCESS_RSS_BYTES,
                    None if system_capture is None else system_capture.memory_bytes,
                ),
                (
                    GaugeName.PROCESS_MEMORY_RATIO,
                    None if system_capture is None else system_capture.memory_ratio,
                ),
                (
                    GaugeName.EVENT_LOOP_LAG_NS,
                    None
                    if system_capture is None
                    or system_capture.event_loop_lag_ms is None
                    else system_capture.event_loop_lag_ms
                    * _NANOSECONDS_PER_MILLISECOND,
                ),
            )
        )
        return tuple(counters), tuple(histograms), gauges

    @staticmethod
    def _gauge(name: GaugeName, value: float | None) -> GaugeReading:
        quality = GaugeQuality.UNAVAILABLE if value is None else GaugeQuality.AVAILABLE
        return GaugeReading(name=name, value=value, quality=quality)
