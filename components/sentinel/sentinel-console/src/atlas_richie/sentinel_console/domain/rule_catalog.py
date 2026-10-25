"""Bounded current-source rule catalog projections for the Console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .rule_bindings import RuleBinding, RuleKind, is_rule_binding_identifier
from .rule_snapshots import RuleRecord
from .wire_strings import is_bounded_wire_text

MAX_RULE_CATALOG_PAGE_SIZE = 100
MAX_RULE_CATALOG_PAGE_NUMBER = 1_000_000
MAX_RULE_CATALOG_SEARCH_LENGTH = 200
MAX_RULE_CATALOG_ISSUES = 100
MAX_RULE_BINDING_STATE_PAGE_SIZE = 100


class RuleBindingObservedState(StrEnum):
    """Provider-confirmed state for one registered rule binding."""

    CURRENT_WITH_RULES = "current_with_rules"
    CONFIGURED_EMPTY = "configured_empty"
    TARGET_MISSING = "target_missing"
    CONTENT_INVALID = "content_invalid"
    UNSUPPORTED_PROFILE = "unsupported_profile"
    SOURCE_UNAVAILABLE = "source_unavailable"
    NOT_READ = "not_read"


@dataclass(frozen=True, slots=True)
class RuleBindingStatesQuery:
    """Bounded filter and page for provider state, separate from rule rows."""

    environment_id: str
    app_id: str | None
    kind: RuleKind | None
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if (
            not is_rule_binding_identifier(self.environment_id)
            or (self.app_id is not None and not is_rule_binding_identifier(self.app_id))
            or (self.kind is not None and not isinstance(self.kind, RuleKind))
            or type(self.page) is not int
            or not 1 <= self.page <= MAX_RULE_CATALOG_PAGE_NUMBER
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= MAX_RULE_BINDING_STATE_PAGE_SIZE
        ):
            raise ValueError("rule binding state query is outside its bounds")


@dataclass(frozen=True, slots=True)
class RuleBindingObservedStateItem:
    """One binding's safe provider outcome and last-known-good indicator."""

    binding: RuleBinding
    state: RuleBindingObservedState
    rule_count: int | None
    source_revision: str | None
    last_attempt_at: datetime | None
    freshness: RuleCatalogFreshness
    has_last_known_good: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.binding, RuleBinding)
            or not isinstance(self.state, RuleBindingObservedState)
            or (self.rule_count is not None and (type(self.rule_count) is not int or self.rule_count < 0))
            or (self.source_revision is not None and not isinstance(self.source_revision, str))
            or (self.last_attempt_at is not None and not _aware_instant(self.last_attempt_at))
            or not isinstance(self.freshness, RuleCatalogFreshness)
            or type(self.has_last_known_good) is not bool
            or (self.state is RuleBindingObservedState.CURRENT_WITH_RULES and not self.rule_count)
            or (self.state is RuleBindingObservedState.CONFIGURED_EMPTY and self.rule_count != 0)
            or (
                self.state in {
                    RuleBindingObservedState.TARGET_MISSING,
                    RuleBindingObservedState.CONTENT_INVALID,
                    RuleBindingObservedState.UNSUPPORTED_PROFILE,
                    RuleBindingObservedState.SOURCE_UNAVAILABLE,
                    RuleBindingObservedState.NOT_READ,
                }
                and self.rule_count is not None
            )
            or (self.state is RuleBindingObservedState.NOT_READ and self.has_last_known_good)
        ):
            raise ValueError("rule binding observed state is inconsistent")


@dataclass(frozen=True, slots=True)
class RuleBindingStatesPage:
    """Stable server-paginated provider state projection."""

    query: RuleBindingStatesQuery
    as_of: datetime
    coverage: RuleCatalogCoverage
    total: int | None
    has_more: bool
    items: tuple[RuleBindingObservedStateItem, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.query, RuleBindingStatesQuery)
            or not _aware_instant(self.as_of)
            or not isinstance(self.coverage, RuleCatalogCoverage)
            or (self.total is not None and (type(self.total) is not int or self.total < 0))
            or ((self.coverage is RuleCatalogCoverage.COMPLETE) != (self.total is not None))
            or type(self.has_more) is not bool
            or not isinstance(self.items, tuple)
            or len(self.items) > self.query.page_size
            or (self.total is not None and self.has_more != (
                (self.query.page - 1) * self.query.page_size + len(self.items) < self.total
            ))
        ):
            raise ValueError("rule binding states page is inconsistent")


