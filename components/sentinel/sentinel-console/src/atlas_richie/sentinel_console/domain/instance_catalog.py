"""Immutable instance-catalog facts and their cross-record invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from .wire_strings import (
    has_non_blank_wire_content,
    has_unicode_scalar_values,
    is_bounded_wire_identifier,
    utf16_length as _utf16_length,
)

from .observation_limits import MAX_OBSERVATION_WINDOW_MS, is_finite_json_number
from .wire_numbers import MAX_SAFE_JSON_INTEGER

_MAX_IDENTIFIER_LENGTH = 200
_MAX_PAGE = 1_000_000
_MAX_PAGE_SIZE = 100
_MAX_SEARCH_UTF16_UNITS = 200
_MIN_SUPPORTED_UTC_YEAR = 1970
_METRIC_UNITS = {
    "http_qps": "requests_per_second",
    "resource_entry_rate": "entries_per_second",
    "tps": "transactions_per_second",
    "rt_p95": "milliseconds",
    "blocked_ratio": "ratio",
    "cpu_ratio": "ratio",
    "memory_ratio": "ratio",
    "memory_bytes": "bytes",
}


class ObservationScope(StrEnum):
    """Scope requested for the instance directory observation."""

    FLEET = "fleet"
    APPLICATION = "application"
    HOST = "host"
    CONTAINER = "container"
    PROCESS = "process"


class InstanceHealth(StrEnum):
    """Finite health classification supplied by the observation authority."""

    HEALTHY = "healthy"
    ATTENTION = "attention"
    UNKNOWN = "unknown"


class InstanceLayer(StrEnum):
    """Collection layers explicitly supported by one observed process."""

    HOST = "host"
    CONTAINER = "container"
    PROCESS = "process"


class RuleReceiptState(StrEnum):
    """Finite status of the desired ruleset at one process incarnation."""

    APPLIED = "applied"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"


class MetricDenominator(StrEnum):
    """Stable aggregation basis; never infer a denominator from a display unit."""

    REPORTING_PROCESSES = "reporting_processes"
    REPORTING_HOSTS = "reporting_hosts"
    REPORTING_CONTAINERS = "reporting_containers"
    CPU_CORES = "cpu_cores"
    MEMORY_LIMIT_BYTES = "memory_limit_bytes"
    COMPLETED_HTTP_REQUESTS = "completed_http_requests"
    ATTEMPTED_ENTRIES = "attempted_entries"
    BUSINESS_TRANSACTIONS = "business_transactions"
    ELAPSED_SECONDS = "elapsed_seconds"


class MetricQuality(StrEnum):
    """Quality of a metric sample, distinct from its numeric value."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    STALE = "stale"
    NO_SAMPLES = "no_samples"
    NOT_INTEGRATED = "not_integrated"


OPERATIONAL_METRIC_DEFINITIONS = (
    (
        "http_qps",
        _METRIC_UNITS["http_qps"],
        MetricDenominator.COMPLETED_HTTP_REQUESTS,
    ),
    ("tps", _METRIC_UNITS["tps"], MetricDenominator.BUSINESS_TRANSACTIONS),
    (
        "rt_p95",
        _METRIC_UNITS["rt_p95"],
        MetricDenominator.COMPLETED_HTTP_REQUESTS,
    ),
    (
        "blocked_ratio",
        _METRIC_UNITS["blocked_ratio"],
        MetricDenominator.ATTEMPTED_ENTRIES,
    ),
    ("cpu_ratio", _METRIC_UNITS["cpu_ratio"], MetricDenominator.CPU_CORES),
    (
        "memory_ratio",
        _METRIC_UNITS["memory_ratio"],
        MetricDenominator.MEMORY_LIMIT_BYTES,
    ),
)
OPERATIONAL_METRIC_NAMES = tuple(
    metric for metric, _unit, _denominator in OPERATIONAL_METRIC_DEFINITIONS
)
_OPERATIONAL_METRICS = frozenset(OPERATIONAL_METRIC_NAMES)
METRIC_UNITS = MappingProxyType(_METRIC_UNITS)
OPERATIONAL_METRICS = _OPERATIONAL_METRICS


