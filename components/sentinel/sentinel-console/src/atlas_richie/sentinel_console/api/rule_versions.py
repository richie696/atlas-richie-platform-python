"""Authenticated reads for immutable versions in one rule binding."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_version import ReadRuleVersion
from ..application.read_rule_versions import ReadRuleVersions
from ..application.read_session import ReadSession
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.rule_version_ports import (
    RuleSetVersionAuthorityUnavailable,
    RuleSetVersionNotFound,
    RuleSetVersionRateLimited,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from .http_support import error_response
from .rule_version_serializers import (
    rule_set_version_body,
    rule_version_collection_body,
)
from .system_observation_access import authorize_system_read, system_read_headers


def rule_versions_routes(
    read_session: ReadSession,
    read_versions: ReadRuleVersions | None,
    read_version: ReadRuleVersion | None,
) -> tuple[Route, Route]:
    """Create session-protected list and exact-detail version endpoints."""

    async def read_collection(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        if read_versions is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            collection = await read_versions.execute(binding_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleSetVersionNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleSetVersionRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleSetVersionAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_version_collection_body(collection),
            headers=system_read_headers(request_id_value),
        )

    async def read_one(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        version_id = request.path_params["versionId"]
        if not all(
            is_rule_binding_identifier(value) for value in (binding_id, version_id)
        ):
            return error_response(request_id_value, "invalid_request", 400)
        if read_version is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            version = await read_version.execute(binding_id, version_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleSetVersionNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleSetVersionRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleSetVersionAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_set_version_body(version),
            headers=system_read_headers(request_id_value),
        )

    return (
        Route(
            "/api/v1/rulesets/{bindingId:str}/versions",
            read_collection,
            methods=["GET"],
        ),
        Route(
            "/api/v1/rulesets/{bindingId:str}/versions/{versionId:str}",
            read_one,
            methods=["GET"],
        ),
    )
