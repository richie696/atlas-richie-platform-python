"""Incarnation-bound instance detail and scoped metric observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .instance_catalog import (
    METRIC_DENOMINATORS as _METRIC_DENOMINATORS,
)
from .instance_catalog import (
    METRIC_UNITS as _METRIC_UNITS,
)
from .instance_catalog import (
    OPERATIONAL_METRICS as _OPERATIONAL_METRICS,
)
from .instance_catalog import (
    InstanceLayer,
    MetricDenominator,
    MetricQuality,
    MetricReading,
    ObservationCoverage,
    ObservationScope,
    ObservationWindow,
    ObservedInstance,
)
from .instance_catalog import (
    is_aware_instant as _is_aware_instant,
)
from .instance_catalog import (
    is_observation_identifier as _is_identifier,
)
from .observation_limits import (
    MAX_OBSERVATION_POINTS,
    MAX_OBSERVATION_WINDOW_MS,
    is_finite_json_number,
)

MAX_METRIC_SELECTION = len(_METRIC_UNITS)


class ObservationAnnotationKind(StrEnum):
    """Recorded control-plane event kinds aligned to a metric window."""

    PUBLICATION = "publication"
    SOURCE_ACTIVATION = "source_activation"
    INCIDENT = "incident"


@dataclass(frozen=True, slots=True)
class InstanceDetailQuery:
    """Explicit target incarnation, collection scope, window, and step."""

    environment_id: str
    app_id: str
    instance_id: str
    resource: str | None
    scope: InstanceLayer
    window: ObservationWindow
    process_epoch: str
    step_ms: int

    def __post_init__(self) -> None:
        required = (
            self.environment_id,
            self.app_id,
            self.instance_id,
            self.process_epoch,
        )
        if not all(_is_identifier(value) for value in required):
            raise ValueError("instance detail target identity is invalid")
        if self.resource is not None and not _is_identifier(self.resource):
            raise ValueError("instance detail resource identity is invalid")
        if not isinstance(self.scope, InstanceLayer):
            raise ValueError("instance detail scope is unsupported")
        if not isinstance(self.window, ObservationWindow):
            raise ValueError("instance detail window is invalid")
        if (
            type(self.step_ms) is not int
            or not 1 <= self.step_ms <= MAX_OBSERVATION_WINDOW_MS
            or math.ceil(self.window.duration_ms / self.step_ms)
            > MAX_OBSERVATION_POINTS
        ):
            raise ValueError("instance detail step exceeds the sample bound")

    @property
    def context(self) -> ObservationContext:
        """Return the shared metric context without the process-epoch selector."""
        return ObservationContext(
            environment_id=self.environment_id,
            app_id=self.app_id,
            instance_id=self.instance_id,
            resource=self.resource,
            scope=ObservationScope(self.scope.value),
            window=self.window,
        )


@dataclass(frozen=True, slots=True)
class ObservationContext:
    """Scope identity and half-open time window shared by metric consumers."""

    environment_id: str
    app_id: str | None
    instance_id: str | None
    resource: str | None
    scope: ObservationScope
    window: ObservationWindow

    def __post_init__(self) -> None:
        required_ids = (self.environment_id,)
        optional_ids = (self.app_id, self.instance_id, self.resource)
        if not all(_is_identifier(value) for value in required_ids) or any(
            value is not None and not _is_identifier(value) for value in optional_ids
        ):
            raise ValueError("observation context identity is invalid")
        if self.instance_id is not None and self.app_id is None:
            raise ValueError("instance context requires an application identity")
        if not isinstance(self.scope, ObservationScope):
            raise ValueError("observation scope is unsupported")
        if not isinstance(self.window, ObservationWindow):
            raise ValueError("observation context window is invalid")


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One ordered UTC sample; a missing value is not a zero measurement."""

    at: datetime
    value: int | float | None

    def __post_init__(self) -> None:
        if not _is_aware_instant(self.at):
            raise ValueError("metric sample time must be timezone-aware")
        if (
            self.value is not None
            and (not is_finite_json_number(self.value) or self.value < 0)
        ):
            raise ValueError("metric sample value must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """One metric's quality and denominator plus a bounded ordered sample series."""

    source: str
    denominator: MetricDenominator
    coverage: ObservationCoverage
    quality: MetricQuality
    metric: str
    unit: str
    samples: tuple[MetricSample, ...]

    def __post_init__(self) -> None:
        if not _is_identifier(self.source):
            raise ValueError("metric series source is invalid")
        if not isinstance(self.denominator, MetricDenominator):
            raise ValueError("metric series denominator is unsupported")
        if not isinstance(self.coverage, ObservationCoverage):
            raise ValueError("metric series coverage is invalid")
        if not isinstance(self.quality, MetricQuality):
            raise ValueError("metric series quality is unsupported")
        _validate_metric_identity(self.metric, self.unit, self.denominator)
        if (
            not isinstance(self.samples, tuple)
            or len(self.samples) > MAX_OBSERVATION_POINTS
        ):
            raise ValueError("metric series exceeds the sample bound")
        if any(not isinstance(sample, MetricSample) for sample in self.samples):
            raise ValueError("metric series contains an invalid sample")
        previous: datetime | None = None
        for sample in self.samples:
            _validate_metric_value(self.metric, sample.value)
            if previous is not None and sample.at <= previous:
                raise ValueError("metric samples must be strictly ordered")
            if sample.value is not None and self.coverage.reporting == 0:
                raise ValueError("metric samples require reporting coverage")
            if sample.value is not None and self.quality in (
                MetricQuality.NO_SAMPLES,
                MetricQuality.NOT_INTEGRATED,
            ):
                raise ValueError("unobserved metric series cannot contain values")
            previous = sample.at
        if self.quality is MetricQuality.AVAILABLE:
            if (
                self.coverage.expected is None
                or self.coverage.reporting == 0
                or self.coverage.reporting != self.coverage.expected
                or not any(sample.value is not None for sample in self.samples)
            ):
                raise ValueError(
                    "available metric series requires complete observed coverage"
                )
        if self.quality in (MetricQuality.NO_SAMPLES, MetricQuality.NOT_INTEGRATED):
            if self.coverage.reporting != 0:
                raise ValueError("unobserved metric series cannot claim reporters")


@dataclass(frozen=True, slots=True)
class ObservationAnnotation:
    """A bounded management event aligned with the requested observation window."""

    id: str
    kind: ObservationAnnotationKind
    at: datetime
    version_id: str | None = None
    publication_id: str | None = None
    incident_id: str | None = None

    def __post_init__(self) -> None:
        if not _is_identifier(self.id) or not _is_aware_instant(self.at):
            raise ValueError("observation annotation identity or time is invalid")
        if not isinstance(self.kind, ObservationAnnotationKind):
            raise ValueError("observation annotation kind is unsupported")
        optional_ids = (self.version_id, self.publication_id, self.incident_id)
        if any(
            value is not None and not _is_identifier(value) for value in optional_ids
        ):
            raise ValueError("observation annotation target is invalid")


@dataclass(frozen=True, slots=True)
class MetricQuery:
    """Metric selection owned by the observation request, not UI labels."""

    context: ObservationContext
    metrics: tuple[str, ...]
    step_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.context, ObservationContext):
            raise ValueError("metric query context is invalid")
        if (
            not isinstance(self.metrics, tuple)
            or not 1 <= len(self.metrics) <= MAX_METRIC_SELECTION
            or any(not isinstance(metric, str) for metric in self.metrics)
            or len(set(self.metrics)) != len(self.metrics)
            or any(metric not in _METRIC_UNITS for metric in self.metrics)
        ):
            raise ValueError("metric query selection is invalid")
        if (
            type(self.step_ms) is not int
            or not 1 <= self.step_ms <= MAX_OBSERVATION_WINDOW_MS
            or math.ceil(self.context.window.duration_ms / self.step_ms)
            > MAX_OBSERVATION_POINTS
        ):
            raise ValueError("metric query step exceeds the sample bound")