def _is_aware_instant(value: datetime | None) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
    )


def _is_identifier(value: str | None) -> bool:
    return is_bounded_wire_identifier(value, _MAX_IDENTIFIER_LENGTH)


def _is_count(value: int) -> bool:
    return type(value) is int and 0 <= value <= MAX_SAFE_JSON_INTEGER


is_aware_instant = _is_aware_instant
is_observation_identifier = _is_identifier
is_observation_count = _is_count


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """A bounded half-open UTC interval used to qualify instance metrics."""

    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        if not _is_aware_instant(self.starts_at) or not _is_aware_instant(self.ends_at):
            raise ValueError("observation window instants must be timezone-aware")
        duration_ms = (self.ends_at - self.starts_at).total_seconds() * 1000
        if not 0 < duration_ms <= MAX_OBSERVATION_WINDOW_MS:
            raise ValueError(
                "observation window must be positive and at most seven days"
            )

    def contains(self, value: datetime) -> bool:
        return self.starts_at <= value < self.ends_at

    @property
    def duration_ms(self) -> float:
        """Return the half-open window duration in milliseconds."""
        return (self.ends_at - self.starts_at).total_seconds() * 1000


@dataclass(frozen=True, slots=True)
class InstanceCatalogQuery:
    """The explicit filters and paging requested by an authorized Console user."""

    environment_id: str
    app_id: str | None
    instance_id: str | None
    resource: str | None
    scope: ObservationScope
    window: ObservationWindow
    page: int
    page_size: int
    search: str
    attention_only: bool

    def __post_init__(self) -> None:
        optional_ids = (self.app_id, self.instance_id, self.resource)
        if not _is_identifier(self.environment_id) or any(
            value is not None and not _is_identifier(value) for value in optional_ids
        ):
            raise ValueError("instance catalog query identity is invalid")
        if not isinstance(self.scope, ObservationScope):
            raise ValueError("instance catalog scope is unsupported")
        expected_scope = (
            ObservationScope.FLEET
            if self.app_id is None
            else ObservationScope.APPLICATION
        )
        if (
            self.scope is not expected_scope
            or self.instance_id is not None
            or self.resource is not None
        ):
            raise ValueError("instance catalog context is not a directory scope")
        if not isinstance(self.window, ObservationWindow):
            raise ValueError("instance catalog query window is invalid")
        if type(self.page) is not int or not 1 <= self.page <= _MAX_PAGE:
            raise ValueError("instance catalog page is out of range")
        if type(self.page_size) is not int or not 1 <= self.page_size <= _MAX_PAGE_SIZE:
            raise ValueError("instance catalog page size is out of range")
        if (
            not isinstance(self.search, str)
            or _utf16_length(self.search) > _MAX_SEARCH_UTF16_UNITS
        ):
            raise ValueError("instance catalog search is out of range")
        if type(self.attention_only) is not bool:
            raise ValueError("instance catalog attention filter must be boolean")


@dataclass(frozen=True, slots=True)
class ObservationCoverage:
    """Known inventory denominator, or an explicit unknown pair, plus reporters."""

    expected: int | None
    inventory_source: str | None
    reporting: int

    def __post_init__(self) -> None:
        if self.expected is None:
            if self.inventory_source is not None:
                raise ValueError("unknown inventory cannot name an inventory source")
        elif not _is_count(self.expected) or not _is_identifier(self.inventory_source):
            raise ValueError("known inventory requires a bounded count and source")
        if not _is_count(self.reporting):
            raise ValueError("reporting count is out of range")
        if self.expected is not None and self.reporting > self.expected:
            raise ValueError("reporting count cannot exceed expected inventory")


