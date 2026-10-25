"""CSRF-protected account mutation and original-operation read adapters."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.account_commands import (
    AccountCommandActor,
    AccountCommandCsrfFailed,
    AccountCommandForbidden,
    AccountCommandIdempotencyConflict,
    AccountCommandKind,
    AccountCommandUnauthenticated,
    AccountCommandUnavailable,
    AccountMutation,
    AccountOperationActor,
    AccountOperationUnavailable,
    MutateAccount,
)
from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.account_password import AccountPassword
from ..domain.account_username import AccountUsername
from ..domain.session import AccountRole
from .account_serialization import operation_body
from .browser_origin import normalize_browser_origin
from .browser_security import (
    SESSION_COOKIE_NAME,
    browser_session_digest,
    browser_write_proof,
)
from .http_support import (
    error_response,
    read_json_object,
    request_id,
)

_MAX_BODY_BYTES = 8192
_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def account_command_routes(
    service: MutateAccount,
    read_session: ReadSession,
    allowed_browser_origins: frozenset[str],
) -> tuple[Route, Route]:
    """Create account command endpoints with exact-origin and session checks."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def mutate(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        proof, failure = browser_write_proof(request, allowed_origins)
        if failure is not None:
            return error_response(request_id_value, failure[0], failure[1])
        assert proof is not None
        body = await read_json_object(request, _MAX_BODY_BYTES)
        command = _parse_command(body)
        idempotency_keys = request.headers.getlist("idempotency-key")
        if command is None or len(idempotency_keys) != 1:
            return error_response(request_id_value, "invalid_request", 400)
        if (
            _REQUEST_KEY_PATTERN.fullmatch(idempotency_keys[0]) is None
            or idempotency_keys[0] != command.request_key
        ):
            return error_response(request_id_value, "idempotency_conflict", 409)
        try:
            identity = await read_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
            if identity is None:
                raise AccountCommandUnauthenticated("browser session is inactive")
            if identity.role_id is not AccountRole.ADMIN:
                raise AccountCommandForbidden("administrator role is required")
            actor = AccountCommandActor(identity.account_id, proof[0], proof[1])
            operation = await service.execute(
                actor=actor,
                command=command,
                request_id=request_id_value,
                now=datetime.now(UTC),
            )
        except AccountCommandUnauthenticated:
            return error_response(request_id_value, "unauthenticated", 401)
        except AccountCommandForbidden:
            return error_response(request_id_value, "forbidden", 403)
        except AccountCommandCsrfFailed:
            return error_response(request_id_value, "csrf_failed", 403)
        except AccountCommandIdempotencyConflict:
            return error_response(request_id_value, "idempotency_conflict", 409)
        except AccountCommandUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            operation_body(operation),
            headers=_response_headers(request_id_value),
        )

    async def read_operation(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
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
        request_key = request.path_params.get("request_key", "")
        if _REQUEST_KEY_PATTERN.fullmatch(request_key) is None:
            return error_response(request_id_value, "invalid_request", 400)
        try:
            operation = await service.read_operation(
                request_key,
                AccountOperationActor(identity.account_id, session_digest),
            )
        except AccountCommandUnauthenticated:
            return error_response(request_id_value, "unauthenticated", 401)
        except AccountCommandForbidden:
            return error_response(request_id_value, "forbidden", 403)
        except AccountOperationUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        body = (
            operation_body(operation)
            if operation is not None
            else {"status": "not-found", "requestKey": request_key}
        )
        return JSONResponse(body, headers=_response_headers(request_id_value))

    return (
        Route("/api/v1/accounts/commands", mutate, methods=["POST"]),
        Route(
            "/api/v1/accounts/operations/{request_key:str}",
            read_operation,
            methods=["GET"],
        ),
    )


def _parse_command(body: dict[str, object] | None) -> AccountMutation | None:
    if body is None:
        return None
    kind_value = body.get("kind")
    request_key = body.get("requestKey")
    if (
        not isinstance(kind_value, str)
        or not isinstance(request_key, str)
        or _REQUEST_KEY_PATTERN.fullmatch(request_key) is None
    ):
        return None
    try:
        kind = AccountCommandKind(kind_value)
        if kind is AccountCommandKind.CREATE:
            if set(body) != {"kind", "requestKey", "input"}:
                return None
            payload = body["input"]
            if not isinstance(payload, dict) or set(payload) != {
                "username",
                "password",
                "roleId",
            }:
                return None
            username = AccountUsername(payload["username"])
            password = AccountPassword(payload["password"])
            role = AccountRole(payload["roleId"])
            return AccountMutation(request_key, kind, username, password, role)

        if kind is AccountCommandKind.STATUS:
            expected_keys = {"kind", "requestKey", "accountId", "revision", "status"}
        elif kind is AccountCommandKind.ROLE:
            expected_keys = {"kind", "requestKey", "accountId", "revision", "roleId"}
        elif kind is AccountCommandKind.RESET_PASSWORD:
            expected_keys = {"kind", "requestKey", "accountId", "revision", "password"}
        else:
            expected_keys = {"kind", "requestKey", "accountId", "revision"}
        if set(body) != expected_keys:
            return None
        account_id = body.get("accountId")
        revision_value = body.get("revision")
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or _utf16_length(account_id) > 200
            or not isinstance(revision_value, str)
            or not revision_value.isascii()
            or not revision_value.isdecimal()
            or str(int(revision_value)) != revision_value
            or not 1 <= int(revision_value) <= 9_223_372_036_854_775_807
        ):
            return None
        if kind is AccountCommandKind.STATUS:
            status = body.get("status")
            if status not in {"active", "disabled"}:
                return None
            return AccountMutation(
                request_key,
                kind,
                account_id=account_id,
                expected_revision=int(revision_value),
                status=status,
            )
        if kind in {AccountCommandKind.RESET_PASSWORD, AccountCommandKind.DELETE}:
            return AccountMutation(
                request_key,
                kind,
                account_id=account_id,
                expected_revision=int(revision_value),
                password=AccountPassword(body["password"]) if kind is AccountCommandKind.RESET_PASSWORD else None,
            )
        return AccountMutation(
            request_key,
            kind,
            role_id=AccountRole(body.get("roleId")),
            account_id=account_id,
            expected_revision=int(revision_value),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _utf16_length(value: str) -> int:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return 10**9


def _response_headers(request_id_value: str) -> dict[str, str]:
    return {
        "x-request-id": request_id_value,
        "cache-control": "no-store",
        "vary": "Cookie, Origin",
    }
