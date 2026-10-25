"""Admin-protected idempotent rule commands and original-operation lookup."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.errors import SessionAuthorityUnavailable
from ..application.mutate_rule_set import (
    RuleMutationAuthority,
    RuleMutationAuthorityUnavailable,
    RuleMutationForbidden,
    RuleMutationIdempotencyConflict,
    RuleMutationRateLimited,
    RuleMutationUnauthenticated,
    RuleOperationStatus,
)
from ..application.read_session import ReadSession
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.session import AccountRole
from .admin_write_access import authorize_admin_write
from .browser_security import SESSION_COOKIE_NAME, browser_session_digest
from .http_support import error_response, read_json_object
from .rule_mutation_parsing import InvalidRuleMutation, parse_rule_mutation
from .rule_mutation_serializers import rule_mutation_operation_body
from .system_observation_access import authorize_system_read, system_read_headers

_MAX_BODY_BYTES = 1_048_576
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def rule_mutation_routes(
    read_session: ReadSession,
    authority: RuleMutationAuthority | None,
    allowed_browser_origins: Collection[str],
) -> tuple[Route, Route]:
    """Create the mutation and exact original-operation routes for a ruleset."""

    async def mutate(request: Request) -> Response:
        access, rejection = await authorize_admin_write(
            request, read_session, allowed_browser_origins
        )
        if rejection is not None:
            return rejection
        assert access is not None
        binding_id = request.path_params.get("bindingId", "")
        try:
            command = parse_rule_mutation(
                binding_id, await read_json_object(request, _MAX_BODY_BYTES)
            )
        except (InvalidRuleMutation, TypeError, ValueError):
            return error_response(access.request_id, "validation_failed", 422)
        idempotency_keys = request.headers.getlist("idempotency-key")
        if (
            len(idempotency_keys) != 1
            or idempotency_keys[0] != command.request_key
            or _REQUEST_KEY.fullmatch(idempotency_keys[0]) is None
        ):
            return error_response(access.request_id, "idempotency_conflict", 409)
        if authority is None:
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            operation = await authority.mutate(
                command,
                actor_id=access.identity.account_id,
                session_digest=access.session_digest,
                csrf_digest=access.csrf_digest,
                request_id=access.request_id,
                now=datetime.now(UTC),
            )
        except RuleMutationForbidden:
            return error_response(access.request_id, "forbidden", 403)
        except RuleMutationUnauthenticated:
            return error_response(access.request_id, "unauthenticated", 401)
        except RuleMutationIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except RuleMutationRateLimited as error:
            return error_response(
                access.request_id,
                "rate_limited",
                429,
                retry_after_ms=error.retry_after_ms,
            )
        except RuleMutationAuthorityUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        if (
            operation.binding_id != binding_id
            or operation.request_key != command.request_key
        ):
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            body = rule_mutation_operation_body(operation)
        except (TypeError, ValueError):
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            body,
            status_code=202,
            headers={
                "x-request-id": access.request_id,
                "cache-control": "no-store",
                "vary": "Cookie",
            },
        )

    async def read_operation(request: Request) -> Response:
        request_id, identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id, "forbidden", 403)
        binding_id = request.path_params.get("bindingId", "")
        request_key = request.path_params.get("requestKey", "")
        if (
            not is_rule_binding_identifier(binding_id)
            or _REQUEST_KEY.fullmatch(request_key) is None
        ):
            return error_response(request_id, "not_found", 404)
        session_digest, failure = browser_session_digest(request)
        if failure is not None:
            return error_response(request_id, failure[0], failure[1])
        assert session_digest is not None
        if authority is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            operation = await authority.read_operation(
                binding_id,
                request_key,
                actor_id=identity.account_id,
                session_digest=session_digest,
            )
        except RuleMutationForbidden:
            return error_response(request_id, "forbidden", 403)
        except RuleMutationUnauthenticated:
            return error_response(request_id, "unauthenticated", 401)
        except RuleMutationRateLimited as error:
            return error_response(
                request_id,
                "rate_limited",
                429,
                retry_after_ms=error.retry_after_ms,
            )
        except RuleMutationAuthorityUnavailable:
            return error_response(request_id, "service_unavailable", 503)
        if operation is None:
            body = {
                "requestKey": request_key,
                "bindingId": binding_id,
                "status": RuleOperationStatus.NOT_FOUND.value,
            }
        elif operation.binding_id != binding_id or operation.request_key != request_key:
            return error_response(request_id, "service_unavailable", 503)
        else:
            try:
                body = rule_mutation_operation_body(operation)
            except (TypeError, ValueError):
                return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(body, headers=system_read_headers(request_id))

    return (
        Route(
            "/api/v1/rulesets/{bindingId:str}/commands",
            mutate,
            methods=["POST"],
        ),
        Route(
            "/api/v1/rulesets/{bindingId:str}/operations/{requestKey:str}",
            read_operation,
            methods=["GET"],
        ),
    )
