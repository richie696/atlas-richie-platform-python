"""Bounded structured incident facts and query-bound timeline snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .instance_catalog import (
    ObservationScope,
    ObservationWindow,
    is_aware_instant,
    is_observation_count,
    is_observation_identifier,
)
from .instance_observation import ObservationContext
from .observation_limits import is_finite_json_number
from .wire_strings import (
    is_bounded_wire_identifier,
)

MAX_INCIDENT_PAGE_SIZE = 100
MAX_INCIDENT_CURSOR_LENGTH = 512
MAX_INCIDENT_EVIDENCE_ITEMS = 100


class IncidentSeverity(StrEnum):
    """Finite severity values accepted by incident query filters."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IncidentCategory(StrEnum):
    """Finite event categories; publication and application remain distinct."""

    RESOURCE = "resource"
    RESPONSE_TIME = "rt"
    RULE_PUBLISHED = "rulePublished"
    RULE_EFFECTIVE = "ruleEffective"


class IncidentFactCode(StrEnum):
    """Allowlisted structured facts; arbitrary messages are intentionally absent."""

    RESOURCE_PRESSURE = "resource_pressure"
    RESPONSE_TIME = "response_time"
    RULE_PUBLISHED = "rule_published"
    RULE_APPLIED = "rule_applied"


@dataclass(frozen=True, slots=True)
class IncidentFact:
    """One finite caption fact with only fields valid for its discriminator."""

    code: IncidentFactCode
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None
    value_ms: float | None = None
    threshold_ms: float | None = None
    version_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, IncidentFactCode):
            raise ValueError("incident fact code is unsupported")
        if self.code is IncidentFactCode.RESOURCE_PRESSURE:
            if (
                self.metric not in ("cpu_ratio", "memory_ratio")
                or not _ratio(self.value)
                or not _ratio(self.threshold)
                or any(
                    value is not None
                    for value in (self.value_ms, self.threshold_ms, self.version_id)
                )
            ):
                raise ValueError("resource pressure fact is invalid")
        elif self.code is IncidentFactCode.RESPONSE_TIME:
            if (
                not _finite_nonnegative(self.value_ms)
                or not _finite_nonnegative(self.threshold_ms)
                or any(
                    value is not None
                    for value in (
                        self.metric,
                        self.value,
                        self.threshold,
                        self.version_id,
                    )
                )
            ):
                raise ValueError("response-time fact is invalid")
        elif self.code in (
            IncidentFactCode.RULE_PUBLISHED,
            IncidentFactCode.RULE_APPLIED,
        ):
            if (
                not is_observation_identifier(self.version_id)
                or any(
                    value is not None
                    for value in (
                        self.metric,
                        self.value,
                        self.threshold,
                        self.value_ms,
                        self.threshold_ms,
                    )
                )
            ):
                raise ValueError("rule incident fact is invalid")


@dataclass(frozen=True, slots=True)
class IncidentQuery:
    """Explicit observation scope, half-open window, filters, and opaque cursor."""

    context: ObservationContext
    severity: IncidentSeverity | None
    category: IncidentCategory | None
    cursor: str | None
    page_size: int

    def __post_init__(self) -> None:
        _validate_incident_filters(self.context, self.severity, self.category)
        if self.cursor is not None and (
            not _is_incident_cursor(self.cursor)
        ):
            raise ValueError("incident cursor is invalid")
        if (
            type(self.page_size) is not int
            or not 1 <= self.page_size <= MAX_INCIDENT_PAGE_SIZE
        ):
            raise ValueError("incident page size is out of range")


@dataclass(frozen=True, slots=True)
class ObservedIncident:
    """A recorded incident with safe identifiers and structured facts only."""

    id: str
    environment_id: str
    app_id: str
    instance_id: str | None
    process_epoch: str | None
    occurred_at: datetime
    received_at: datetime
    severity: IncidentSeverity
    category: IncidentCategory
    source_event_id: str | None
    publication_id: str | None
    caption: IncidentFact

    def __post_init__(self) -> None:
        required = (self.id, self.environment_id, self.app_id)
        optional = (
            self.instance_id,
            self.process_epoch,
            self.source_event_id,
            self.publication_id,
        )
        if not all(is_observation_identifier(value) for value in required) or any(
            value is not None and not is_observation_identifier(value)
            for value in optional
        ):
            raise ValueError("incident identity is invalid")
        if self.instance_id is None and self.process_epoch is not None:
            raise ValueError("process epoch requires an instance")
        if not is_aware_instant(self.occurred_at) or not is_aware_instant(
            self.received_at
        ):
            raise ValueError("incident timestamps must be timezone-aware")
        if not isinstance(self.severity, IncidentSeverity) or not isinstance(
            self.category, IncidentCategory
        ):
            raise ValueError("incident classification is unsupported")
        if not isinstance(self.caption, IncidentFact):
            raise ValueError("incident caption is invalid")
        expected_category = {
            IncidentFactCode.RESOURCE_PRESSURE: IncidentCategory.RESOURCE,
            IncidentFactCode.RESPONSE_TIME: IncidentCategory.RESPONSE_TIME,
            IncidentFactCode.RULE_PUBLISHED: IncidentCategory.RULE_PUBLISHED,
            IncidentFactCode.RULE_APPLIED: IncidentCategory.RULE_EFFECTIVE,
        }[self.caption.code]
        if self.category is not expected_category:
            raise ValueError("incident category does not match its fact")


