"""Idempotent admin source-mutation and original-operation HTTP adapters."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.errors import SessionAuthorityUnavailable
from ..application.check_registered_source import SourceConnectionInput
from ..application.mutate_registered_source import (
    RegisteredSourceMutation,
    RegisteredSourceMutationAuthority,
    SourceMutationAuthorityUnavailable,
    SourceMutationForbidden,
    SourceMutationIdempotencyConflict,
    SourceMutationKind,
    SourceMutationRateLimited,
    SourceMutationRejection,
    SourceMutationStatus,
    SourceMutationUnauthenticated,
)
from ..application.read_session import ReadSession
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.registered_sources import RegisteredConfigurationSource
from ..domain.session import AccountRole
from ..domain.wire_strings import is_bounded_wire_identifier
from .admin_write_access import authorize_admin_write
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_session_digest
from .http_support import error_response, read_json_object, strict_request_id
from .source_connection_parsing import parse_source_connection
from .system_observation_access import system_read_headers

_MAX_BODY_BYTES = 8192
_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def registered_source_command_routes(
    read_session: ReadSession,
    authority: RegisteredSourceMutationAuthority | None,
    allowed_browser_origins: Collection[str],
) -> tuple[Route, Route]:
    """Create source mutation and operation routes with shared admin policy."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def mutate(request: Request) -> Response:
        access, rejection = await authorize_admin_write(
            request, read_session, allowed_origins
        )
        if rejection is not None:
            return rejection
        assert access is not None
        command = _parse_mutation(await read_json_object(request, _MAX_BODY_BYTES))
        keys = request.headers.getlist("idempotency-key")
        if command is None or len(keys) != 1:
            return error_response(access.request_id, "validation_failed", 422)
        if _REQUEST_KEY_PATTERN.fullmatch(keys[0]) is None:
            return error_response(access.request_id, "validation_failed", 422)
        if keys[0] != command.request_key:
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
        except SourceMutationForbidden:
            return error_response(access.request_id, "forbidden", 403)
        except SourceMutationUnauthenticated:
            return error_response(access.request_id, "unauthenticated", 401)
        except SourceMutationIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except SourceMutationRateLimited as error:
            return error_response(
                access.request_id,
                "rate_limited",
                429,
                retry_after_ms=error.retry_after_ms,
            )
        except SourceMutationAuthorityUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        if operation.request_key != command.request_key:
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            _operation_body(operation),
            status_code=202,
            headers=_write_headers(access.request_id),
        )

    async def read_operation(request: Request) -> Response:
        request_id_value, valid_request_id = strict_request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        session_digest, failure = browser_session_digest(request)
        if failure is not None:
            return error_response(request_id_value, failure[0], failure[1])
        assert session_digest is not None
        try:
            identity = await read_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if identity is None:
            return error_response(request_id_value, "unauthenticated", 401)
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id_value, "forbidden", 403)
        if authority is None:
            return error_response(request_id_value, "service_unavailable", 503)
        request_key = request.path_params.get("requestKey", "")
        if _REQUEST_KEY_PATTERN.fullmatch(request_key) is None:
            return error_response(request_id_value, "not_found", 404)
        try:
            operation = await authority.read_operation(
                request_key,
                actor_id=identity.account_id,
                session_digest=session_digest,
            )
        except SourceMutationForbidden:
            return error_response(request_id_value, "forbidden", 403)
        except SourceMutationUnauthenticated:
            return error_response(request_id_value, "unauthenticated", 401)
        except SourceMutationRateLimited as error:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=error.retry_after_ms,
            )
        except SourceMutationAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        body = (
            _operation_body(operation)
            if operation is not None
            else {"status": "not_found", "requestKey": request_key}
        )
        return JSONResponse(body, headers=system_read_headers(request_id_value))

    return (
        Route("/api/v1/system/sources/commands", mutate, methods=["POST"]),
        Route(
            "/api/v1/system/sources/operations/{requestKey:str}",
            read_operation,
            methods=["GET"],
        ),
    )


def _parse_mutation(body: dict[str, object] | None) -> RegisteredSourceMutation | None:
    if body is None:
        return None
    kind_value = body.get("kind")
    request_key = body.get("requestKey")
    name = body.get("name")
    if (
        not isinstance(kind_value, str)
        or not isinstance(request_key, str)
        or _REQUEST_KEY_PATTERN.fullmatch(request_key) is None
        or not is_bounded_wire_identifier(name, 200)
    ):
        return None
    try:
        kind = SourceMutationKind(kind_value)
    except ValueError:
        return None
    if kind is SourceMutationKind.REGISTER:
        if set(body) != {"kind", "requestKey", "name", "source"}:
            return None
        source = parse_source_connection(
            body.get("source") if isinstance(body.get("source"), dict) else None,
            source_id=None,
            expected_revision=None,
        )
    else:
        if set(body) != {
            "kind",
            "requestKey",
            "sourceId",
            "expectedRevision",
            "name",
            "source",
        }:
            return None
        source_id = body.get("sourceId")
        revision = body.get("expectedRevision")
        if (
            not is_bounded_wire_identifier(source_id, 200)
            or not is_bounded_wire_identifier(revision, 200)
        ):
            return None
        source = parse_source_connection(
            body.get("source") if isinstance(body.get("source"), dict) else None,
            source_id=source_id,
            expected_revision=revision,
        )
    if source is None:
        return None
    try:
        return RegisteredSourceMutation(kind, request_key, name, source)
    except ValueError:
        return None


def _operation_body(operation) -> dict[str, object]:
    body: dict[str, object] = {
        "status": operation.status.value,
        "requestKey": operation.request_key,
    }
    if operation.record is not None:
        body["record"] = _source_record_body(operation.record)
    if operation.status is SourceMutationStatus.NOT_FOUND:
        body["status"] = "not_found"
    if operation.reason is not None:
        body["reason"] = operation.reason.value
    return body


def _source_record_body(source: RegisteredConfigurationSource) -> dict[str, object]:
    body: dict[str, object] = {
        "id": source.id,
        "revision": source.revision,
        "name": source.name,
        "endpoint": source.endpoint,
        "authenticationMode": source.authentication_mode.value,
        "credentialConfigured": source.credential_configured,
        "provider": source.provider.value,
    }
    body[
        "namespace"
        if source.provider is ConfigurationSourceProvider.NACOS
        else "datacenter"
    ] = source.location
    return body


def _write_headers(request_id_value: str) -> dict[str, str]:
    return {
        **system_read_headers(request_id_value),
        "vary": "Cookie, Origin",
    }


