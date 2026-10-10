"""Validated environment and application facts for observation filters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .wire_strings import (
    has_non_blank_wire_content,
    is_bounded_wire_identifier,
    is_bounded_wire_text,
)

_MAX_CATALOG_ITEMS = 1_000
_MAX_TEXT_LENGTH = 200
_MIN_SUPPORTED_UTC_YEAR = 1970


def _is_aware_instant(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
    )


def _is_identifier(value: str) -> bool:
    return is_bounded_wire_identifier(value, _MAX_TEXT_LENGTH)


def _is_name(value: str) -> bool:
    return isinstance(value, str) and bool(value) and is_bounded_wire_text(
        value, _MAX_TEXT_LENGTH
    ) and has_non_blank_wire_content(value)


@dataclass(frozen=True, slots=True)
class ObservationEnvironment:
    """One environment that may scope an observation query."""

    id: str
    name: str

    def __post_init__(self) -> None:
        if not _is_identifier(self.id) or not _is_name(self.name):
            raise ValueError("observation environment identity is invalid")


@dataclass(frozen=True, slots=True)
class ObservationApplication:
    """One application and its owning environment identifier."""

    id: str
    environment_id: str
    name: str

    def __post_init__(self) -> None:
        if (
            not _is_identifier(self.id)
            or not _is_identifier(self.environment_id)
            or not _is_name(self.name)
        ):
            raise ValueError("observation application identity is invalid")


@dataclass(frozen=True, slots=True)
class ObservationCatalogSnapshot:
    """A bounded, authoritative catalog snapshot for dashboard selectors."""

    as_of: datetime
    environments: tuple[ObservationEnvironment, ...]
    applications: tuple[ObservationApplication, ...]

    def __post_init__(self) -> None:
        if not _is_aware_instant(self.as_of):
            raise ValueError("observation catalog time must be timezone-aware")
        if (
            not isinstance(self.environments, tuple)
            or len(self.environments) > _MAX_CATALOG_ITEMS
            or any(
                not isinstance(item, ObservationEnvironment)
                for item in self.environments
            )
        ):
            raise ValueError("observation environments must be a bounded tuple")
        if (
            not isinstance(self.applications, tuple)
            or len(self.applications) > _MAX_CATALOG_ITEMS
            or any(
                not isinstance(item, ObservationApplication)
                for item in self.applications
            )
        ):
            raise ValueError("observation applications must be a bounded tuple")
        environment_ids = {item.id for item in self.environments}
        if len(environment_ids) != len(self.environments):
            raise ValueError("observation environment identities must be unique")
        application_identities = {
            (item.environment_id, item.id) for item in self.applications
        }
        if len(application_identities) != len(self.applications):
            raise ValueError("scoped observation application identities must be unique")
        if any(
            item.environment_id not in environment_ids for item in self.applications
        ):
            raise ValueError("observation application references an unknown environment")