@dataclass(frozen=True, slots=True)
class MetricReading:
    """One process-level metric with explicit source, denominator and quality."""

    source: str
    denominator: MetricDenominator
    coverage: ObservationCoverage
    quality: MetricQuality
    metric: str
    unit: str
    value: int | float | None
    sampled_at: datetime | None

    def __post_init__(self) -> None:
        if not _is_identifier(self.source):
            raise ValueError("metric source is invalid")
        if not isinstance(self.denominator, MetricDenominator):
            raise ValueError("metric denominator is unsupported")
        if not isinstance(self.coverage, ObservationCoverage):
            raise ValueError("metric coverage is invalid")
        if not isinstance(self.quality, MetricQuality):
            raise ValueError("metric quality is unsupported")
        if self.metric not in _METRIC_UNITS or self.unit != _METRIC_UNITS[self.metric]:
            raise ValueError("metric unit does not match the metric")
        if self.value is not None:
            if (
                not is_finite_json_number(self.value)
                or self.value < 0
            ):
                raise ValueError("metric value must be finite and non-negative")
            if self.unit == "ratio" and self.value > 1:
                raise ValueError("ratio metrics must be between zero and one")
        if self.value is None:
            if self.sampled_at is not None:
                raise ValueError("missing metric values cannot have a sample time")
        elif not _is_aware_instant(self.sampled_at):
            raise ValueError("sampled metric values require an aware sample time")
        if self.quality is MetricQuality.AVAILABLE and (
            self.value is None
            or self.coverage.expected is None
            or self.coverage.reporting == 0
            or self.coverage.reporting != self.coverage.expected
        ):
            raise ValueError("available metrics require complete non-empty coverage")
        if self.quality in (MetricQuality.NO_SAMPLES, MetricQuality.NOT_INTEGRATED):
            if self.value is not None or self.coverage.reporting != 0:
                raise ValueError(
                    "unobserved metrics cannot contain values or reporters"
                )
        elif self.value is not None and self.coverage.reporting == 0:
            raise ValueError("metric values require at least one reporting source")


@dataclass(frozen=True, slots=True)
class InstanceRuleReceipt:
    """Rule delivery acknowledgement bound to one exact process incarnation."""

    state: RuleReceiptState
    desired_version_id: str | None
    applied_version_id: str | None
    process_epoch: str
    received_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, RuleReceiptState):
            raise ValueError("rule receipt state is unsupported")
        if not _is_identifier(self.process_epoch):
            raise ValueError("rule receipt process epoch is invalid")
        if any(
            value is not None and not _is_identifier(value)
            for value in (self.desired_version_id, self.applied_version_id)
        ):
            raise ValueError("rule receipt version identity is invalid")
        if self.received_at is not None and not _is_aware_instant(self.received_at):
            raise ValueError("rule receipt time must be timezone-aware")
        if self.state is RuleReceiptState.APPLIED and (
            self.applied_version_id is None
            or self.applied_version_id != self.desired_version_id
            or self.received_at is None
        ):
            raise ValueError(
                "applied receipt must confirm the desired version and time"
            )