@dataclass(frozen=True, slots=True)
class MetricBundle:
    """Query-bound metric summaries, ordered series, and aligned annotations."""

    query: MetricQuery
    as_of: datetime
    summary: tuple[MetricReading, ...]
    series: tuple[MetricSeries, ...]
    annotations: tuple[ObservationAnnotation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, MetricQuery) or not _is_aware_instant(self.as_of):
            raise ValueError("metric bundle query or read time is invalid")
        if (
            not isinstance(self.summary, tuple)
            or not isinstance(self.series, tuple)
            or not isinstance(self.annotations, tuple)
            or len(self.summary) > MAX_METRIC_SELECTION
            or len(self.series) > MAX_METRIC_SELECTION
            or len(self.annotations) > MAX_OBSERVATION_POINTS
        ):
            raise ValueError("metric bundle exceeds a collection bound")
        requested = set(self.query.metrics)
        if (
            any(not isinstance(item, MetricReading) for item in self.summary)
            or any(not isinstance(item, MetricSeries) for item in self.series)
            or any(
                not isinstance(item, ObservationAnnotation)
                for item in self.annotations
            )
            or {item.metric for item in self.summary} != requested
            or len(self.summary) != len(requested)
            or {item.metric for item in self.series} != requested
            or len(self.series) != len(requested)
        ):
            raise ValueError("metric bundle does not match the metric selection")
        series_by_metric = {item.metric: item for item in self.series}
        if any(
            not _same_metric_metadata(reading, series_by_metric[reading.metric])
            for reading in self.summary
        ):
            raise ValueError("metric summary and series metadata must match")
        if any(
            not self.query.context.window.contains(item.sampled_at)
            for item in self.summary
            if item.sampled_at is not None
        ):
            raise ValueError("metric summary sample is outside the requested window")
        if any(
            not self.query.context.window.contains(sample.at)
            for item in self.series
            for sample in item.samples
        ):
            raise ValueError("metric series sample is outside the requested window")
        if any(
            not self.query.context.window.contains(item.at)
            for item in self.annotations
        ):
            raise ValueError("metric annotation is outside the requested query")
        if len({item.id for item in self.annotations}) != len(self.annotations):
            raise ValueError("metric annotations must have unique identities")


