"""Strict CSRF-protected HTTP adapter for browser login."""

from __future__ import annotations

import hashlib
import hmac

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .client_address import ClientAddressResolver
from ..application.login import Login, LoginOutcome
from ..application.login_ports import LoginAuthorityUnavailable
from .browser_origin import normalize_browser_origin
from .browser_security import CSRF_COOKIE_NAME, SECURE_COOKIES, SESSION_COOKIE_NAME
from ..domain.account_username import AccountUsername
from .http_support import cookie_count, error_response, read_json_object, request_id

_MAX_BODY_BYTES = 4096
_OPAQUE_VALUE_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


def login_route(
    login: Login,
    allowed_browser_origins: frozenset[str],
    client_identity_hmac_key: bytes,
    client_address_resolver: ClientAddressResolver | None = None,
) -> Route:
    """Create login endpoint after exact origin and double-submit CSRF checks."""
    if (
        not isinstance(client_identity_hmac_key, bytes)
        or len(client_identity_hmac_key) < 32
    ):
        raise ValueError("client identity HMAC key must be at least 32 bytes")
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")
    address_resolver = client_address_resolver or ClientAddressResolver()

    async def authenticate(request: Request) -> Response:
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
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if (
            len(csrf_values) != 1
            or cookie_count(request, CSRF_COOKIE_NAME) != 1
            or not _is_opaque_value(csrf_values[0])
            or csrf_cookie is None
            or not hmac.compare_digest(csrf_values[0], csrf_cookie)
        ):
            return error_response(request_id_value, "csrf_failed", 403)
        if cookie_count(request, SESSION_COOKIE_NAME) > 1:
            return error_response(request_id_value, "unauthenticated", 401)

        credentials = await _read_credentials(request)
        if credentials is None:
            return error_response(request_id_value, "invalid_request", 400)

        remote_host = address_resolver.resolve(request)
        client_identity_digest = hmac.new(
            client_identity_hmac_key,
            remote_host.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        try:
            result = await login.execute(
                username=credentials[0],
                password=credentials[1],
                client_identity_digest=client_identity_digest,
                previous_session_token=request.cookies.get(SESSION_COOKIE_NAME),
            )
        except LoginAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        if result.outcome is LoginOutcome.REJECTED:
            return error_response(request_id_value, "unauthenticated", 401)
        if result.outcome is LoginOutcome.RATE_LIMITED:
            if result.retry_after_ms is None:
                return error_response(request_id_value, "service_unavailable", 503)
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=result.retry_after_ms,
            )
        if result.outcome is not LoginOutcome.AUTHENTICATED or result.session is None:
            return error_response(request_id_value, "service_unavailable", 503)

        identity = result.session.identity
        response = JSONResponse(
            {
                "accountId": identity.account_id,
                "username": identity.username,
                "roleId": identity.role_id.value,
                "capabilities": [item.value for item in identity.capabilities],
                "sessionEpoch": identity.session_epoch,
            },
            headers={
                "x-request-id": request_id_value,
                "x-sentinel-csrf": result.session.csrf_nonce,
                "cache-control": "no-store",
                "vary": "Cookie, Origin",
            },
        )
        response.set_cookie(
            SESSION_COOKIE_NAME,
            result.session.session_token,
            path="/",
            secure=SECURE_COOKIES,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            CSRF_COOKIE_NAME,
            result.session.csrf_nonce,
            path="/",
            secure=SECURE_COOKIES,
            httponly=True,
            samesite="strict",
        )
        return response

    return Route("/api/v1/auth/login", authenticate, methods=["POST"])


async def _read_credentials(request: Request) -> tuple[str, str] | None:
    """Read a bounded exact-shape JSON body without echoing submitted values."""
    body = await read_json_object(request, _MAX_BODY_BYTES)
    if body is None:
        return None
    if not isinstance(body, dict) or set(body) != {"username", "password"}:
        return None
    username = body["username"]
    password = body["password"]
    if (
        not isinstance(username, str)
        or not isinstance(password, str)
        or not _has_valid_text_length(password, 1024)
    ):
        return None
    try:
        normalized_username = AccountUsername(username).value
    except (TypeError, ValueError):
        return None
    return normalized_username, password


def _has_valid_text_length(value: str, maximum: int) -> bool:
    try:
        return 1 <= _utf16_length(value) <= maximum
    except UnicodeEncodeError:
        return False


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _is_opaque_value(value: str) -> bool:
    return 32 <= len(value) <= 256 and all(
        character in _OPAQUE_VALUE_CHARACTERS for character in value
    )
