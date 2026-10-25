"""Bounded HOST-scope metrics returned by a configured monitoring source."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .observation_limits import MAX_OBSERVATION_POINTS

MAX_HOST_METRIC_HOSTS = 200


class HostMetricKind(StrEnum):
    """Finite Linux host metrics supported by node-exporter-v1."""

    CPU_BUSY_RATIO = "host_cpu_busy_ratio"
    MEMORY_USED_BYTES = "host_memory_used_bytes"
    MEMORY_USED_RATIO = "host_memory_used_ratio"
    LOAD_1M = "host_load_1m"


class HostMetricQuality(StrEnum):
    """Quality of one metric series; missing data is never represented as zero."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    STALE = "stale"
    NO_SAMPLES = "no_samples"
    NOT_INTEGRATED = "not_integrated"
    UNAVAILABLE = "unavailable"


class HostMetricReason(StrEnum):
    """Allowlisted reasons that contain no provider error text."""

    SOURCE_DISABLED = "source_disabled"
    TARGET_REJECTED = "target_rejected"
    AUTHENTICATION = "authentication"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_RESPONSE = "invalid_response"
    MISSING_SAMPLES = "missing_samples"
    STALE_SAMPLES = "stale_samples"
    DUPLICATE_SERIES = "duplicate_series"
    CONFLICTING_IDENTITY = "conflicting_identity"


@dataclass(frozen=True, slots=True)
class HostMetricsQuery:
    """One bounded half-open UTC query interval and Prometheus evaluation step."""

    start_at: datetime
    end_at: datetime
    step_ms: int

    def __post_init__(self) -> None:
        if not _aware(self.start_at) or not _aware(self.end_at):
            raise ValueError("host metrics range must use aware timestamps")
        start_at = self.start_at.astimezone(UTC)
        end_at = self.end_at.astimezone(UTC)
        duration_ms = (end_at - start_at) / timedelta(milliseconds=1)
        if (
            duration_ms < 1
            or type(self.step_ms) is not int
            or self.step_ms < 1_000
            or self.step_ms > 3_600_000
        ):
            raise ValueError("host metrics range is invalid")
        count = math.floor((duration_ms - 1) / self.step_ms) + 1
        if count > MAX_OBSERVATION_POINTS:
            raise ValueError("host metrics point limit exceeded")
        object.__setattr__(self, "start_at", start_at)
        object.__setattr__(self, "end_at", end_at)

    @property
    def point_count(self) -> int:
        """Number of evaluations in the requested `[start_at, end_at)` range."""
        duration_ms = (self.end_at - self.start_at) / timedelta(milliseconds=1)
        return math.floor((duration_ms - 1) / self.step_ms) + 1

    @property
    def last_inclusive_at(self) -> datetime:
        """Prometheus inclusive end corresponding to the half-open Console range."""
        return self.start_at + timedelta(milliseconds=(self.point_count - 1) * self.step_ms)


@dataclass(frozen=True, slots=True)
class HostMetricPoint:
    """One finite numeric sample with its actual provider evaluation timestamp."""

    at: datetime
    value: float

    def __post_init__(self) -> None:
        if not _aware(self.at) or type(self.value) not in {int, float}:
            raise ValueError("host metric point is invalid")
        if not math.isfinite(float(self.value)):
            raise ValueError("host metric value must be finite")
        object.__setattr__(self, "at", self.at.astimezone(UTC))
        object.__setattr__(self, "value", float(self.value))


@dataclass(frozen=True, slots=True)
class HostMetricSeries:
    """Typed samples and quality for one host metric."""

    kind: HostMetricKind
    quality: HostMetricQuality
    reason: HostMetricReason | None
    samples: tuple[HostMetricPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HostMetricKind) or not isinstance(
            self.quality, HostMetricQuality
        ):
            raise ValueError("host metric series classification is invalid")
        if self.reason is not None and not isinstance(self.reason, HostMetricReason):
            raise ValueError("host metric series reason is invalid")
        if not isinstance(self.samples, tuple) or len(self.samples) > MAX_OBSERVATION_POINTS:
            raise ValueError("host metric samples exceed the bounded contract")
        if any(not isinstance(item, HostMetricPoint) for item in self.samples):
            raise ValueError("host metric samples are invalid")
        if self.quality in {
            HostMetricQuality.AVAILABLE,
            HostMetricQuality.PARTIAL,
            HostMetricQuality.STALE,
        }:
            if not self.samples:
                if self.quality is not HostMetricQuality.PARTIAL:
                    raise ValueError("available host metrics require samples")
        elif self.samples:
            raise ValueError("unavailable host metrics cannot contain values")


@dataclass(frozen=True, slots=True)
class HostMetricIdentity:
    """Operator-selected stable identity labels, not arbitrary provider labels."""

    host_id: str
    labels: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.host_id or len(self.host_id) > 512:
            raise ValueError("host identity key is invalid")
        if not isinstance(self.labels, tuple) or not 1 <= len(self.labels) <= 10:
            raise ValueError("host identity labels are invalid")
        names = tuple(name for name, _value in self.labels)
        if len(set(names)) != len(names) or any(
            not name or len(name) > 128 for name in names
        ):
            raise ValueError("host identity label names are invalid")
        if any(not value or len(value) > 256 for _name, value in self.labels):
            raise ValueError("host identity label values are invalid")


@dataclass(frozen=True, slots=True)
class HostMetricsHost:
    """One host identity and its independent four-series quality facts."""

    identity: HostMetricIdentity
    metrics: tuple[HostMetricSeries, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, HostMetricIdentity):
            raise ValueError("host metrics identity is invalid")
        if (
            not isinstance(self.metrics, tuple)
            or len(self.metrics) != len(HostMetricKind)
            or {item.kind for item in self.metrics} != set(HostMetricKind)
        ):
            raise ValueError("each host must have exactly the supported metric series")


@dataclass(frozen=True, slots=True)
class HostMetricsSnapshot:
    """Bounded query facts; provider failures remain empty finite results."""

    source_id: str
    environment_id: str
    query: HostMetricsQuery
    as_of: datetime
    quality: HostMetricQuality
    reason: HostMetricReason | None
    hosts: tuple[HostMetricsHost, ...]

    def __post_init__(self) -> None:
        if not self.source_id or len(self.source_id) > 200:
            raise ValueError("monitoring source identity is invalid")
        if not self.environment_id or len(self.environment_id) > 200:
            raise ValueError("monitoring environment identity is invalid")
        if not _aware(self.as_of):
            raise ValueError("host metrics query time must be aware")
        if not isinstance(self.quality, HostMetricQuality):
            raise ValueError("host metrics quality is invalid")
        if self.reason is not None and not isinstance(self.reason, HostMetricReason):
            raise ValueError("host metrics reason is invalid")
        if not isinstance(self.hosts, tuple) or len(self.hosts) > MAX_HOST_METRIC_HOSTS:
            raise ValueError("host metrics result exceeds its host bound")
        host_ids = tuple(item.identity.host_id for item in self.hosts)
        if len(set(host_ids)) != len(host_ids):
            raise ValueError("host metrics identities must be unique")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


__all__ = [
    "HostMetricIdentity",
    "HostMetricKind",
    "HostMetricPoint",
    "HostMetricQuality",
    "HostMetricReason",
    "HostMetricSeries",
    "HostMetricsHost",
    "HostMetricsQuery",
    "HostMetricsSnapshot",
    "MAX_HOST_METRIC_HOSTS",
]
