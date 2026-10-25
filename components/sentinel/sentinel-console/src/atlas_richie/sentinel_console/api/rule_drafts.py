"""Administrator-only endpoint for a binding's persisted rule drafts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_drafts import ReadRuleDrafts
from ..application.read_session import ReadSession
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.rule_draft_ports import (
    RuleDraftAuthorityUnavailable,
    RuleDraftNotFound,
    RuleDraftRateLimited,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.session import SessionCapability
from .http_support import error_response
from .rule_draft_serializers import rule_draft_collection_body
from .system_observation_access import authorize_system_read, system_read_headers


def rule_drafts_route(
    read_session: ReadSession,
    read_drafts: ReadRuleDrafts | None,
) -> Route:
    """Create the session- and rules:write-protected drafts endpoint."""

    async def read_collection(request: Request) -> Response:
        request_id_value, identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        if (
            identity is None
            or SessionCapability.RULES_WRITE not in identity.capabilities
        ):
            return error_response(request_id_value, "forbidden", 403)
        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        if read_drafts is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            collection = await read_drafts.execute(binding_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleDraftNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleDraftRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleDraftAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_draft_collection_body(collection),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/drafts",
        read_collection,
        methods=["GET"],
    )
