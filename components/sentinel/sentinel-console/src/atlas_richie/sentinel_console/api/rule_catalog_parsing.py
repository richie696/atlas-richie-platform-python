"""Strict bounded query/body parsing for the rule catalog API."""

from __future__ import annotations

import re

from starlette.requests import Request

from ..domain.rule_bindings import RuleKind, is_rule_binding_identifier
from ..domain.rule_catalog import RuleCatalogQuery

_CANONICAL_INTEGER = re.compile(r"^[1-9][0-9]*$")
_QUERY_KEYS = frozenset(
    {"environmentId", "appId", "kind", "search", "page", "pageSize"}
)


def parse_rule_catalog_query(request: Request) -> RuleCatalogQuery:
    """Reject duplicate/unknown query keys and parse exact bounded filters."""
    values: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key not in _QUERY_KEYS or key in values:
            raise ValueError("rule catalog query keys are invalid")
        values[key] = value
    environment_id = values.get("environmentId", "")
    app_id = values.get("appId") or None
    if not is_rule_binding_identifier(environment_id) or (
        app_id is not None and not is_rule_binding_identifier(app_id)
    ):
        raise ValueError("rule catalog scope is invalid")
    kind_raw = values.get("kind")
    try:
        kind = RuleKind(kind_raw) if kind_raw else None
    except ValueError:
        raise ValueError("rule catalog kind is invalid") from None
    return RuleCatalogQuery(
        environment_id=environment_id,
        app_id=app_id,
        kind=kind,
        search=values.get("search", ""),
        page=_integer(values.get("page", "1")),
        page_size=_integer(values.get("pageSize", "20")),
    )


def parse_rule_catalog_refresh(value: object) -> tuple[str, str | None]:
    """Parse the only accepted refresh command fields and explicit scope."""
    if not isinstance(value, dict) or set(value) - {"environmentId", "appId"}:
        raise ValueError("rule catalog refresh body is invalid")
    environment_id = value.get("environmentId")
    app_id = value.get("appId")
    if not is_rule_binding_identifier(environment_id):
        raise ValueError("rule catalog refresh environment is invalid")
    if app_id is not None and not is_rule_binding_identifier(app_id):
        raise ValueError("rule catalog refresh application is invalid")
    return environment_id, app_id


def _integer(value: str) -> int:
    if not isinstance(value, str) or _CANONICAL_INTEGER.fullmatch(value) is None:
        raise ValueError("rule catalog page number is invalid")
    return int(value)


__all__ = ["parse_rule_catalog_query", "parse_rule_catalog_refresh"]
