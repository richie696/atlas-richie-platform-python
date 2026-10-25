"""Typed, bounded Console read model for current per-instance rule loads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleLoadEventKind,
    RuleLoadFailureReason,
    RuleKind as ObservedRuleKind,
)

from .rule_bindings import is_rule_binding_identifier
from .rule_catalog import RuleCatalogCoverage

MAX_RULE_LOAD_QUERY_PAGE_SIZE = 100


class RuleLoadObservedState(StrEnum):
    """Current runtime state for one enrolled process and binding pair."""

    APPLIED = "applied"
    FAILED_KEEPS_LAST_KNOWN_GOOD = "failed_keeps_last_known_good"
    FAILED_BEFORE_FIRST_LOAD = "failed_before_first_load"
    NOT_OBSERVED = "not_observed"


class RuleLoadFreshness(StrEnum):
    """Freshness derived only from Collector-owned receipt time."""

    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RuleLoadObservationQuery:
    """Exact app scope with optional binding/instance and bounded page."""

    environment_id: str
    app_id: str
    binding_id: str | None
    instance_id: str | None
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if (
            not is_rule_binding_identifier(self.environment_id)
            or not is_rule_binding_identifier(self.app_id)
            or (self.binding_id is not None and not is_rule_binding_identifier(self.binding_id))
            or (self.instance_id is not None and not is_rule_binding_identifier(self.instance_id))
            or type(self.page) is not int
            or not 1 <= self.page <= 1_000_000
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= MAX_RULE_LOAD_QUERY_PAGE_SIZE
        ):
            raise ValueError("rule load observation query is outside its bounds")


@dataclass(frozen=True, slots=True)
class RuleLoadMemberView:
    """One compatible-profile rule membership fingerprint."""

    rule_kind: ObservedRuleKind
    fingerprint_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rule_kind, ObservedRuleKind)
            or not isinstance(self.fingerprint_sha256, str)
            or len(self.fingerprint_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.fingerprint_sha256)
        ):
            raise ValueError("rule-load member fingerprint is invalid")


@dataclass(frozen=True, slots=True)
class RuleLoadSnapshotView:
    """Safe projection of the accepted active snapshot metadata."""

    source_revision: str | None
    canonical_rules_sha256: str
    membership_complete: bool
    members: tuple[RuleLoadMemberView, ...]

    def __post_init__(self) -> None:
        if (
            (self.source_revision is not None and not isinstance(self.source_revision, str))
            or not _digest(self.canonical_rules_sha256)
            or type(self.membership_complete) is not bool
            or not isinstance(self.members, tuple)
            or len(self.members) > 8192
            or any(not isinstance(member, RuleLoadMemberView) for member in self.members)
            or (not self.membership_complete and self.members)
        ):
            raise ValueError("rule-load active snapshot is invalid")


@dataclass(frozen=True, slots=True)
class RuleLoadAttemptView:
    """Safe finite failure projection for the most recent load attempt."""

    source_revision: str | None
    canonical_rules_sha256: str | None
    failure_reason: RuleLoadFailureReason

    def __post_init__(self) -> None:
        if (
            (self.source_revision is not None and not isinstance(self.source_revision, str))
            or (self.canonical_rules_sha256 is not None and not _digest(self.canonical_rules_sha256))
            or not isinstance(self.failure_reason, RuleLoadFailureReason)
        ):
            raise ValueError("rule-load attempt is invalid")


@dataclass(frozen=True, slots=True)
class RuleLoadObservationItem:
    """One expected worker/binding pair with authenticated identity facts."""

    binding_id: str
    instance_id: str
    process_id: str
    process_epoch: str | None
    profile_id: str | None
    load_state: RuleLoadObservedState
    event_kind: RuleLoadEventKind | None
    active_snapshot: RuleLoadSnapshotView | None
    attempt: RuleLoadAttemptView | None
    observed_at: datetime | None
    received_at: datetime | None
    freshness: RuleLoadFreshness

    def __post_init__(self) -> None:
        if (
            not is_rule_binding_identifier(self.binding_id)
            or not is_rule_binding_identifier(self.instance_id)
            or not is_rule_binding_identifier(self.process_id)
            or (self.process_epoch is not None and not isinstance(self.process_epoch, str))
            or (self.profile_id is not None and not isinstance(self.profile_id, str))
            or not isinstance(self.load_state, RuleLoadObservedState)
            or (self.event_kind is not None and not isinstance(self.event_kind, RuleLoadEventKind))
            or (self.active_snapshot is not None and not isinstance(self.active_snapshot, RuleLoadSnapshotView))
            or (self.attempt is not None and not isinstance(self.attempt, RuleLoadAttemptView))
            or (self.observed_at is not None and not _aware(self.observed_at))
            or (self.received_at is not None and not _aware(self.received_at))
            or not isinstance(self.freshness, RuleLoadFreshness)
            or (self.event_kind is None and (self.observed_at is not None or self.received_at is not None))
            or (self.event_kind is not None and (self.observed_at is None or self.received_at is None))
            or (self.load_state is RuleLoadObservedState.FAILED_KEEPS_LAST_KNOWN_GOOD and self.active_snapshot is None)
            or (self.load_state is RuleLoadObservedState.FAILED_BEFORE_FIRST_LOAD and self.attempt is None)
        ):
            raise ValueError("rule-load observation item is inconsistent")


@dataclass(frozen=True, slots=True)
class RuleLoadObservationTargets:
    """Authoritative aggregate counts over the exact unpaginated query scope."""

    expected: int | None
    observed: int | None
    stale: int | None
    not_observed: int | None

    def __post_init__(self) -> None:
        values = (self.expected, self.observed, self.stale, self.not_observed)
        if all(value is None for value in values):
            return
        if (
            any(type(value) is not int or value < 0 for value in values)
            or self.observed is None
            or self.stale is None
            or self.not_observed is None
            or self.expected is None
            or self.observed + self.not_observed != self.expected
            or self.stale > self.observed
        ):
            raise ValueError("rule-load target counts are inconsistent")


@dataclass(frozen=True, slots=True)
class RuleLoadObservationPage:
    """Stable, server-paginated current load facts and target coverage."""

    query: RuleLoadObservationQuery
    as_of: datetime
    coverage: RuleCatalogCoverage
    targets: RuleLoadObservationTargets
    total: int | None
    has_more: bool
    items: tuple[RuleLoadObservationItem, ...]

    def __post_init__(self) -> None:
        identities = tuple((item.binding_id, item.instance_id) for item in self.items)
        if (
            not isinstance(self.query, RuleLoadObservationQuery)
            or not _aware(self.as_of)
            or not isinstance(self.coverage, RuleCatalogCoverage)
            or not isinstance(self.targets, RuleLoadObservationTargets)
            or (self.total is not None and (type(self.total) is not int or self.total < 0))
            or ((self.coverage is RuleCatalogCoverage.COMPLETE) != (self.total is not None))
            or type(self.has_more) is not bool
            or not isinstance(self.items, tuple)
            or len(self.items) > self.query.page_size
            or any(not isinstance(item, RuleLoadObservationItem) for item in self.items)
            or len(set(identities)) != len(identities)
            or identities != tuple(sorted(identities))
            or any(
                item.binding_id != self.query.binding_id
                for item in self.items
                if self.query.binding_id is not None
            )
            or any(
                item.instance_id != self.query.instance_id
                for item in self.items
                if self.query.instance_id is not None
            )
            or (
                self.total is not None
                and self.has_more
                != ((self.query.page - 1) * self.query.page_size + len(self.items) < self.total)
            )
            or (self.coverage is RuleCatalogCoverage.COMPLETE and self.targets.expected is None)
            or (self.coverage is RuleCatalogCoverage.PARTIAL and self.targets.expected is not None)
        ):
            raise ValueError("rule-load observation page is inconsistent")


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "MAX_RULE_LOAD_QUERY_PAGE_SIZE",
    "RuleLoadAttemptView",
    "RuleLoadFreshness",
    "RuleLoadMemberView",
    "RuleLoadObservationItem",
    "RuleLoadObservationPage",
    "RuleLoadObservationQuery",
    "RuleLoadObservationTargets",
    "RuleLoadObservedState",
    "RuleLoadSnapshotView",
]