def _aware_instant(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


class RuleCatalogCoverage(StrEnum):
    """Whether all registered bindings in the selected scope were freshly read."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class RuleCatalogFreshness(StrEnum):
    """Current projection freshness for one binding's last source read."""

    CURRENT = "current"
    STALE = "stale"
    NOT_READ = "not_read"


class RuleCatalogIssueReason(StrEnum):
    """Safe per-binding outcomes; raw provider errors never reach the UI."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    CONTENT_INVALID = "content_invalid"
    NOT_READ = "not_read"


@dataclass(frozen=True, slots=True)
class RuleCatalogQuery:
    """Exact environment/application/type/resource filter and bounded page."""

    environment_id: str
    app_id: str | None
    kind: RuleKind | None
    search: str
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if not is_rule_binding_identifier(self.environment_id):
            raise ValueError("rule catalog environment is required")
        if self.app_id is not None and not is_rule_binding_identifier(self.app_id):
            raise ValueError("rule catalog application is invalid")
        if self.kind is not None and not isinstance(self.kind, RuleKind):
            raise ValueError("rule catalog rule kind is invalid")
        if (
            not isinstance(self.search, str)
            or not is_bounded_wire_text(self.search, MAX_RULE_CATALOG_SEARCH_LENGTH)
            or type(self.page) is not int
            or not 1 <= self.page <= MAX_RULE_CATALOG_PAGE_NUMBER
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= MAX_RULE_CATALOG_PAGE_SIZE
        ):
            raise ValueError("rule catalog query is outside its bounds")


@dataclass(frozen=True, slots=True)
class RuleCatalogEntry:
    """One typed rule tied to the exact source snapshot that was read."""

    binding: RuleBinding
    record: RuleRecord
    checksum: str
    source_revision: str | None
    version_id: str | None
    snapshot_as_of: datetime
    last_attempt_at: datetime
    freshness: RuleCatalogFreshness

    def __post_init__(self) -> None:
        if (
            not isinstance(self.binding, RuleBinding)
            or not isinstance(self.record, RuleRecord)
            or self.record.rule.kind is not self.binding.kind
            or not self.checksum
            or not isinstance(self.snapshot_as_of, datetime)
            or self.snapshot_as_of.tzinfo is None
            or not isinstance(self.last_attempt_at, datetime)
            or self.last_attempt_at.tzinfo is None
            or not isinstance(self.freshness, RuleCatalogFreshness)
        ):
            raise ValueError("rule catalog entry is inconsistent")


@dataclass(frozen=True, slots=True)
class RuleCatalogIssue:
    """Redacted status for one binding that is not currently readable."""

    binding: RuleBinding
    reason: RuleCatalogIssueReason
    last_attempt_at: datetime | None
    stale: bool


@dataclass(frozen=True, slots=True)
class RuleCatalogPage:
    """One server-paginated projection with explicit scope coverage."""

    query: RuleCatalogQuery
    as_of: datetime
    coverage: RuleCatalogCoverage
    bindings_total: int
    bindings_current: int
    bindings_stale: int
    bindings_not_read: int
    total: int | None
    has_more: bool
    items: tuple[RuleCatalogEntry, ...]
    issues: tuple[RuleCatalogIssue, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.query, RuleCatalogQuery)
            or not isinstance(self.as_of, datetime)
            or self.as_of.tzinfo is None
            or not isinstance(self.coverage, RuleCatalogCoverage)
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.bindings_total,
                    self.bindings_current,
                    self.bindings_stale,
                    self.bindings_not_read,
                )
            )
            or self.bindings_current + self.bindings_stale + self.bindings_not_read
            != self.bindings_total
            or (self.total is not None and (type(self.total) is not int or self.total < 0))
            or (self.coverage is RuleCatalogCoverage.COMPLETE) != (self.total is not None)
            or type(self.has_more) is not bool
            or not isinstance(self.items, tuple)
            or len(self.items) > self.query.page_size
            or (
                self.total is not None
                and self.has_more != (
                    (self.query.page - 1) * self.query.page_size + len(self.items)
                    < self.total
                )
            )
            or not isinstance(self.issues, tuple)
            or len(self.issues) > MAX_RULE_CATALOG_ISSUES
        ):
            raise ValueError("rule catalog page is inconsistent")


@dataclass(frozen=True, slots=True)
class RuleCatalogRefreshResult:
    """Outcome of one bounded source-read batch for an explicit scope."""

    environment_id: str
    app_id: str | None
    as_of: datetime
    coverage: RuleCatalogCoverage
    bindings_total: int
    bindings_attempted: int
    bindings_current: int
    bindings_stale: int
    bindings_not_read: int


__all__ = [
    "MAX_RULE_BINDING_STATE_PAGE_SIZE",
    "MAX_RULE_CATALOG_ISSUES",
    "MAX_RULE_CATALOG_PAGE_NUMBER",
    "MAX_RULE_CATALOG_PAGE_SIZE",
    "MAX_RULE_CATALOG_SEARCH_LENGTH",
    "RuleCatalogCoverage",
    "RuleCatalogEntry",
    "RuleCatalogFreshness",
    "RuleCatalogIssue",
    "RuleCatalogIssueReason",
    "RuleCatalogPage",
    "RuleCatalogQuery",
    "RuleCatalogRefreshResult",
    "RuleBindingObservedState",
    "RuleBindingObservedStateItem",
    "RuleBindingStatesPage",
    "RuleBindingStatesQuery",
]
