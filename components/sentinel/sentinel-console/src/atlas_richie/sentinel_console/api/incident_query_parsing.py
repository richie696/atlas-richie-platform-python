"""Strict shared query parsing for incident timeline and evidence reads."""

from __future__ import annotations

from starlette.requests import Request

from ..domain.incidents import (
    MAX_INCIDENT_PAGE_SIZE,
    IncidentCategory,
    IncidentDetailQuery,
    IncidentQuery,
    IncidentSeverity,
)
from ..domain.instance_catalog import ObservationScope, ObservationWindow
from ..domain.instance_observation import ObservationContext
from .query_parsing import parse_utc_timestamp

_TIMELINE_REQUIRED = frozenset(
    {"environmentId", "scope", "from", "to", "pageSize"}
)
_TIMELINE_OPTIONAL = frozenset(
    {"appId", "instanceId", "severity", "category", "cursor"}
)
_EVIDENCE_REQUIRED = frozenset({"environmentId", "scope", "from", "to"})
_EVIDENCE_OPTIONAL = frozenset(
    {"appId", "instanceId", "severity", "category"}
)


def parse_incident_timeline_query(request: Request) -> IncidentQuery:
    """Parse bounded timeline query parameters, rejecting unknown/repeated keys."""
    supplied = _query_values(request, _TIMELINE_REQUIRED, _TIMELINE_OPTIONAL)
    cursor = supplied.get("cursor")
    return IncidentQuery(
        context=_context(supplied),
        severity=_severity(supplied),
        category=_category(supplied),
        cursor=cursor,
        page_size=_page_size(supplied["pageSize"]),
    )


def parse_incident_detail_query(
    request: Request, event_id: str
) -> IncidentDetailQuery:
    """Parse the selected event's exact observation identity and filters."""
    supplied = _query_values(request, _EVIDENCE_REQUIRED, _EVIDENCE_OPTIONAL)
    return IncidentDetailQuery(
        context=_context(supplied),
        event_id=event_id,
        severity=_severity(supplied),
        category=_category(supplied),
    )


def _query_values(
    request: Request,
    required: frozenset[str],
    optional: frozenset[str],
) -> dict[str, str]:
    supplied: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name not in required | optional or name in supplied:
            raise ValueError("incident query parameters must be known and unique")
        supplied[name] = value
    if not required.issubset(supplied):
        raise ValueError("required incident query field is missing")
    return supplied


def _context(supplied: dict[str, str]) -> ObservationContext:
    return ObservationContext(
        environment_id=supplied["environmentId"],
        app_id=supplied.get("appId"),
        instance_id=supplied.get("instanceId"),
        resource=supplied.get("resource"),
        scope=ObservationScope(supplied["scope"]),
        window=ObservationWindow(
            parse_utc_timestamp(supplied["from"]),
            parse_utc_timestamp(supplied["to"]),
        ),
    )


def _severity(supplied: dict[str, str]) -> IncidentSeverity | None:
    return IncidentSeverity(supplied["severity"]) if "severity" in supplied else None


def _category(supplied: dict[str, str]) -> IncidentCategory | None:
    return IncidentCategory(supplied["category"]) if "category" in supplied else None


def _page_size(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("incident page size must be an unsigned decimal integer")
    parsed = int(value)
    if not 1 <= parsed <= MAX_INCIDENT_PAGE_SIZE:
        raise ValueError("incident page size is out of range")
    return parsed
