"""Bounded fleet overview facts for the Dashboard's top-level observation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math

from .instance_catalog import (
    OPERATIONAL_METRIC_NAMES,
    MetricReading,
    ObservationCoverage,
    ObservationScope,
    ObservationWindow,
    is_aware_instant,
    is_observation_count,
    is_observation_identifier,
)
from .instance_observation import MetricBundle, MetricQuery, ObservationContext
from .observation_limits import (
    MAX_OBSERVATION_POINTS,
    MAX_OBSERVATION_WINDOW_MS,
    is_finite_json_number,
)
from .wire_strings import is_bounded_wire_text

_MAX_PAGE = 1_000_000
_MAX_PAGE_SIZE = 100
_MAX_SEARCH_LENGTH = 200
_MAX_CONNECTIONS = 100
_METRIC_NAMES = frozenset(OPERATIONAL_METRIC_NAMES)


class FleetApplicationHealth(StrEnum):
    """Health classification supplied by the observation authority."""

    HEALTHY = "healthy"
    ATTENTION = "attention"
    UNKNOWN = "unknown"


class FleetConnectionProvider(StrEnum):
    """Independent dependency categories summarized on fleet overview."""

    NACOS = "nacos"
    CONSUL = "consul"
    COLLECTOR = "collector"


class FleetConnectionState(StrEnum):
    """Observed dependency state; browser reachability is not a substitute."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FleetQuery:
    """Exact fleet/application context, window, pagination, and series step."""

    context: ObservationContext
    page: int
    page_size: int
    search: str
    step_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.context, ObservationContext):
            raise ValueError("fleet query context is invalid")
        if (
            self.context.instance_id is not None
            or self.context.resource is not None
            or self.context.scope
            is not (
                ObservationScope.FLEET
                if self.context.app_id is None
                else ObservationScope.APPLICATION
            )
        ):
            raise ValueError("fleet query scope must be fleet or application")
        if type(self.page) is not int or not 1 <= self.page <= _MAX_PAGE:
            raise ValueError("fleet page is out of range")
        if type(self.page_size) is not int or not 1 <= self.page_size <= _MAX_PAGE_SIZE:
            raise ValueError("fleet page size is out of range")
        if not is_bounded_wire_text(self.search, _MAX_SEARCH_LENGTH):
            raise ValueError("fleet search is out of range")
        if (
            type(self.step_ms) is not int
            or not 1 <= self.step_ms <= MAX_OBSERVATION_WINDOW_MS
            or math.ceil(self.context.window.duration_ms / self.step_ms)
            > MAX_OBSERVATION_POINTS
        ):
            raise ValueError("fleet series step exceeds the sample bound")

    @property
    def metric_query(self) -> MetricQuery:
        """Return the aggregate metric query owned by this fleet request."""
        return MetricQuery(
            context=self.context,
            metrics=OPERATIONAL_METRIC_NAMES,
            step_ms=self.step_ms,
        )


@dataclass(frozen=True, slots=True)
class FleetApplication:
    """One application row with its own summary and coverage facts."""

    app_id: str
    name: str
    health: FleetApplicationHealth
    instance_coverage: ObservationCoverage
    rule_coverage: ObservationCoverage
    metrics: tuple[MetricReading, ...]

    def __post_init__(self) -> None:
        if not is_observation_identifier(self.app_id) or not is_observation_identifier(
            self.name
        ):
            raise ValueError("fleet application identity is invalid")
        if not isinstance(self.health, FleetApplicationHealth):
            raise ValueError("fleet application health is invalid")
        valid_instance_coverage = isinstance(
            self.instance_coverage, ObservationCoverage
        )
        valid_rule_coverage = isinstance(self.rule_coverage, ObservationCoverage)
        if not valid_instance_coverage or not valid_rule_coverage:
            raise ValueError("fleet application coverage is invalid")
        if (
            not isinstance(self.metrics, tuple)
            or len(self.metrics) != len(OPERATIONAL_METRIC_NAMES)
            or any(not isinstance(item, MetricReading) for item in self.metrics)
            or {item.metric for item in self.metrics} != _METRIC_NAMES
        ):
            raise ValueError("fleet application must have each operational metric once")


