"""Authenticated read-only API 0.9 route for registered rule binding states."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_binding_states import ReadRuleBindingStates
from ..application.read_session import ReadSession
from ..domain.rule_bindings import RuleKind
from ..domain.rule_catalog import RuleBindingStatesQuery
from .http_support import error_response
from .rule_binding_state_serializers import rule_binding_states_page_body
from .system_observation_access import authorize_system_read, system_read_headers

_CANONICAL_INTEGER = re.compile(r"^[1-9][0-9]*$")
_QUERY_KEYS = frozenset({"environmentId", "appId", "kind", "page", "pageSize"})


def rule_binding_states_route(
    read_session: ReadSession,
    reader: ReadRuleBindingStates | None,
) -> Route:
    """Create the session-protected provider-state query operation."""

    async def read_states(request: Request) -> Response:
        request_id, _identity, rejection = await authorize_system_read(request, read_session)
        if rejection is not None:
            return rejection
        try:
            values: dict[str, str] = {}
            for key, value in request.query_params.multi_items():
                if key not in _QUERY_KEYS or key in values:
                    raise ValueError("invalid binding state query")
                values[key] = value
            environment_id = values.get("environmentId", "")
            app_id = values.get("appId")
            if app_id == "":
                raise ValueError("blank application is invalid")
            kind_raw = values.get("kind")
            kind = RuleKind(kind_raw) if kind_raw else None
            query = RuleBindingStatesQuery(
                environment_id=environment_id,
                app_id=app_id,
                kind=kind,
                page=_integer(values.get("page", "1")),
                page_size=_integer(values.get("pageSize", "20")),
            )
        except (TypeError, ValueError):
            return error_response(request_id, "invalid_request", 400)
        if reader is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            body = rule_binding_states_page_body(await reader.execute(query))
        except (RuntimeError, TypeError, ValueError):
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(body, headers=system_read_headers(request_id))

    return Route("/api/v2/rules/catalog/binding-states", read_states, methods=["GET"])


def _integer(value: str) -> int:
    if _CANONICAL_INTEGER.fullmatch(value) is None:
        raise ValueError("invalid canonical page number")
    return int(value)


__all__ = ["rule_binding_states_route"]
