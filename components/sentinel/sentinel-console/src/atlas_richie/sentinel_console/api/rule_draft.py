"""Administrator-only endpoint for one exact persisted rule draft."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_draft import ReadRuleDraft
from ..application.read_session import ReadSession
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.rule_draft_detail_ports import (
    RuleDraftDetailAuthorityUnavailable,
    RuleDraftDetailNotFound,
    RuleDraftDetailRateLimited,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.session import SessionCapability
from .http_support import error_response
from .rule_draft_serializers import stored_rule_draft_body
from .system_observation_access import authorize_system_read, system_read_headers


def rule_draft_route(
    read_session: ReadSession,
    read_draft: ReadRuleDraft | None,
) -> Route:
    """Create the session- and rules:write-protected draft detail endpoint."""

    async def read_one(request: Request) -> Response:
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
        draft_id = request.path_params["draftId"]
        if not all(
            is_rule_binding_identifier(value) for value in (binding_id, draft_id)
        ):
            return error_response(request_id_value, "invalid_request", 400)
        if read_draft is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            draft = await read_draft.execute(binding_id, draft_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleDraftDetailNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleDraftDetailRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleDraftDetailAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            stored_rule_draft_body(draft),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/drafts/{draftId:str}",
        read_one,
        methods=["GET"],
    )

