"""Pure, reporter-local facts used to build durable UTC metric rollups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from atlas_richie.contracts.reporting.v2 import (
    CounterName,
    GaugeName,
    GaugeQuality,
    HistogramName,
    MetricsSnapshot,
    calculate_counter_rate,
    calculate_histogram_delta,
)

from .instance_catalog import is_observation_identifier
from .observation_limits import is_finite_json_number

_MAX_RECEIPT_GAP_NS = 3_000_000_000
_NANOSECONDS_PER_SECOND = 1_000_000_000
_GLOBAL_RESOURCE_KEY = ""


class MetricContributionQuality(StrEnum):
    """Reason a stored rollup contribution has or lacks a numeric value."""

    AVAILABLE = "available"
    NO_SAMPLES = "no_samples"
    STALE = "stale"
    OVERFLOW = "overflow"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MetricIntervalContribution:
    """One bounded metric fact attributed to a reporter and UTC minute.

    Counter and histogram values are interval deltas, never cumulative values.
    Gauges retain the latest received value. ``resource=None`` is the global
    series; resource-scoped Sentinel and HTTP histograms keep their exact label.
    """

    reporter_id: str
    startup_epoch: str
    sequence: int
    environment_id: str
    app_id: str
    instance_id: str
    metric: str
    resource: str | None
    received_at: datetime
    bucket_started_at: datetime
    quality: MetricContributionQuality
    delta: int | None = None
    elapsed_ns: int | None = None
    numerator: int | None = None
    denominator: int | None = None
    histogram_buckets: tuple[int, ...] | None = None
    histogram_sample_count: int | None = None
    gauge_value: int | float | None = None

    def __post_init__(self) -> None:
        identifiers = (
            self.reporter_id,
            self.startup_epoch,
            self.environment_id,
            self.app_id,
            self.instance_id,
            self.metric,
        )
        if not all(is_observation_identifier(value) for value in identifiers):
            raise ValueError("metric contribution identity is invalid")
        if self.resource is not None and not is_observation_identifier(self.resource):
            raise ValueError("metric contribution resource is invalid")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("metric contribution sequence is invalid")
        if not _is_utc(self.received_at) or not _is_utc(self.bucket_started_at):
            raise ValueError("metric contribution times must be UTC")
        expected_bucket = self.received_at.replace(second=0, microsecond=0)
        if self.bucket_started_at != expected_bucket:
            raise ValueError("metric contribution must use its UTC minute bucket")
        if not isinstance(self.quality, MetricContributionQuality):
            raise TypeError("metric contribution quality is unsupported")
        if self.delta is not None and (type(self.delta) is not int or self.delta < 0):
            raise ValueError("metric counter delta is invalid")
        if self.elapsed_ns is not None and (
            type(self.elapsed_ns) is not int or self.elapsed_ns <= 0
        ):
            raise ValueError("metric elapsed duration is invalid")
        if self.numerator is not None and (
            type(self.numerator) is not int or self.numerator < 0
        ):
            raise ValueError("metric numerator is invalid")
        if self.denominator is not None and (
            type(self.denominator) is not int or self.denominator < 0
        ):
            raise ValueError("metric denominator is invalid")
        if self.histogram_buckets is not None and (
            type(self.histogram_buckets) is not tuple
            or any(
                type(value) is not int or value < 0 for value in self.histogram_buckets
            )
        ):
            raise ValueError("metric histogram buckets are invalid")
        if self.histogram_sample_count is not None and (
            type(self.histogram_sample_count) is not int
            or self.histogram_sample_count < 0
        ):
            raise ValueError("metric histogram sample count is invalid")
        if self.gauge_value is not None and (
            not is_finite_json_number(self.gauge_value) or self.gauge_value < 0
        ):
            raise ValueError("metric gauge value is invalid")
        _validate_measurement_shape(self)


def build_metric_interval_contributions(
    *,
    environment_id: str,
    app_id: str,
    instance_id: str,
    previous: MetricsSnapshot | None,
    previous_received_at: datetime | None,
    current: MetricsSnapshot,
    received_at: datetime,
) -> tuple[MetricIntervalContribution, ...]:
    """Derive one reporter's interval facts without crossing epochs.

    ``capture_elapsed_ns`` is the only rate clock. Collector receipt time is
    used only for staleness and UTC bucketing. A gap over three seconds is
    treated as stale and establishes a new baseline; a new epoch does likewise.
    """
    if not isinstance(current, MetricsSnapshot):
        raise TypeError("current metrics snapshot is required")
    if previous is not None and not isinstance(previous, MetricsSnapshot):
        raise TypeError("previous metrics snapshot is invalid")
    if not all(
        is_observation_identifier(value)
        for value in (environment_id, app_id, instance_id)
    ):
        raise ValueError("metric contribution scope identity is invalid")
    if not _is_utc(received_at):
        raise ValueError("Collector receipt time must be UTC")

    bucket_started_at = received_at.replace(second=0, microsecond=0)
    same_epoch = (
        previous is not None
        and previous.reporter_id == current.reporter_id
        and previous.startup_epoch == current.startup_epoch
        and previous.sequence < current.sequence
    )
    recent_baseline = (
        same_epoch
        and previous_received_at is not None
        and _is_utc(previous_received_at)
        and 0
        <= (received_at - previous_received_at).total_seconds()
        * _NANOSECONDS_PER_SECOND
        <= _MAX_RECEIPT_GAP_NS
    )

    contributions: list[MetricIntervalContribution] = []
    if recent_baseline and previous is not None:
        elapsed_ns = current.capture_elapsed_ns - previous.capture_elapsed_ns
        if 0 < elapsed_ns <= 10_000_000_000:
            contributions.extend(
                _counter_contributions(
                    environment_id,
                    app_id,
                    instance_id,
                    previous,
                    current,
                    received_at,
                    bucket_started_at,
                )
            )
            contributions.extend(
                _histogram_contributions(
                    environment_id,
                    app_id,
                    instance_id,
                    previous,
                    current,
                    received_at,
                    bucket_started_at,
                )
            )

    contributions.extend(
        _gauge_contributions(
            environment_id,
            app_id,
            instance_id,
            current,
            received_at,
            bucket_started_at,
        )
    )
    return tuple(contributions)


def _counter_contributions(
    environment_id: str,
    app_id: str,
    instance_id: str,
    previous: MetricsSnapshot,
    current: MetricsSnapshot,
    received_at: datetime,
    bucket_started_at: datetime,
) -> list[MetricIntervalContribution]:
    result: list[MetricIntervalContribution] = []
    counter_metrics = (
        (CounterName.HTTP_REQUESTS_COMPLETED, "http_qps"),
        (CounterName.BUSINESS_TRANSACTIONS_COMPLETED, "tps"),
    )
    for name, metric in counter_metrics:
        calculation = calculate_counter_rate(previous, current, name)
        if calculation.delta is not None:
            result.append(
                _base_contribution(
                    environment_id,
                    app_id,
                    instance_id,
                    current,
                    metric,
                    None,
                    received_at,
                    bucket_started_at,
                    delta=calculation.delta,
                    elapsed_ns=current.capture_elapsed_ns - previous.capture_elapsed_ns,
                )
            )

    prior = _counter_values(previous)
    latest = _counter_values(current)
    resource_ids = sorted(
        {
            resource
            for name, resource in (*prior.keys(), *latest.keys())
            if name
            in (
                CounterName.SENTINEL_ENTRIES_ADMITTED,
                CounterName.SENTINEL_ENTRIES_BLOCKED,
            )
        },
        key=lambda resource: (resource is not None, resource or _GLOBAL_RESOURCE_KEY),
    )
    for resource in resource_ids:
        admitted_key = (CounterName.SENTINEL_ENTRIES_ADMITTED, resource)
        blocked_key = (CounterName.SENTINEL_ENTRIES_BLOCKED, resource)
        if admitted_key not in prior or admitted_key not in latest:
            continue
        if blocked_key not in prior or blocked_key not in latest:
            continue
        admitted_delta = latest[admitted_key] - prior[admitted_key]
        blocked_delta = latest[blocked_key] - prior[blocked_key]
        if admitted_delta < 0 or blocked_delta < 0:
            continue
        result.append(
            _base_contribution(
                environment_id,
                app_id,
                instance_id,
                current,
                "resource_entry_rate",
                resource,
                received_at,
                bucket_started_at,
                delta=admitted_delta + blocked_delta,
                elapsed_ns=current.capture_elapsed_ns - previous.capture_elapsed_ns,
            )
        )
        result.append(
            _base_contribution(
                environment_id,
                app_id,
                instance_id,
                current,
                "blocked_ratio",
                resource,
                received_at,
                bucket_started_at,
                quality=(
                    MetricContributionQuality.UNAVAILABLE
                    if admitted_delta + blocked_delta == 0
                    else MetricContributionQuality.AVAILABLE
                ),
                numerator=blocked_delta,
                denominator=admitted_delta + blocked_delta,
            )
        )
    return result


def _histogram_contributions(
    environment_id: str,
    app_id: str,
    instance_id: str,
    previous: MetricsSnapshot,
    current: MetricsSnapshot,
    received_at: datetime,
    bucket_started_at: datetime,
) -> list[MetricIntervalContribution]:
    previous_resources = {
        item.resource
        for item in previous.histograms
        if item.name is HistogramName.HTTP_REQUEST_DURATION
    }
    current_resources = {
        item.resource
        for item in current.histograms
        if item.name is HistogramName.HTTP_REQUEST_DURATION
    }
    result: list[MetricIntervalContribution] = []
    for resource in sorted(
        previous_resources & current_resources,
        key=lambda value: (value is not None, value or _GLOBAL_RESOURCE_KEY),
    ):
        calculation = calculate_histogram_delta(
            previous, current, HistogramName.HTTP_REQUEST_DURATION, resource
        )
        histogram = calculation.histogram
        if histogram is None:
            continue
        quality = (
            MetricContributionQuality.NO_SAMPLES
            if histogram.sample_count == 0
            else MetricContributionQuality.OVERFLOW
            if histogram.p95_upper_bound_ns is None
            else MetricContributionQuality.AVAILABLE
        )
        result.append(
            _base_contribution(
                environment_id,
                app_id,
                instance_id,
                current,
                "rt_p95",
                resource,
                received_at,
                bucket_started_at,
                quality=quality,
                histogram_buckets=histogram.bucket_counts,
                histogram_sample_count=histogram.sample_count,
            )
        )
    return result


def _gauge_contributions(
    environment_id: str,
    app_id: str,
    instance_id: str,
    snapshot: MetricsSnapshot,
    received_at: datetime,
    bucket_started_at: datetime,
) -> list[MetricIntervalContribution]:
    names = {
        GaugeName.PROCESS_CPU_RATIO: "cpu_ratio",
        GaugeName.PROCESS_RSS_BYTES: "memory_bytes",
        GaugeName.PROCESS_MEMORY_RATIO: "memory_ratio",
    }
    result: list[MetricIntervalContribution] = []
    for reading in snapshot.gauges:
        metric = names.get(reading.name)
        if metric is None:
            continue
        quality = (
            MetricContributionQuality.AVAILABLE
            if reading.quality is GaugeQuality.AVAILABLE
            else MetricContributionQuality.UNAVAILABLE
        )
        result.append(
            _base_contribution(
                environment_id,
                app_id,
                instance_id,
                snapshot,
                metric,
                None,
                received_at,
                bucket_started_at,
                quality=quality,
                gauge_value=reading.value,
            )
        )
    return result


def _base_contribution(
    environment_id: str,
    app_id: str,
    instance_id: str,
    snapshot: MetricsSnapshot,
    metric: str,
    resource: str | None,
    received_at: datetime,
    bucket_started_at: datetime,
    *,
    quality: MetricContributionQuality = MetricContributionQuality.AVAILABLE,
    delta: int | None = None,
    elapsed_ns: int | None = None,
    numerator: int | None = None,
    denominator: int | None = None,
    histogram_buckets: tuple[int, ...] | None = None,
    histogram_sample_count: int | None = None,
    gauge_value: float | None = None,
) -> MetricIntervalContribution:
    return MetricIntervalContribution(
        reporter_id=snapshot.reporter_id,
        startup_epoch=str(snapshot.startup_epoch),
        sequence=snapshot.sequence,
        environment_id=environment_id,
        app_id=app_id,
        instance_id=instance_id,
        metric=metric,
        resource=resource,
        received_at=received_at.astimezone(UTC),
        bucket_started_at=bucket_started_at,
        quality=quality,
        delta=delta,
        elapsed_ns=elapsed_ns,
        numerator=numerator,
        denominator=denominator,
        histogram_buckets=histogram_buckets,
        histogram_sample_count=histogram_sample_count,
        gauge_value=gauge_value,
    )


def _counter_values(
    snapshot: MetricsSnapshot,
) -> dict[tuple[CounterName, str | None], int]:
    return {(item.name, item.resource): item.value for item in snapshot.counters}


def _validate_measurement_shape(contribution: MetricIntervalContribution) -> None:
    rate_metric = contribution.metric in {
        "http_qps",
        "resource_entry_rate",
        "tps",
    }
    ratio_metric = contribution.metric == "blocked_ratio"
    histogram_metric = contribution.metric == "rt_p95"
    gauge_metric = contribution.metric in {"cpu_ratio", "memory_bytes", "memory_ratio"}
    if sum((rate_metric, ratio_metric, histogram_metric, gauge_metric)) != 1:
        raise ValueError("metric contribution kind is unsupported")
    if rate_metric and (
        contribution.delta is None
        or contribution.elapsed_ns is None
        or any(
            value is not None
            for value in (
                contribution.numerator,
                contribution.denominator,
                contribution.histogram_buckets,
                contribution.histogram_sample_count,
                contribution.gauge_value,
            )
        )
    ):
        raise ValueError("rate contribution shape is invalid")
    if ratio_metric and (
        contribution.numerator is None
        or contribution.denominator is None
        or contribution.elapsed_ns is not None
        or contribution.delta is not None
        or contribution.histogram_buckets is not None
        or contribution.histogram_sample_count is not None
        or contribution.gauge_value is not None
    ):
        raise ValueError("ratio contribution shape is invalid")
    if histogram_metric and (
        contribution.histogram_buckets is None
        or contribution.histogram_sample_count is None
        or contribution.elapsed_ns is not None
        or contribution.delta is not None
        or contribution.numerator is not None
        or contribution.denominator is not None
        or contribution.gauge_value is not None
    ):
        raise ValueError("histogram contribution shape is invalid")
    if gauge_metric and (
        contribution.gauge_value is not None
        and not is_finite_json_number(contribution.gauge_value)
        or contribution.delta is not None
        or contribution.elapsed_ns is not None
        or contribution.numerator is not None
        or contribution.denominator is not None
        or contribution.histogram_buckets is not None
        or contribution.histogram_sample_count is not None
    ):
        raise ValueError("gauge contribution shape is invalid")
    if (
        ratio_metric
        and contribution.denominator == 0
        and (contribution.quality is MetricContributionQuality.AVAILABLE)
    ):
        raise ValueError("zero-denominator ratio cannot be available")
    if contribution.quality is MetricContributionQuality.UNAVAILABLE:
        unavailable_gauge = gauge_metric and contribution.gauge_value is None
        unavailable_ratio = ratio_metric and contribution.denominator == 0
        if not (unavailable_gauge or unavailable_ratio):
            raise ValueError("unavailable contribution has a measured value")
    if (
        contribution.quality is MetricContributionQuality.OVERFLOW
        and not histogram_metric
    ):
        raise ValueError("overflow quality is only valid for histograms")
    if contribution.quality is MetricContributionQuality.NO_SAMPLES and not (
        histogram_metric and contribution.histogram_sample_count == 0
    ):
        raise ValueError("no-sample contribution must be an empty histogram")


def _is_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


__all__ = [
    "MetricContributionQuality",
    "MetricIntervalContribution",
    "build_metric_interval_contributions",
]
