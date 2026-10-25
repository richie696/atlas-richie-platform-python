"""Immutable value objects and pure calculations for Metrics Reporting V2."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class CounterName(StrEnum):
    """Frozen cumulative counters accepted by Metrics Reporting V2."""

    HTTP_REQUESTS_COMPLETED = "http_requests_completed_total"
    SENTINEL_ENTRIES_ADMITTED = "sentinel_entries_admitted_total"
    SENTINEL_ENTRIES_BLOCKED = "sentinel_entries_blocked_total"
    BUSINESS_TRANSACTIONS_COMPLETED = "business_transactions_completed_total"


class HistogramName(StrEnum):
    """Frozen histogram families accepted by Metrics Reporting V2."""

    HTTP_REQUEST_DURATION = "http_request_duration"


class GaugeName(StrEnum):
    """Frozen process-scope gauges with metric-specific units."""

    PROCESS_CPU_RATIO = "process_cpu_ratio"
    PROCESS_RSS_BYTES = "process_rss_bytes"
    PROCESS_MEMORY_RATIO = "process_memory_ratio"
    EVENT_LOOP_LAG_NS = "event_loop_lag_ns"


class GaugeQuality(StrEnum):
    """Whether a reported gauge value is available at capture time."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


MAX_SAFE_INTEGER = 2**53 - 1
MAX_DECIMAL_INTEGER_DIGITS = 38
MAX_IDENTIFIER_LENGTH = 200
MAX_HISTOGRAM_BOUNDARIES = 64
HTTP_REQUEST_DURATION_BOUNDARIES_NS = (
    1_000_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
    250_000_000,
    500_000_000,
    1_000_000_000,
    2_000_000_000,
    5_000_000_000,
    10_000_000_000,
)
MAX_RATE_INTERVAL_NS = 10_000_000_000
_PERCENTILE_NUMERATOR = 95
_PERCENTILE_DENOMINATOR = 100


class CumulativeDeltaState(StrEnum):
    """Stable outcomes when differencing cumulative observations."""

    AVAILABLE = "available"
    BASELINE_REQUIRED = "baseline_required"
    COUNTER_RESET = "counter_reset"
    SAMPLE_ORDER_INVALID = "sample_order_invalid"


# Counter and histogram differencing share baseline and ordering states.
CounterRateState = CumulativeDeltaState


def _is_nonnegative_int(value: object) -> bool:
    """Reject bool as well as negative/non-integer measurement values."""
    return type(value) is int and 0 <= value <= MAX_SAFE_INTEGER


def _is_nonnegative_decimal_integer(value: object) -> bool:
    """Bound cumulative nanoseconds for exact cross-language decimal encoding."""
    return type(value) is int and 0 <= value < 10**MAX_DECIMAL_INTEGER_DIGITS


def _validate_utc_instant(value: datetime) -> bool:
    """Return whether a timestamp is timezone-aware and normalized to UTC."""
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


def _is_bounded_scalar_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
        and len(value) <= MAX_IDENTIFIER_LENGTH
        and "\r" not in value
        and "\n" not in value
        and not any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    )


@dataclass(frozen=True, slots=True)
class CounterReading:
    """One cumulative monotonic counter, optionally scoped to a resource."""

    name: CounterName
    value: int
    resource: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, CounterName):
            raise TypeError("counter name must use CounterName")
        if not _is_nonnegative_int(self.value):
            raise ValueError("counter value must be a non-negative integer")
        if self.resource is not None and not _is_bounded_scalar_identifier(
            self.resource
        ):
            raise ValueError("resource identity must be non-blank when provided")


