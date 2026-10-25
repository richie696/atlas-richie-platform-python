"""Authenticated read-only API for historical process-epoch rule-load facts."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_load_observation_history import ReadRuleLoadObservationHistory
from ..application.read_session import ReadSession
from ..domain.rule_load_observation_history import RuleLoadObservationHistoryQuery
from .http_support import error_response
from .rule_load_observation_history_serializers import rule_load_history_page_body
from .system_observation_access import authorize_system_read, system_read_headers

_CANONICAL_INTEGER = re.compile(r"^[1-9][0-9]*$")
_QUERY_KEYS = frozenset(
    {"environmentId", "appId", "bindingId", "instanceId", "page", "pageSize"}
)


def rule_load_observation_history_route(
    read_session: ReadSession,
    reader: ReadRuleLoadObservationHistory | None,
) -> Route:
    """Build the separate historical read; current target counts are untouched."""

    async def read_page(request: Request) -> Response:
        request_id, _identity, rejection = await authorize_system_read(request, read_session)
        if rejection is not None:
            return rejection
        try:
            values: dict[str, str] = {}
            for key, value in request.query_params.multi_items():
                if key not in _QUERY_KEYS or key in values:
                    raise ValueError("invalid rule-load history query")
                values[key] = value
            if not {"environmentId", "appId", "bindingId"}.issubset(values):
                raise ValueError("historical query requires an exact binding")
            if "pageSize" in values and int(values["pageSize"]) > 100:
                raise ValueError("history page size exceeds bound")
            query = RuleLoadObservationHistoryQuery(
                environment_id=values["environmentId"],
                app_id=values["appId"],
                binding_id=values["bindingId"],
                instance_id=_optional_identifier(values.get("instanceId")),
                page=_integer(values.get("page", "1")),
                page_size=_integer(values.get("pageSize", "20")),
            )
        except (TypeError, ValueError):
            return error_response(request_id, "invalid_request", 400)
        if reader is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            body = rule_load_history_page_body(await reader.execute(query))
        except (RuntimeError, TypeError, ValueError):
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(body, headers=system_read_headers(request_id))

    return Route("/api/v2/rules/load-observation-history", read_page, methods=["GET"])


def _optional_identifier(value: str | None) -> str | None:
    if value == "":
        raise ValueError("blank optional identifier is invalid")
    return value


def _integer(value: str) -> int:
    if _CANONICAL_INTEGER.fullmatch(value) is None:
        raise ValueError("invalid canonical page number")
    return int(value)


__all__ = ["rule_load_observation_history_route"]