@dataclass(frozen=True, slots=True)
class ObservedInstance:
    """One instance incarnation with explicit process-level metric summaries."""

    instance_id: str
    app_id: str
    environment_id: str
    host_id: str | None
    container_id: str | None
    process_id: str | None
    process_epoch: str
    health: InstanceHealth
    last_report_at: datetime | None
    supported_scopes: tuple[InstanceLayer, ...]
    rule_receipt: InstanceRuleReceipt
    process_metrics: tuple[MetricReading, ...]

    def __post_init__(self) -> None:
        identity_values = (
            self.instance_id,
            self.app_id,
            self.environment_id,
            self.process_epoch,
        )
        optional_ids = (self.host_id, self.container_id, self.process_id)
        if not all(_is_identifier(value) for value in identity_values) or any(
            value is not None and not _is_identifier(value) for value in optional_ids
        ):
            raise ValueError("instance identity is invalid")
        if not isinstance(self.health, InstanceHealth):
            raise ValueError("instance health is unsupported")
        if self.last_report_at is not None and not _is_aware_instant(
            self.last_report_at
        ):
            raise ValueError("last report time must be timezone-aware")
        if (
            not isinstance(self.supported_scopes, tuple)
            or len(self.supported_scopes) > 3
        ):
            raise ValueError("instance scopes must be a bounded tuple")
        if any(not isinstance(scope, InstanceLayer) for scope in self.supported_scopes):
            raise ValueError("instance scope is unsupported")
        if len(set(self.supported_scopes)) != len(self.supported_scopes):
            raise ValueError("instance scopes must be unique")
        scope_identity = {
            InstanceLayer.HOST: self.host_id,
            InstanceLayer.CONTAINER: self.container_id,
            InstanceLayer.PROCESS: self.process_id,
        }
        if any(
            scope_identity[scope] is None for scope in self.supported_scopes
        ):
            raise ValueError(
                "supported scopes require their matching instance identity"
            )
        if not isinstance(self.rule_receipt, InstanceRuleReceipt) or (
            self.rule_receipt.process_epoch != self.process_epoch
        ):
            raise ValueError(
                "rule receipt must identify the current process incarnation"
            )
        if (
            not isinstance(self.process_metrics, tuple)
            or len(self.process_metrics) != len(_OPERATIONAL_METRICS)
            or any(not isinstance(item, MetricReading) for item in self.process_metrics)
            or {item.metric for item in self.process_metrics} != _OPERATIONAL_METRICS
        ):
            raise ValueError(
                "process metrics must contain the six operational metrics once"
            )


@dataclass(frozen=True, slots=True)
class InstanceCatalogSnapshot:
    """A bounded page with full-population counters and its exact query echo."""

    query: InstanceCatalogQuery
    as_of: datetime
    coverage: ObservationCoverage
    total_instances: int
    attention_instances: int
    filtered_total: int
    items: tuple[ObservedInstance, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, InstanceCatalogQuery) or not _is_aware_instant(
            self.as_of
        ):
            raise ValueError("instance catalog snapshot identity or time is invalid")
        if not isinstance(self.coverage, ObservationCoverage):
            raise ValueError("instance catalog coverage is invalid")
        counts = (self.total_instances, self.attention_instances, self.filtered_total)
        if not all(_is_count(value) for value in counts):
            raise ValueError("instance catalog counts are invalid")
        if (
            self.attention_instances > self.total_instances
            or self.filtered_total
            > (
                self.attention_instances
                if self.query.attention_only
                else self.total_instances
            )
        ):
            raise ValueError("instance catalog filtered counts exceed their population")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > self.query.page_size
            or any(not isinstance(item, ObservedInstance) for item in self.items)
        ):
            raise ValueError("instance catalog items exceed the requested page")
        page_offset = (self.query.page - 1) * self.query.page_size
        if len(self.items) > self.filtered_total or (
            page_offset >= self.filtered_total and self.items
        ):
            raise ValueError(
                "instance catalog page contradicts its filtered total"
            )
        identities = {(item.app_id, item.instance_id) for item in self.items}
        if len(identities) != len(self.items):
            raise ValueError("instance catalog page contains duplicate instances")
        for item in self.items:
            if (
                item.environment_id != self.query.environment_id
                or (self.query.app_id is not None and item.app_id != self.query.app_id)
                or (
                    self.query.instance_id is not None
                    and item.instance_id != self.query.instance_id
                )
                or (
                    self.query.attention_only
                    and item.health is not InstanceHealth.ATTENTION
                )
                or any(
                    metric.sampled_at is not None
                    and not self.query.window.contains(metric.sampled_at)
                    for metric in item.process_metrics
                )
            ):
                raise ValueError("instance page facts contradict the requested query")
