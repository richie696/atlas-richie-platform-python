"""Strict, bounded query parsing for the rule binding directory endpoint."""

from __future__ import annotations

from starlette.requests import Request

from ..domain.rule_bindings import RuleBindingQuery, RuleKind
from .query_parsing import (
    MAX_QUERY_PAGE_NUMBER,
    MAX_QUERY_PAGE_SIZE,
    MIN_QUERY_INTEGER,
    parse_integer,
    parse_query_values,
)

_REQUIRED = frozenset({"environmentId", "page", "pageSize"})
_OPTIONAL = frozenset({"appId", "kind", "search"})


def parse_rule_binding_query(request: Request) -> RuleBindingQuery:
    """Reject unknown/repeated parameters and parse bounded exact filters."""
    supplied = parse_query_values(request, _REQUIRED, _OPTIONAL)
    app_id = supplied.get("appId")
    kind_value = supplied.get("kind")
    return RuleBindingQuery(
        environment_id=supplied["environmentId"],
        app_id=app_id,
        kind=RuleKind(kind_value) if kind_value is not None else None,
        search=supplied.get("search", ""),
        page=parse_integer(supplied["page"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER),
        page_size=parse_integer(
            supplied["pageSize"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE
        ),
    )
