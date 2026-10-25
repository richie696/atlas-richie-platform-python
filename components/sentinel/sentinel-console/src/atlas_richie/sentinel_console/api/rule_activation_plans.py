"""Authenticated read endpoint for persisted rule activation plans."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_activation_plans import ReadRuleActivationPlans
from ..application.read_session import ReadSession
from ..application.rule_activation_plan_ports import (
    RuleActivationPlanAuthorityUnavailable,
    RuleActivationPlanNotFound,
    RuleActivationPlanRateLimited,
)
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..domain.rule_bindings import is_rule_binding_identifier
from .http_support import error_response
from .rule_activation_plan_serializers import rule_activation_plan_collection_body
from .system_observation_access import authorize_system_read, system_read_headers


def rule_activation_plans_route(
    read_session: ReadSession,
    read_plans: ReadRuleActivationPlans | None,
) -> Route:
    """Create the browser-session-protected plan collection endpoint."""

    async def read_collection(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        if read_plans is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            collection = await read_plans.execute(binding_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleActivationPlanNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleActivationPlanRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleActivationPlanAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_activation_plan_collection_body(collection),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/plans",
        read_collection,
        methods=["GET"],
    )