@dataclass(frozen=True, slots=True)
class HistogramReading:
    """A cumulative HTTP duration histogram with disjoint buckets and overflow.

    ``bucket_counts`` contains one count per inclusive finite upper boundary,
    followed by one overflow count. Metrics V2 freezes twelve HTTP duration
    boundaries in :data:`HTTP_REQUEST_DURATION_BOUNDARIES_NS`.
    """

    name: HistogramName
    boundaries_ns: tuple[int, ...]
    bucket_counts: tuple[int, ...]
    sample_count: int
    total_ns: int
    min_ns: int | None
    max_ns: int | None
    resource: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, HistogramName):
            raise TypeError("histogram name must use HistogramName")
        if (
            type(self.boundaries_ns) is not tuple
            or type(self.bucket_counts) is not tuple
        ):
            raise ValueError("histogram boundaries and counts must be immutable tuples")
        if (
            not self.boundaries_ns
            or len(self.boundaries_ns) > MAX_HISTOGRAM_BOUNDARIES
            or any(
                not _is_nonnegative_int(boundary) or boundary == 0
                for boundary in self.boundaries_ns
            )
        ):
            raise ValueError("histogram boundaries must be positive integers")
        if tuple(sorted(set(self.boundaries_ns))) != self.boundaries_ns:
            raise ValueError("histogram boundaries must be strictly increasing")
        if self.boundaries_ns != HTTP_REQUEST_DURATION_BOUNDARIES_NS:
            raise ValueError("HTTP duration histogram boundaries must match Metrics V2")
        if len(self.bucket_counts) != len(self.boundaries_ns) + 1:
            raise ValueError("histogram must include one overflow bucket")
        if any(not _is_nonnegative_int(count) for count in self.bucket_counts):
            raise ValueError("histogram bucket counts must be non-negative integers")
        if not _is_nonnegative_int(self.sample_count) or not (
            _is_nonnegative_decimal_integer(self.total_ns)
        ):
            raise ValueError(
                "histogram count and total are outside their numeric bounds"
            )
        if sum(self.bucket_counts) != self.sample_count:
            raise ValueError("histogram bucket counts must sum to sample count")
        if self.sample_count == 0:
            if self.total_ns != 0 or self.min_ns is not None or self.max_ns is not None:
                raise ValueError("empty histogram cannot carry duration statistics")
        elif (
            not _is_nonnegative_int(self.min_ns)
            or not _is_nonnegative_int(self.max_ns)
            or self.min_ns > self.max_ns
            or self.total_ns < self.min_ns * self.sample_count
            or self.total_ns > self.max_ns * self.sample_count
        ):
            raise ValueError("histogram duration statistics are inconsistent")
        if self.resource is not None and not _is_bounded_scalar_identifier(
            self.resource
        ):
            raise ValueError("resource identity must be non-blank when provided")


