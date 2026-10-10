"""Authenticated read endpoint for the filtered rule binding directory."""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_bindings import ReadRuleBindings
from ..application.read_session import ReadSession
from ..application.rule_binding_ports import (
    RuleBindingAuthorityUnavailable,
    RuleBindingRateLimited,
    RuleBindingRegistrationAuthorityUnavailable,
    RuleBindingRegistrationConflict,
    RuleBindingRegistrationForbidden,
    RuleBindingRegistrationIdempotencyConflict,
    RuleBindingRegistrationUnauthenticated,
    RuleBindingRegistrationAuthority,
    RuleBindingTargetNotFound,
)
from ..application.register_rule_binding import RegisterRuleBindingUseCase
from .http_support import error_response, read_json_object
from .rule_binding_parsing import parse_rule_binding_query
from .rule_binding_registration_parsing import parse_rule_binding_registration
from .rule_binding_serializers import rule_binding_body, rule_binding_page_body
from .admin_write_access import authorize_admin_write
from .system_observation_access import authorize_system_read, system_read_headers

_MAX_BODY_BYTES = 8192


def rule_bindings_routes(
    read_session: ReadSession,
    read_bindings: ReadRuleBindings | None,
    registration_authority: RuleBindingRegistrationAuthority | None,
    allowed_browser_origins: frozenset[str],
) -> tuple[Route, Route]:
    """Create the read directory and admin-only atomic registration endpoints."""

    async def read_page(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        try:
            query = parse_rule_binding_query(request)
        except (ValueError, TypeError):
            return error_response(request_id_value, "invalid_request", 400)
        if read_bindings is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            page = await read_bindings.execute(query)
        except RuleBindingTargetNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleBindingRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleBindingAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_binding_page_body(page), headers=system_read_headers(request_id_value)
        )

    async def register(request: Request) -> Response:
        access, rejection = await authorize_admin_write(
            request, read_session, allowed_browser_origins
        )
        if rejection is not None:
            return rejection
        assert access is not None
        try:
            command = parse_rule_binding_registration(
                await read_json_object(request, _MAX_BODY_BYTES)
            )
        except (TypeError, ValueError):
            return error_response(access.request_id, "validation_failed", 422)
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or keys[0] != command.request_key:
            return error_response(access.request_id, "idempotency_conflict", 409)
        if registration_authority is None:
            return error_response(access.request_id, "service_unavailable", 503)
        now = datetime.now(UTC)
        try:
            binding = await RegisterRuleBindingUseCase(
                registration_authority
            ).execute(
                command,
                actor_id=access.identity.account_id,
                session_digest=access.session_digest,
                csrf_digest=access.csrf_digest,
                request_id=access.request_id,
                now=now.replace(microsecond=(now.microsecond // 1_000) * 1_000),
            )
        except RuleBindingRegistrationUnauthenticated:
            return error_response(access.request_id, "unauthenticated", 401)
        except RuleBindingRegistrationForbidden:
            return error_response(access.request_id, "forbidden", 403)
        except RuleBindingRegistrationIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except RuleBindingRegistrationConflict:
            return error_response(access.request_id, "conflict", 409)
        except (RuleBindingRegistrationAuthorityUnavailable, ValueError):
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            body = rule_binding_body(binding)
        except (TypeError, ValueError):
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            body,
            status_code=201,
            headers={
                "x-request-id": access.request_id,
                "cache-control": "no-store",
                "vary": "Cookie",
            },
        )

    return (
        Route("/api/v1/rulesets", read_page, methods=["GET"]),
        Route("/api/v1/rulesets", register, methods=["POST"]),
    )

