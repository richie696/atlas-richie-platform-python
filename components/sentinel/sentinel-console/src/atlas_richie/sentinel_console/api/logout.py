"""HTTP adapter for authenticated browser-session logout."""

from __future__ import annotations

from collections.abc import Collection
import hmac

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ..application.errors import SessionAuthorityUnavailable
from ..application.revoke_current_session import RevokeCurrentSession
from ..domain.session import SessionRevocationResult
from .browser_origin import normalize_browser_origin
from .browser_security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from .http_support import cookie_count, error_response, request_id


def logout_route(
    revoke_session: RevokeCurrentSession,
    allowed_browser_origins: Collection[str],
) -> Route:
    """Create the CSRF- and exact-Origin-protected logout protocol adapter."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def logout(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)

        origin_values = request.headers.getlist("origin")
        if len(origin_values) != 1:
            return error_response(request_id_value, "csrf_failed", 403)
        try:
            origin = normalize_browser_origin(origin_values[0])
        except ValueError:
            return error_response(request_id_value, "csrf_failed", 403)
        if origin not in allowed_origins:
            return error_response(request_id_value, "csrf_failed", 403)

        csrf_values = request.headers.getlist("x-sentinel-csrf")
        if len(csrf_values) != 1:
            return error_response(request_id_value, "csrf_failed", 403)
        if cookie_count(request, SESSION_COOKIE_NAME) > 1:
            return error_response(request_id_value, "unauthenticated", 401)
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if (
            cookie_count(request, CSRF_COOKIE_NAME) != 1
            or csrf_cookie is None
            or not hmac.compare_digest(csrf_values[0], csrf_cookie)
        ):
            return error_response(request_id_value, "csrf_failed", 403)

        try:
            result = await revoke_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME),
                csrf_values[0],
            )
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        if result is SessionRevocationResult.UNAUTHENTICATED:
            return error_response(request_id_value, "unauthenticated", 401)
        if result is SessionRevocationResult.CSRF_FAILED:
            return error_response(request_id_value, "csrf_failed", 403)

        response = Response(
            status_code=204,
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

    return Route("/api/v1/auth/logout", logout, methods=["POST"])