@dataclass(frozen=True, slots=True)
class GaugeReading:
    """One instantaneous gauge; unavailable measurements use ``None``."""

    name: GaugeName
    value: int | float | None
    quality: GaugeQuality

    def __post_init__(self) -> None:
        if not isinstance(self.name, GaugeName):
            raise TypeError("gauge name must use GaugeName")
        if not isinstance(self.quality, GaugeQuality):
            raise TypeError("gauge quality must use GaugeQuality")
        if self.quality is GaugeQuality.UNAVAILABLE:
            if self.value is not None:
                raise ValueError("unavailable gauge must not carry a value")
            return
        if type(self.value) is int:
            is_valid = 0 <= self.value <= MAX_SAFE_INTEGER
        elif type(self.value) is float:
            is_valid = math.isfinite(self.value) and 0 <= self.value <= MAX_SAFE_INTEGER
        else:
            is_valid = False
        if not is_valid:
            raise ValueError(
                "available gauge must be finite and non-negative "
                "within the safe number range"
            )


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Typed V2 snapshot; identity remains subject to transport enrollment."""

    reporter_id: str
    startup_epoch: UUID
    sequence: int
    captured_at: datetime
    capture_elapsed_ns: int
    counters: tuple[CounterReading, ...] = ()
    histograms: tuple[HistogramReading, ...] = ()
    gauges: tuple[GaugeReading, ...] = ()

    def __post_init__(self) -> None:
        if not _is_bounded_scalar_identifier(self.reporter_id):
            raise ValueError("reporter identity must be a bounded non-blank scalar")
        if type(self.startup_epoch) is not UUID:
            raise ValueError("startup epoch must be a UUID")
        if not _is_nonnegative_int(self.sequence) or self.sequence == 0:
            raise ValueError("sequence must be a positive integer")
        if not _validate_utc_instant(self.captured_at):
            raise ValueError("capture time must be a UTC-aware datetime")
        if not _is_nonnegative_decimal_integer(self.capture_elapsed_ns):
            raise ValueError(
                "capture elapsed time must be a bounded non-negative integer"
            )
        if any(
            type(records) is not tuple
            for records in (self.counters, self.histograms, self.gauges)
        ):
            raise ValueError("snapshot readings must be immutable tuples")
        if any(not isinstance(item, CounterReading) for item in self.counters):
            raise ValueError("snapshot counters must use CounterReading values")
        if any(not isinstance(item, HistogramReading) for item in self.histograms):
            raise ValueError("snapshot histograms must use HistogramReading values")
        if any(not isinstance(item, GaugeReading) for item in self.gauges):
            raise ValueError("snapshot gauges must use GaugeReading values")
        counter_keys = tuple((item.name, item.resource) for item in self.counters)
        histogram_keys = tuple((item.name, item.resource) for item in self.histograms)
        gauge_keys = tuple(item.name for item in self.gauges)
        if len(set(counter_keys)) != len(counter_keys):
            raise ValueError("snapshot cannot repeat a counter identity")
        if len(set(histogram_keys)) != len(histogram_keys):
            raise ValueError("snapshot cannot repeat a histogram identity")
        if len(set(gauge_keys)) != len(gauge_keys):
            raise ValueError("snapshot cannot repeat a gauge identity")


@dataclass(frozen=True, slots=True)
class CounterRateCalculation:
    """Pure result of deriving a per-reporter rate from two snapshots."""

    state: CounterRateState
    delta: int | None
    elapsed_seconds: float | None
    rate_per_second: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CounterRateState):
            raise TypeError("counter rate state must use CounterRateState")
        values = (self.delta, self.elapsed_seconds, self.rate_per_second)
        if self.state is not CounterRateState.AVAILABLE:
            if any(value is not None for value in values):
                raise ValueError("unavailable rate calculation cannot carry values")
            return
        if (
            not _is_nonnegative_int(self.delta)
            or type(self.elapsed_seconds) is not float
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds <= 0
            or type(self.rate_per_second) is not float
            or not math.isfinite(self.rate_per_second)
            or self.rate_per_second < 0
        ):
            raise ValueError("available rate calculation values are inconsistent")


@dataclass(frozen=True, slots=True)
class HistogramDelta:
    """Interval histogram derived from two cumulative reporter snapshots.

    It intentionally contains no min/max: cumulative extrema cannot be
    subtracted to recover interval extrema. Bucket counts and total duration
    are the mergeable facts needed for pooled percentile calculation.
    """

    name: HistogramName
    boundaries_ns: tuple[int, ...]
    bucket_counts: tuple[int, ...]
    sample_count: int
    total_ns: int
    resource: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, HistogramName):
            raise TypeError("histogram delta name must use HistogramName")
        if (
            type(self.boundaries_ns) is not tuple
            or type(self.bucket_counts) is not tuple
        ):
            raise ValueError("histogram delta sequences must be immutable tuples")
        if (
            not self.boundaries_ns
            or len(self.boundaries_ns) > MAX_HISTOGRAM_BOUNDARIES
            or any(
                type(boundary) is not int
                or boundary <= 0
                or boundary > MAX_SAFE_INTEGER
                for boundary in self.boundaries_ns
            )
            or tuple(sorted(set(self.boundaries_ns))) != self.boundaries_ns
        ):
            raise ValueError("histogram delta boundaries must be positive and ordered")
        if self.boundaries_ns != HTTP_REQUEST_DURATION_BOUNDARIES_NS:
            raise ValueError("HTTP duration histogram boundaries must match Metrics V2")
        if len(self.bucket_counts) != len(self.boundaries_ns) + 1:
            raise ValueError("histogram delta must include one overflow bucket")
        if any(not _is_nonnegative_int(count) for count in self.bucket_counts):
            raise ValueError(
                "histogram delta counts must be safe non-negative integers"
            )
        if not _is_nonnegative_int(self.sample_count) or not (
            _is_nonnegative_decimal_integer(self.total_ns)
        ):
            raise ValueError("histogram delta totals are outside their numeric bounds")
        if sum(self.bucket_counts) != self.sample_count:
            raise ValueError("histogram delta buckets must sum to sample count")
        if self.sample_count == 0 and self.total_ns != 0:
            raise ValueError("empty histogram delta must have zero total duration")
        if self.resource is not None and not _is_bounded_scalar_identifier(
            self.resource
        ):
            raise ValueError("histogram delta resource must be a bounded identifier")

    @property
    def p95_upper_bound_ns(self) -> int | None:
        """Return nearest-rank p95's finite bucket bound, or unavailable."""
        if self.sample_count == 0:
            return None
        rank = (
            self.sample_count * _PERCENTILE_NUMERATOR + _PERCENTILE_DENOMINATOR - 1
        ) // _PERCENTILE_DENOMINATOR
        cumulative = 0
        for boundary, count in zip(
            self.boundaries_ns, self.bucket_counts[:-1], strict=True
        ):
            cumulative += count
            if cumulative >= rank:
                return boundary
        return None


