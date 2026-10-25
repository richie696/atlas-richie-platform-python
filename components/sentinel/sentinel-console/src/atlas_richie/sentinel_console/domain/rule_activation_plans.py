"""Immutable schedule facts for binding-scoped rule activation plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .rule_bindings import is_rule_binding_identifier
from .utc_time import is_wire_utc_millisecond_instant
from .wire_strings import has_non_blank_wire_content, is_bounded_wire_text

_MAX_PLANS_PER_BINDING = 1_000
_MAX_TIME_ZONE_UNITS = 128


class RuleActivationPlanState(StrEnum):
    """Finite scheduler lifecycle states declared by the Console protocol."""

    PENDING = "pending"
    ACTIVATING = "activating"
    ACTIVE = "active"
    RESTORING = "restoring"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RuleActivationPlanPhase(StrEnum):
    """Stable identity of one of the two durable plan publications."""

    ACTIVATION = "activation"
    RESTORATION = "restoration"


@dataclass(frozen=True, slots=True)
class RuleActivationPlan:
    """One persisted schedule with explicit activation and restoration targets."""

    id: str
    revision: str
    binding_id: str
    version_id: str
    restore_version_id: str
    activate_at: datetime
    deactivate_at: datetime
    time_zone: str
    state: RuleActivationPlanState
    activation_publication_id: str | None
    restore_publication_id: str | None

    def __post_init__(self) -> None:
        identities = (
            self.id,
            self.revision,
            self.binding_id,
            self.version_id,
            self.restore_version_id,
        )
        if any(not is_rule_binding_identifier(value) for value in identities):
            raise ValueError("rule activation plan identity is invalid")
        if self.version_id == self.restore_version_id:
            raise ValueError("rule activation and restore versions must differ")
        if not all(
            is_wire_utc_millisecond_instant(value)
            for value in (self.activate_at, self.deactivate_at)
        ) or self.deactivate_at <= self.activate_at:
            raise ValueError("rule activation plan window is invalid")
        if not isinstance(self.state, RuleActivationPlanState):
            raise ValueError("rule activation plan state is unsupported")
        if (
            not is_bounded_wire_text(self.time_zone, _MAX_TIME_ZONE_UNITS)
            or not has_non_blank_wire_content(self.time_zone)
        ):
            raise ValueError("rule activation plan time zone is invalid")
        try:
            ZoneInfo(self.time_zone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("rule activation plan time zone is unsupported") from error
        for publication_id in (
            self.activation_publication_id,
            self.restore_publication_id,
        ):
            if publication_id is not None and not is_rule_binding_identifier(
                publication_id
            ):
                raise ValueError("rule activation publication identity is invalid")


@dataclass(frozen=True, slots=True)
class RuleActivationPlanCollection:
    """Complete bounded plan snapshot for one rule binding."""

    binding_id: str
    as_of: datetime
    items: tuple[RuleActivationPlan, ...]

    def __post_init__(self) -> None:
        if not is_rule_binding_identifier(self.binding_id):
            raise ValueError("rule activation plan collection binding is invalid")
        if not is_wire_utc_millisecond_instant(self.as_of):
            raise ValueError("rule activation plan collection time is invalid")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > _MAX_PLANS_PER_BINDING
            or any(not isinstance(item, RuleActivationPlan) for item in self.items)
        ):
            raise ValueError("rule activation plan collection exceeds its limit")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("rule activation plan identities must be unique")
        if any(item.binding_id != self.binding_id for item in self.items):
            raise ValueError("rule activation plan belongs to another binding")