@dataclass(frozen=True, slots=True)
class IncidentStatistics:
    """Whole-scope counters independent of filters and cursor pagination."""

    total: int
    critical: int
    warning: int
    info: int
    rule_changes: int
    affected_applications: int

    def __post_init__(self) -> None:
        values = (
            self.total,
            self.critical,
            self.warning,
            self.info,
            self.rule_changes,
            self.affected_applications,
        )
        if not all(is_observation_count(value) for value in values):
            raise ValueError("incident statistics contain an invalid count")
        if (
            self.total != self.critical + self.warning + self.info
            or self.rule_changes > self.total
            or self.affected_applications > self.total
        ):
            raise ValueError("incident statistics are inconsistent")


@dataclass(frozen=True, slots=True)
class IncidentPage:
    """One bounded filtered page plus whole-scope statistics at a read instant."""

    query: IncidentQuery
    as_of: datetime
    statistics: IncidentStatistics
    items: tuple[ObservedIncident, ...]
    filtered_total: int
    next_cursor: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.query, IncidentQuery) or not is_aware_instant(
            self.as_of
        ):
            raise ValueError("incident page query or read time is invalid")
        if not isinstance(self.statistics, IncidentStatistics):
            raise ValueError("incident page statistics are invalid")
        if not isinstance(self.items, tuple) or len(self.items) > self.query.page_size:
            raise ValueError("incident page exceeds its requested size")
        if any(not isinstance(item, ObservedIncident) for item in self.items):
            raise ValueError("incident page contains an invalid event")
        if (
            not is_observation_count(self.filtered_total)
            or self.filtered_total > self.statistics.total
        ):
            raise ValueError("incident filtered total is invalid")
        if self.query.severity is not None and self.filtered_total > getattr(
            self.statistics, self.query.severity.value
        ):
            raise ValueError("incident filtered total exceeds severity total")
        ids = tuple(item.id for item in self.items)
        if len(set(ids)) != len(ids):
            raise ValueError("incident page contains duplicate IDs")
        if any(not _matches_query(item, self.query) for item in self.items):
            raise ValueError("incident page contains an event outside the query")
        if any(
            not _precedes(first, second)
            for first, second in zip(self.items, self.items[1:])
        ):
            raise ValueError("incident page is not in canonical descending order")
        if self.next_cursor is not None and (
            not _is_incident_cursor(self.next_cursor)
            or self.next_cursor == self.query.cursor
            or not self.items
        ):
            raise ValueError("incident next cursor is invalid")


@dataclass(frozen=True, slots=True)
class IncidentDetailQuery:
    """Identity and active filters for one explicitly selected event."""

    context: ObservationContext
    event_id: str
    severity: IncidentSeverity | None
    category: IncidentCategory | None

    def __post_init__(self) -> None:
        _validate_incident_filters(self.context, self.severity, self.category)
        if not is_observation_identifier(self.event_id):
            raise ValueError("incident detail event ID is invalid")