@dataclass(frozen=True, slots=True)
class HistogramDeltaCalculation:
    """Pure result for deriving one interval histogram from a reporter pair."""

    state: CumulativeDeltaState
    histogram: HistogramDelta | None
    elapsed_seconds: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CumulativeDeltaState):
            raise TypeError("histogram delta state must use CumulativeDeltaState")
        if self.state is CumulativeDeltaState.AVAILABLE:
            if (
                not isinstance(self.histogram, HistogramDelta)
                or type(self.elapsed_seconds) is not float
                or not math.isfinite(self.elapsed_seconds)
                or self.elapsed_seconds <= 0
            ):
                raise ValueError("available histogram delta requires valid data")
        elif self.histogram is not None or self.elapsed_seconds is not None:
            raise ValueError("unavailable histogram delta cannot carry data")


def calculate_counter_rate(
    previous: MetricsSnapshot,
    current: MetricsSnapshot,
    name: CounterName,
    resource: str | None = None,
) -> CounterRateCalculation:
    """Derive one counter rate without crossing reporter/epoch boundaries.

    A missing previous point requires a new baseline. Sequence or monotonic
    elapsed-time regressions and counter resets yield explicit unavailable
    states rather than a negative or fabricated rate. Gaps beyond ten seconds
    also establish a fresh baseline; wall-clock timestamps are diagnostic only.
    """
    if not isinstance(previous, MetricsSnapshot) or not isinstance(
        current, MetricsSnapshot
    ):
        raise TypeError("counter rate inputs must be MetricsSnapshot values")
    if not isinstance(name, CounterName):
        raise TypeError("counter rate name must use CounterName")
    if previous.reporter_id != current.reporter_id or (
        previous.startup_epoch != current.startup_epoch
    ):
        return CounterRateCalculation(
            CounterRateState.BASELINE_REQUIRED, None, None, None
        )
    if current.sequence <= previous.sequence:
        return CounterRateCalculation(
            CounterRateState.SAMPLE_ORDER_INVALID, None, None, None
        )
    counter_key = (name, resource)
    previous_counts = {
        (reading.name, reading.resource): reading.value for reading in previous.counters
    }
    current_counts = {
        (reading.name, reading.resource): reading.value for reading in current.counters
    }
    if counter_key not in previous_counts or counter_key not in current_counts:
        return CounterRateCalculation(
            CounterRateState.BASELINE_REQUIRED, None, None, None
        )
    previous_value = previous_counts[counter_key]
    current_value = current_counts[counter_key]
    if current_value < previous_value:
        return CounterRateCalculation(CounterRateState.COUNTER_RESET, None, None, None)
    elapsed_ns = current.capture_elapsed_ns - previous.capture_elapsed_ns
    if elapsed_ns <= 0:
        return CounterRateCalculation(
            CounterRateState.SAMPLE_ORDER_INVALID, None, None, None
        )
    if elapsed_ns > MAX_RATE_INTERVAL_NS:
        return CounterRateCalculation(
            CounterRateState.BASELINE_REQUIRED, None, None, None
        )
    elapsed_seconds = elapsed_ns / 1_000_000_000
    delta = current_value - previous_value
    rate_per_second = delta / elapsed_seconds
    if not math.isfinite(rate_per_second):
        return CounterRateCalculation(
            CounterRateState.BASELINE_REQUIRED, None, None, None
        )
    return CounterRateCalculation(
        CounterRateState.AVAILABLE,
        delta,
        elapsed_seconds,
        rate_per_second,
    )


