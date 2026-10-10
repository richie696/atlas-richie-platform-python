"""Strict, bounded query parsing for the rule binding directory endpoint."""

from __future__ import annotations

from starlette.requests import Request

from ..domain.rule_bindings import RuleBindingQuery, RuleKind

_REQUIRED = frozenset({"environmentId", "page", "pageSize"})
_OPTIONAL = frozenset({"appId", "kind", "search"})


def parse_rule_binding_query(request: Request) -> RuleBindingQuery:
    """Reject unknown/repeated parameters and parse bounded exact filters."""
    supplied: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name not in _REQUIRED | _OPTIONAL or name in supplied:
            raise ValueError("rule binding query parameters must be known and unique")
        supplied[name] = value
    if not _REQUIRED.issubset(supplied):
        raise ValueError("required rule binding query field is missing")
    app_id = supplied.get("appId")
    kind_value = supplied.get("kind")
    return RuleBindingQuery(
        environment_id=supplied["environmentId"],
        app_id=app_id,
        kind=RuleKind(kind_value) if kind_value is not None else None,
        search=supplied.get("search", ""),
        page=_positive_integer(supplied["page"], 1_000_000),
        page_size=_positive_integer(supplied["pageSize"], 100),
    )


def _positive_integer(value: str, maximum: int) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("rule binding page values must be unsigned decimal integers")
    parsed = int(value)
    if not 1 <= parsed <= maximum:
        raise ValueError("rule binding page value is out of range")
    return parsed

