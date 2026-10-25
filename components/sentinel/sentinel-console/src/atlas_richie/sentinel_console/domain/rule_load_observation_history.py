"""Bounded read model for historical process-epoch rule-load observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .rule_bindings import is_rule_binding_identifier
from .rule_catalog import RuleCatalogCoverage
from .rule_load_observation_query import RuleLoadObservationItem


class HistoricalProcessEpochStatus(StrEnum):
    """Why an observation's process epoch is not the currently active epoch."""

    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    NO_CURRENT_EPOCH = "no_current_epoch"


@dataclass(frozen=True, slots=True)
class RuleLoadObservationHistoryQuery:
    """Exact binding history query with bounded, stable pagination."""

    environment_id: str
    app_id: str
    binding_id: str
    instance_id: str | None
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if (
            not is_rule_binding_identifier(self.environment_id)
            or not is_rule_binding_identifier(self.app_id)
            or not is_rule_binding_identifier(self.binding_id)
            or (self.instance_id is not None and not is_rule_binding_identifier(self.instance_id))
            or type(self.page) is not int
            or not 1 <= self.page <= 1_000_000
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= 100
        ):
            raise ValueError("rule-load history query is outside its bounds")


@dataclass(frozen=True, slots=True)
class RuleLoadObservationHistoryItem:
    """One immutable observation from a non-current process epoch."""

    observation_id: str
    epoch_status: HistoricalProcessEpochStatus
    observation: RuleLoadObservationItem

    def __post_init__(self) -> None:
        if (
            not is_rule_binding_identifier(self.observation_id)
            or not isinstance(self.epoch_status, HistoricalProcessEpochStatus)
            or not isinstance(self.observation, RuleLoadObservationItem)
            or self.observation.process_epoch is None
            or self.observation.event_kind is None
        ):
            raise ValueError("historical rule-load item is inconsistent")


@dataclass(frozen=True, slots=True)
class RuleLoadObservationHistoryPage:
    """Stable, bounded historical facts for one exact rule binding."""

    query: RuleLoadObservationHistoryQuery
    as_of: datetime
    coverage: RuleCatalogCoverage
    total: int | None
    has_more: bool
    items: tuple[RuleLoadObservationHistoryItem, ...]

    def __post_init__(self) -> None:
        identities = tuple(
            (item.observation.received_at, item.observation_id) for item in self.items
        )
        if (
            not isinstance(self.query, RuleLoadObservationHistoryQuery)
            or not _aware(self.as_of)
            or not isinstance(self.coverage, RuleCatalogCoverage)
            or (self.total is not None and (type(self.total) is not int or self.total < 0))
            or ((self.coverage is RuleCatalogCoverage.COMPLETE) != (self.total is not None))
            or type(self.has_more) is not bool
            or not isinstance(self.items, tuple)
            or len(self.items) > self.query.page_size
            or any(not isinstance(item, RuleLoadObservationHistoryItem) for item in self.items)
            or any(item.observation.binding_id != self.query.binding_id for item in self.items)
            or any(item.observation.instance_id != self.query.instance_id for item in self.items if self.query.instance_id)
            or len(set(identities)) != len(identities)
            or any(identities[index] < identities[index + 1] for index in range(len(identities) - 1))
            or (
                self.total is not None
                and self.has_more
                != ((self.query.page - 1) * self.query.page_size + len(self.items) < self.total)
            )
        ):
            raise ValueError("rule-load history page is inconsistent")


__all__ = [
    "HistoricalProcessEpochStatus",
    "RuleLoadObservationHistoryItem",
    "RuleLoadObservationHistoryPage",
    "RuleLoadObservationHistoryQuery",
]


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