def calculate_histogram_delta(
    previous: MetricsSnapshot,
    current: MetricsSnapshot,
    name: HistogramName,
    resource: str | None = None,
) -> HistogramDeltaCalculation:
    """Subtract matching cumulative histograms within one reporter epoch.

    Missing/changed identities or bucket schemas require a fresh baseline.
    Any counter-like histogram component decrease is treated as a reset, not
    as a negative observation. Gaps beyond ten seconds establish a new baseline.
    """
    if not isinstance(previous, MetricsSnapshot) or not isinstance(
        current, MetricsSnapshot
    ):
        raise TypeError("histogram inputs must be MetricsSnapshot values")
    if not isinstance(name, HistogramName):
        raise TypeError("histogram name must use HistogramName")
    if previous.reporter_id != current.reporter_id or (
        previous.startup_epoch != current.startup_epoch
    ):
        return HistogramDeltaCalculation(
            CumulativeDeltaState.BASELINE_REQUIRED, None, None
        )
    if current.sequence <= previous.sequence:
        return HistogramDeltaCalculation(
            CumulativeDeltaState.SAMPLE_ORDER_INVALID, None, None
        )
    key = (name, resource)
    previous_histograms = {
        (reading.name, reading.resource): reading for reading in previous.histograms
    }
    current_histograms = {
        (reading.name, reading.resource): reading for reading in current.histograms
    }
    if key not in previous_histograms or key not in current_histograms:
        return HistogramDeltaCalculation(
            CumulativeDeltaState.BASELINE_REQUIRED, None, None
        )
    previous_reading = previous_histograms[key]
    current_reading = current_histograms[key]
    if previous_reading.boundaries_ns != current_reading.boundaries_ns:
        return HistogramDeltaCalculation(
            CumulativeDeltaState.BASELINE_REQUIRED, None, None
        )
    if (
        current_reading.sample_count < previous_reading.sample_count
        or current_reading.total_ns < previous_reading.total_ns
        or any(
            new_count < old_count
            for old_count, new_count in zip(
                previous_reading.bucket_counts,
                current_reading.bucket_counts,
                strict=True,
            )
        )
    ):
        return HistogramDeltaCalculation(CumulativeDeltaState.COUNTER_RESET, None, None)
    elapsed_ns = current.capture_elapsed_ns - previous.capture_elapsed_ns
    if elapsed_ns <= 0:
        return HistogramDeltaCalculation(
            CumulativeDeltaState.SAMPLE_ORDER_INVALID, None, None
        )
    if elapsed_ns > MAX_RATE_INTERVAL_NS:
        return HistogramDeltaCalculation(
            CumulativeDeltaState.BASELINE_REQUIRED, None, None
        )
    elapsed_seconds = elapsed_ns / 1_000_000_000
    if not math.isfinite(elapsed_seconds):
        return HistogramDeltaCalculation(
            CumulativeDeltaState.SAMPLE_ORDER_INVALID, None, None
        )
    bucket_deltas = tuple(
        new_count - old_count
        for old_count, new_count in zip(
            previous_reading.bucket_counts,
            current_reading.bucket_counts,
            strict=True,
        )
    )
    histogram_delta = HistogramDelta(
        name=name,
        boundaries_ns=current_reading.boundaries_ns,
        bucket_counts=bucket_deltas,
        sample_count=current_reading.sample_count - previous_reading.sample_count,
        total_ns=current_reading.total_ns - previous_reading.total_ns,
        resource=resource,
    )
    return HistogramDeltaCalculation(
        CumulativeDeltaState.AVAILABLE,
        histogram_delta,
        elapsed_seconds,
    )


__all__ = [
    "HTTP_REQUEST_DURATION_BOUNDARIES_NS",
    "MAX_DECIMAL_INTEGER_DIGITS",
    "MAX_HISTOGRAM_BOUNDARIES",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_SAFE_INTEGER",
    "CounterName",
    "CounterRateCalculation",
    "CounterRateState",
    "CounterReading",
    "CumulativeDeltaState",
    "GaugeName",
    "GaugeQuality",
    "GaugeReading",
    "HistogramDelta",
    "HistogramDeltaCalculation",
    "HistogramName",
    "HistogramReading",
    "MetricsSnapshot",
    "calculate_counter_rate",
    "calculate_histogram_delta",
]
