"""Authenticated list and detail endpoints for rule publication attempts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_publication import ReadRulePublication
from ..application.read_rule_publications import ReadRulePublications
from ..application.read_rule_publication_target import ReadRulePublicationTarget
from ..application.read_session import ReadSession
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationNotFound,
    RulePublicationRateLimited,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from .http_support import error_response
from .rule_publication_serializers import (
    rule_publication_body,
    rule_publication_collection_body,
    rule_publication_target_body,
)
from .system_observation_access import authorize_system_read, system_read_headers


def rule_publication_routes(
    read_session: ReadSession,
    read_publications: ReadRulePublications | None,
    read_publication: ReadRulePublication | None,
    read_target: ReadRulePublicationTarget | None = None,
) -> tuple[Route, Route, Route]:
    """Create session-protected publication collection and detail endpoints."""

    async def read_collection(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        if read_publications is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            publications = await read_publications.execute(binding_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RulePublicationNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RulePublicationRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RulePublicationAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_publication_collection_body(publications),
            headers=system_read_headers(request_id_value),
        )

    async def read_one(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        publication_id = request.path_params["publicationId"]
        if not all(
            is_rule_binding_identifier(value) for value in (binding_id, publication_id)
        ):
            return error_response(request_id_value, "invalid_request", 400)
        if read_publication is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            publication = await read_publication.execute(binding_id, publication_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RulePublicationNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RulePublicationRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RulePublicationAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_publication_body(publication),
            headers=system_read_headers(request_id_value),
        )

    async def read_binding_target(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        if read_target is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            target = await read_target.execute(binding_id)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except (RulePublicationAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_publication_target_body(binding_id, target),
            headers=system_read_headers(request_id_value),
        )

    return (
        Route(
            "/api/v1/rulesets/{bindingId:str}/publications",
            read_collection,
            methods=["GET"],
        ),
        Route(
            "/api/v1/rulesets/{bindingId:str}/publications/{publicationId:str}",
            read_one,
            methods=["GET"],
        ),
        Route(
            "/api/v1/rulesets/{bindingId:str}/publication-target",
            read_binding_target,
            methods=["GET"],
        ),
    )
