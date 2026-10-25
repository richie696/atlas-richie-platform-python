"""Authenticated read endpoint for rule-owned selector scopes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_binding_scopes import ReadRuleBindingScopes
from ..application.read_session import ReadSession
from ..application.rule_binding_ports import RuleBindingScopeAuthorityUnavailable
from ..domain.rule_bindings import RuleBindingScopeCatalog
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)


def rule_binding_scopes_route(
    read_session: ReadSession,
    read_scopes: ReadRuleBindingScopes | None,
) -> Route:
    """Create a session-protected, metrics-independent rule scope route."""

    async def read_snapshot(request: Request) -> Response:
        request_id, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        if read_scopes is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            snapshot = await read_scopes.execute()
            body = _snapshot_body(snapshot)
        except (RuleBindingScopeAuthorityUnavailable, TypeError, ValueError):
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(body, headers=system_read_headers(request_id))

    return Route("/api/v2/rules/binding-scopes", read_snapshot, methods=["GET"])


def _snapshot_body(snapshot: RuleBindingScopeCatalog) -> dict[str, object]:
    return {
        "asOf": utc_timestamp(snapshot.as_of),
        "environments": [
            {"id": item.id, "name": item.name} for item in snapshot.environments
        ],
        "applications": [
            {
                "id": item.id,
                "environmentId": item.environment_id,
                "name": item.name,
            }
            for item in snapshot.applications
        ],
    }