class IncidentEvidenceCompleteness(StrEnum):
    """Explicit completeness of evidence returned by the authority."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class IncidentSuggestedView(StrEnum):
    """Read-only destinations offered by currently available evidence."""

    INSTANCE = "instance"
    METRICS = "metrics"
    RULES = "rules"


@dataclass(frozen=True, slots=True)
class IncidentEvidenceFact:
    """One bounded, source-identified fact associated with an incident."""

    id: str
    source: str
    at: datetime
    fact: IncidentFact

    def __post_init__(self) -> None:
        if not is_observation_identifier(self.id) or not is_observation_identifier(
            self.source
        ):
            raise ValueError("incident evidence identity is invalid")
        if not is_aware_instant(self.at) or not isinstance(self.fact, IncidentFact):
            raise ValueError("incident evidence fact is invalid")


@dataclass(frozen=True, slots=True)
class RelatedRuleIdentity:
    """Exact rule address supplied by an authority, never inferred by the UI."""

    environment_id: str
    app_id: str
    binding_id: str
    version_id: str
    publication_id: str

    def __post_init__(self) -> None:
        values = (
            self.environment_id,
            self.app_id,
            self.binding_id,
            self.version_id,
            self.publication_id,
        )
        if not all(is_observation_identifier(value) for value in values):
            raise ValueError("related rule identity is invalid")


@dataclass(frozen=True, slots=True)
class IncidentEvidence:
    """A selected event and its bounded evidence, without causal conclusions."""

    query: IncidentDetailQuery
    as_of: datetime
    event: ObservedIncident
    facts: tuple[IncidentEvidenceFact, ...]
    completeness: IncidentEvidenceCompleteness
    suggested_views: tuple[IncidentSuggestedView, ...]
    related_rule: RelatedRuleIdentity | None

    def __post_init__(self) -> None:
        if not isinstance(self.query, IncidentDetailQuery) or not is_aware_instant(
            self.as_of
        ):
            raise ValueError("incident evidence query or read time is invalid")
        if not isinstance(self.event, ObservedIncident) or not _matches_detail_query(
            self.event, self.query
        ):
            raise ValueError("incident evidence event does not match its query")
        if (
            not isinstance(self.facts, tuple)
            or len(self.facts) > MAX_INCIDENT_EVIDENCE_ITEMS
            or any(not isinstance(item, IncidentEvidenceFact) for item in self.facts)
            or len({item.id for item in self.facts}) != len(self.facts)
        ):
            raise ValueError("incident evidence facts are invalid or unbounded")
        if not isinstance(self.completeness, IncidentEvidenceCompleteness):
            raise ValueError("incident evidence completeness is invalid")
        if (
            self.completeness is IncidentEvidenceCompleteness.COMPLETE
            and not self.facts
        ) or (
            self.completeness is IncidentEvidenceCompleteness.UNAVAILABLE
            and self.facts
        ):
            raise ValueError("incident evidence facts contradict completeness")
        if (
            not isinstance(self.suggested_views, tuple)
            or len(self.suggested_views) > len(IncidentSuggestedView)
            or any(
                not isinstance(view, IncidentSuggestedView)
                for view in self.suggested_views
            )
            or len(set(self.suggested_views)) != len(self.suggested_views)
        ):
            raise ValueError("incident suggested views are invalid")
        if self.related_rule is not None and not _matches_related_rule(
            self.event, self.related_rule
        ):
            raise ValueError("related rule does not match the selected event")
        if IncidentSuggestedView.INSTANCE in self.suggested_views and (
            self.event.instance_id is None
        ):
            raise ValueError("instance view requires an event instance")
        if IncidentSuggestedView.RULES in self.suggested_views and (
            self.related_rule is None
        ):
            raise ValueError("rules view requires an exact related rule")


def _validate_incident_filters(
    context: ObservationContext,
    severity: IncidentSeverity | None,
    category: IncidentCategory | None,
) -> None:
    if not isinstance(context, ObservationContext):
        raise ValueError("incident context is invalid")
    if context.resource is not None:
        raise ValueError("incident queries cannot select a resource")
    _validate_scope(context)
    if severity is not None and not isinstance(severity, IncidentSeverity):
        raise ValueError("incident severity filter is unsupported")
    if category is not None and not isinstance(category, IncidentCategory):
        raise ValueError("incident category filter is unsupported")


def _validate_scope(context: ObservationContext) -> None:
    scope = context.scope
    if scope is ObservationScope.FLEET:
        valid = context.app_id is None and context.instance_id is None
    elif scope is ObservationScope.APPLICATION:
        valid = context.app_id is not None and context.instance_id is None
    elif scope is ObservationScope.PROCESS:
        valid = context.app_id is not None and context.instance_id is not None
    else:
        valid = False
    if not valid:
        raise ValueError("incident scope identity is inconsistent")


def _matches_query(event: ObservedIncident, query: IncidentQuery) -> bool:
    context = query.context
    return (
        event.environment_id == context.environment_id
        and (context.app_id is None or event.app_id == context.app_id)
        and (context.instance_id is None or event.instance_id == context.instance_id)
        and context.window.contains(event.occurred_at)
        and (query.severity is None or event.severity is query.severity)
        and (query.category is None or event.category is query.category)
    )


def _matches_detail_query(
    event: ObservedIncident, query: IncidentDetailQuery
) -> bool:
    context = query.context
    return (
        event.id == query.event_id
        and event.environment_id == context.environment_id
        and (context.app_id is None or event.app_id == context.app_id)
        and (context.instance_id is None or event.instance_id == context.instance_id)
        and context.window.contains(event.occurred_at)
        and (query.severity is None or event.severity is query.severity)
        and (query.category is None or event.category is query.category)
    )


def _matches_related_rule(
    event: ObservedIncident, related_rule: RelatedRuleIdentity
) -> bool:
    return (
        event.environment_id == related_rule.environment_id
        and event.app_id == related_rule.app_id
        and event.publication_id == related_rule.publication_id
        and event.caption.code
        in (IncidentFactCode.RULE_PUBLISHED, IncidentFactCode.RULE_APPLIED)
        and event.caption.version_id == related_rule.version_id
    )


def _precedes(first: ObservedIncident, second: ObservedIncident) -> bool:
    return first.occurred_at > second.occurred_at or (
        first.occurred_at == second.occurred_at and first.id > second.id
    )


def _ratio(value: float | None) -> bool:
    return value is not None and _finite_nonnegative(value) and value <= 1


def _finite_nonnegative(value: float | None) -> bool:
    return is_finite_json_number(value) and value >= 0


def _is_incident_cursor(value: str) -> bool:
    return is_bounded_wire_identifier(value, MAX_INCIDENT_CURSOR_LENGTH)
