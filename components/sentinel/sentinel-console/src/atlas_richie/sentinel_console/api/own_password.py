"""CSRF-protected HTTP adapter for changing the current account password."""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.change_own_password import (
    ChangeOwnPassword,
    OwnPasswordActor,
    OwnPasswordCsrfFailed,
    OwnPasswordCurrentPasswordInvalid,
    OwnPasswordRateLimited,
    OwnPasswordUnauthenticated,
    OwnPasswordUnavailable,
)
from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.account_password import AccountPassword
from .browser_origin import normalize_browser_origin
from .browser_security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    browser_write_proof,
)
from .http_support import error_response, read_json_object, request_id

_MAX_BODY_BYTES = 4096


def own_password_route(
    service: ChangeOwnPassword,
    read_session: ReadSession,
    allowed_browser_origins: frozenset[str],
) -> Route:
    """Build the own-password route with exact-Origin and double-submit CSRF."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def change_password(request: Request) -> Response:
        request_ids = request.headers.getlist("x-request-id")
        request_id_value, valid_request_id = request_id(request)
        if len(request_ids) != 1 or not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)

        proof, failure = browser_write_proof(request, allowed_origins)
        if failure is not None:
            return error_response(request_id_value, failure[0], failure[1])
        assert proof is not None

        body = await read_json_object(request, _MAX_BODY_BYTES)
        credentials = _passwords(body)
        if credentials is None:
            return error_response(request_id_value, "invalid_request", 400)
        if not _valid_utf16_length(credentials[0], 1, 1024) or not (
            _valid_utf16_length(credentials[1], 12, 1024)
        ):
            return error_response(request_id_value, "validation_failed", 422)
        try:
            new_password = AccountPassword(credentials[1])
        except (TypeError, ValueError):
            return error_response(request_id_value, "validation_failed", 422)

        try:
            identity = await read_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if identity is None:
            return error_response(request_id_value, "unauthenticated", 401)

        actor = OwnPasswordActor(
            account_id=identity.account_id,
            session_digest=proof[0],
            csrf_digest=proof[1],
        )
        try:
            result = await service.execute(
                actor=actor,
                current_password=credentials[0],
                new_password=new_password,
                request_id=request_id_value,
                now=datetime.now(UTC),
            )
        except OwnPasswordUnauthenticated:
            return error_response(request_id_value, "unauthenticated", 401)
        except OwnPasswordCurrentPasswordInvalid:
            return error_response(request_id_value, "current_password_invalid", 400)
        except OwnPasswordRateLimited as error:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=error.retry_after_ms,
            )
        except OwnPasswordCsrfFailed:
            return error_response(request_id_value, "csrf_failed", 403)
        except OwnPasswordUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        response = JSONResponse(
            {"sessionDisposition": result.disposition.value},
            headers={
                "x-request-id": request_id_value,
                "cache-control": "no-store",
                "vary": "Cookie, Origin",
            },
        )
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(
            CSRF_COOKIE_NAME,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    return Route("/api/v1/auth/password", change_password, methods=["POST"])


def _passwords(body: dict[str, object] | None) -> tuple[str, str] | None:
    if body is None or set(body) != {"currentPassword", "newPassword"}:
        return None
    current_password = body["currentPassword"]
    new_password = body["newPassword"]
    if (
        not isinstance(current_password, str)
        or not isinstance(new_password, str)
    ):
        return None
    return current_password, new_password


def _valid_utf16_length(value: str, minimum: int, maximum: int) -> bool:
    try:
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return False
    return minimum <= length <= maximum
