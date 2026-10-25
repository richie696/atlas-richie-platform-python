"""Authenticated endpoint for one complete rule-set snapshot."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.read_rule_set_snapshot import ReadRuleSetSnapshot
from ..domain.rule_bindings import is_rule_binding_identifier
from ..application.read_session import ReadSession
from ..application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotRateLimited,
)
from .http_support import error_response
from .rule_snapshot_serializers import rule_set_snapshot_body
from .system_observation_access import authorize_system_read, system_read_headers


def rule_set_snapshot_route(
    read_session: ReadSession,
    read_snapshot: ReadRuleSetSnapshot | None,
) -> Route:
    """Create the session-protected, exact-binding snapshot endpoint."""

    async def read_one(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        if read_snapshot is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_snapshot.execute(binding_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleSetSnapshotNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleSetSnapshotRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleSetSnapshotAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_set_snapshot_body(snapshot),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/snapshot",
        read_one,
        methods=["GET"],
    )