@dataclass(frozen=True, slots=True)
class InstanceObservation:
    """One process incarnation and only the metrics supported at its scope."""

    query: InstanceDetailQuery
    as_of: datetime
    instance: ObservedInstance
    metrics: MetricBundle | None

    def __post_init__(self) -> None:
        if not isinstance(self.query, InstanceDetailQuery) or not _is_aware_instant(
            self.as_of
        ):
            raise ValueError("instance observation query or time is invalid")
        if not isinstance(self.instance, ObservedInstance):
            raise ValueError("instance observation identity is invalid")
        if (
            self.instance.instance_id != self.query.instance_id
            or self.instance.app_id != self.query.app_id
            or self.instance.environment_id != self.query.environment_id
            or self.instance.process_epoch != self.query.process_epoch
            or self.instance.rule_receipt.process_epoch != self.query.process_epoch
        ):
            raise ValueError("instance facts do not match the requested incarnation")
        supported = self.query.scope in self.instance.supported_scopes
        if not supported and self.metrics is not None:
            raise ValueError("unsupported collection scope must not borrow metrics")
        if supported:
            if not isinstance(self.metrics, MetricBundle):
                raise ValueError("supported collection scope requires metric facts")
            metric_query = self.metrics.query
            if (
                metric_query.context != self.query.context
                or set(metric_query.metrics) != _OPERATIONAL_METRICS
                or metric_query.step_ms != self.query.step_ms
                or self.metrics.as_of != self.as_of
            ):
                raise ValueError("metric bundle does not match the instance query")


def _validate_metric_identity(
    metric: str,
    unit: str,
    denominator: MetricDenominator,
) -> None:
    if (
        metric not in _METRIC_UNITS
        or unit != _METRIC_UNITS[metric]
        or denominator != _METRIC_DENOMINATORS[metric]
    ):
        raise ValueError("metric unit or denominator does not match the metric")


def _same_metric_metadata(reading: MetricReading, series: MetricSeries) -> bool:
    return (
        reading.metric == series.metric
        and reading.unit == series.unit
        and reading.source == series.source
        and reading.denominator == series.denominator
        and reading.coverage == series.coverage
        and reading.quality == series.quality
    )


def _validate_metric_value(metric: str, value: int | float | None) -> None:
    if value is None:
        return
    if (
        not is_finite_json_number(value)
        or value < 0
        or (_METRIC_UNITS[metric] == "ratio" and value > 1)
    ):
        raise ValueError("metric value is outside the supported range")