@dataclass(frozen=True, slots=True)
class FleetConnection:
    """A sanitized dependency health observation, separate from metric time."""

    id: str
    provider: FleetConnectionProvider
    state: FleetConnectionState
    checked_at: datetime | None
    latency_ms: float | None

    def __post_init__(self) -> None:
        if not is_observation_identifier(self.id):
            raise ValueError("fleet connection identity is invalid")
        if not isinstance(self.provider, FleetConnectionProvider) or not isinstance(
            self.state, FleetConnectionState
        ):
            raise ValueError("fleet connection classification is invalid")
        if self.checked_at is not None and not is_aware_instant(self.checked_at):
            raise ValueError("fleet connection check time is invalid")
        if self.latency_ms is not None and (
            not is_finite_json_number(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError("fleet connection latency is invalid")


@dataclass(frozen=True, slots=True)
class FleetApplicationPage:
    """One bounded application page with its full filtered population count."""

    items: tuple[FleetApplication, ...]
    total: int
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAX_PAGE_SIZE
            or any(not isinstance(item, FleetApplication) for item in self.items)
        ):
            raise ValueError("fleet application page is invalid or unbounded")
        if (
            not is_observation_count(self.total)
            or type(self.page) is not int
            or not 1 <= self.page <= _MAX_PAGE
        ):
            raise ValueError("fleet application page totals are invalid")
        if type(self.page_size) is not int or not 1 <= self.page_size <= _MAX_PAGE_SIZE:
            raise ValueError("fleet application page size is invalid")
        if len({item.app_id for item in self.items}) != len(self.items):
            raise ValueError("fleet application page identities must be unique")
        if len(self.items) > min(self.page_size, self.total):
            raise ValueError("fleet application page exceeds its declared size")


@dataclass(frozen=True, slots=True)
class FleetSnapshot:
    """Whole-population counters and exact-query facts for the overview page."""

    query: FleetQuery
    as_of: datetime
    coverage: ObservationCoverage
    total_applications: int
    attention_applications: int
    attention_targets: tuple[str, ...]
    applications: FleetApplicationPage
    metrics: MetricBundle
    connections: tuple[FleetConnection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, FleetQuery) or not is_aware_instant(self.as_of):
            raise ValueError("fleet snapshot query or observation time is invalid")
        if not isinstance(self.coverage, ObservationCoverage):
            raise ValueError("fleet coverage is invalid")
        valid_total = is_observation_count(self.total_applications)
        valid_attention_total = is_observation_count(self.attention_applications)
        if not valid_total or not valid_attention_total:
            raise ValueError("fleet application counters are invalid")
        if self.attention_applications > self.total_applications:
            raise ValueError("fleet attention count exceeds application count")
        if self.query.context.app_id is not None and self.total_applications > 1:
            raise ValueError("application query cannot report multiple applications")
        if (
            not isinstance(self.attention_targets, tuple)
            or len(self.attention_targets) > _MAX_PAGE_SIZE
            or any(
                not is_observation_identifier(value) for value in self.attention_targets
            )
            or len(set(self.attention_targets)) != len(self.attention_targets)
            or len(self.attention_targets) > self.attention_applications
        ):
            raise ValueError("fleet attention targets are invalid")
        if self.query.context.app_id is not None and any(
            target != self.query.context.app_id for target in self.attention_targets
        ):
            raise ValueError("application query contains a foreign attention target")
        if not isinstance(self.applications, FleetApplicationPage):
            raise ValueError("fleet application page is invalid")
        if (
            self.applications.page != self.query.page
            or self.applications.page_size != self.query.page_size
            or self.applications.total > self.total_applications
            or len(self.applications.items) > self.total_applications
        ):
            raise ValueError("fleet page does not match its request or population")
        if self.query.context.app_id is not None and any(
            item.app_id != self.query.context.app_id
            for item in self.applications.items
        ):
            raise ValueError("application response contains a foreign application")
        for item in self.applications.items:
            if any(
                reading.sampled_at is not None
                and not self.query.context.window.contains(reading.sampled_at)
                for reading in item.metrics
            ):
                raise ValueError("application metric is outside the requested window")
        if (
            not isinstance(self.metrics, MetricBundle)
            or self.metrics.query != self.query.metric_query
            or self.metrics.as_of != self.as_of
        ):
            raise ValueError("fleet aggregate metrics do not match the request")
        if (
            not isinstance(self.connections, tuple)
            or len(self.connections) > _MAX_CONNECTIONS
            or any(not isinstance(item, FleetConnection) for item in self.connections)
            or len({item.id for item in self.connections}) != len(self.connections)
        ):
            raise ValueError("fleet connection observations are invalid or unbounded")
