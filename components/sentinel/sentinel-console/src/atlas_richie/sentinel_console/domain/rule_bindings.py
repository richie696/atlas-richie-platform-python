"""Validated rule-source binding directory facts for the Sentinel Console."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .wire_numbers import MAX_SAFE_JSON_INTEGER
from .wire_strings import (
    has_non_blank_wire_content,
    is_bounded_wire_identifier,
    is_bounded_wire_text,
)

_MAX_IDENTIFIER_UNITS = 200
_MAX_TEXT_UNITS = 200
_MAX_LOCATION_UNITS = 512
_MAX_SEARCH_UNITS = 200
_MAX_PAGE = 1_000_000
_MAX_PAGE_SIZE = 100
MAX_RULE_BINDING_SCOPE_ITEMS = 1_000
MAX_RULE_BINDING_SCOPE_ROWS = 10_000
_SENSITIVE_QUERY_NAME = re.compile(
    r"(?:^|[&;?])(?:access[_-]?token|api[_-]?key|credential|password|secret|token)\s*=",
    re.IGNORECASE,
)
_URI_USER_INFO = re.compile(r"^[a-z][a-z0-9+.-]*://[^/\s@]+@", re.IGNORECASE)


class RuleKind(StrEnum):
    """Supported Sentinel rule families exposed by the current UI contract."""

    FLOW = "flow"
    DEGRADE = "degrade"
    SYSTEM = "system"
    AUTHORITY = "authority"
    PARAM = "param"


def _valid_identifier(value: str) -> bool:
    return is_bounded_wire_identifier(value, _MAX_IDENTIFIER_UNITS)


def is_rule_binding_identifier(value: str) -> bool:
    """Validate a binding path identity using the public wire limit."""
    return _valid_identifier(value)


def _valid_text(value: str, maximum: int) -> bool:
    return is_bounded_wire_text(value, maximum)


def _valid_location(value: str) -> bool:
    return (
        _valid_text(value, _MAX_LOCATION_UNITS)
        and has_non_blank_wire_content(value)
        and _URI_USER_INFO.match(value) is None
        and _SENSITIVE_QUERY_NAME.search(value) is None
    )


@dataclass(frozen=True, slots=True)
class RuleBinding:
    """One application rule binding and its redacted configuration location."""

    id: str
    environment_id: str
    app_id: str
    kind: RuleKind
    profile: str
    source_id: str
    source_label: str
    location: str

    def __post_init__(self) -> None:
        identifiers = (
            self.id,
            self.environment_id,
            self.app_id,
            self.profile,
            self.source_id,
        )
        if any(not _valid_identifier(value) for value in identifiers):
            raise ValueError("rule binding identifier is invalid")
        if not isinstance(self.kind, RuleKind):
            raise ValueError("rule binding kind is unsupported")
        if not _valid_identifier(self.source_label):
            raise ValueError("rule binding source label is invalid")
        if not _valid_location(self.location):
            raise ValueError("rule binding location is invalid or not redacted")


@dataclass(frozen=True, slots=True)
class RuleBindingQuery:
    """Exact directory filter and pagination requested by a browser session."""

    environment_id: str
    app_id: str | None
    kind: RuleKind | None
    search: str
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if not _valid_identifier(self.environment_id):
            raise ValueError("rule binding environment is invalid")
        if self.app_id is not None and not _valid_identifier(self.app_id):
            raise ValueError("rule binding application is invalid")
        if self.kind is not None and not isinstance(self.kind, RuleKind):
            raise ValueError("rule binding kind filter is unsupported")
        if not _valid_text(self.search, _MAX_SEARCH_UNITS):
            raise ValueError("rule binding search is too long")
        if type(self.page) is not int or not 1 <= self.page <= _MAX_PAGE:
            raise ValueError("rule binding page is out of range")
        if type(self.page_size) is not int or not 1 <= self.page_size <= _MAX_PAGE_SIZE:
            raise ValueError("rule binding page size is out of range")


@dataclass(frozen=True, slots=True)
class RuleBindingPage:
    """One filtered total and an explicitly bounded page of binding facts."""

    query: RuleBindingQuery
    total: int
    items: tuple[RuleBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, RuleBindingQuery):
            raise ValueError("rule binding response query is invalid")
        if type(self.total) is not int or not 0 <= self.total <= MAX_SAFE_JSON_INTEGER:
            raise ValueError("rule binding total is not a safe non-negative count")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > self.query.page_size
            or len(self.items)
            > max(0, self.total - (self.query.page - 1) * self.query.page_size)
            or any(not isinstance(item, RuleBinding) for item in self.items)
        ):
            raise ValueError("rule binding items exceed the filtered page")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("rule binding page contains duplicate identities")
        if any(
            item.environment_id != self.query.environment_id
            or (self.query.app_id is not None and item.app_id != self.query.app_id)
            or (self.query.kind is not None and item.kind is not self.query.kind)
            for item in self.items
        ):
            raise ValueError("rule binding page does not match its exact filters")


@dataclass(frozen=True, slots=True)
class RuleBindingScopeEnvironment:
    """One environment identity persisted by at least one valid rule binding."""

    id: str
    name: str

    def __post_init__(self) -> None:
        if not _valid_identifier(self.id) or not _valid_text(
            self.name, _MAX_TEXT_UNITS
        ):
            raise ValueError("rule binding environment scope is invalid")
        if not has_non_blank_wire_content(self.name):
            raise ValueError("rule binding environment name is blank")


@dataclass(frozen=True, slots=True)
class RuleBindingScopeApplication:
    """One application identity and the environment that owns its bindings."""

    id: str
    environment_id: str
    name: str

    def __post_init__(self) -> None:
        if (
            not _valid_identifier(self.id)
            or not _valid_identifier(self.environment_id)
            or not _valid_text(self.name, _MAX_TEXT_UNITS)
            or not has_non_blank_wire_content(self.name)
        ):
            raise ValueError("rule binding application scope is invalid")


@dataclass(frozen=True, slots=True)
class RuleBindingScopeCatalog:
    """A bounded snapshot of scopes proven by the rule-binding authority."""

    as_of: datetime
    environments: tuple[RuleBindingScopeEnvironment, ...]
    applications: tuple[RuleBindingScopeApplication, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.as_of, datetime)
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
            or not 1970 <= self.as_of.year <= 9999
        ):
            raise ValueError("rule binding scope time must be timezone-aware")
        if (
            not isinstance(self.environments, tuple)
            or len(self.environments) > MAX_RULE_BINDING_SCOPE_ITEMS
            or any(
                not isinstance(item, RuleBindingScopeEnvironment)
                for item in self.environments
            )
        ):
            raise ValueError("rule binding environments exceed their bound")
        if (
            not isinstance(self.applications, tuple)
            or len(self.applications) > MAX_RULE_BINDING_SCOPE_ITEMS
            or any(
                not isinstance(item, RuleBindingScopeApplication)
                for item in self.applications
            )
        ):
            raise ValueError("rule binding applications exceed their bound")
        if len({item.id for item in self.environments}) != len(self.environments):
            raise ValueError("rule binding environment scopes must be unique")
        application_keys = {
            (item.environment_id, item.id) for item in self.applications
        }
        if len(application_keys) != len(self.applications):
            raise ValueError("rule binding application scopes must be unique")
        environment_ids = {item.id for item in self.environments}
        if any(
            item.environment_id not in environment_ids for item in self.applications
        ):
            raise ValueError(
                "rule binding application scope references an unknown environment"
            )
