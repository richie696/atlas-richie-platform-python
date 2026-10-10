"""HTTP adapter for deployment-owned bootstrap operator-code exchange."""

from __future__ import annotations

from collections.abc import Collection

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.authorize_bootstrap import (
    BootstrapAuthorizationAuthority,
    BootstrapAuthorizationStatus,
    is_valid_bootstrap_operator_code,
)
from ..application.errors import BootstrapAuthorityUnavailable
from ..application.issue_csrf_nonce import IssueCsrfNonce
from .browser_origin import normalize_browser_origin
from .browser_security import CSRF_COOKIE_NAME
from .bootstrap_browser_security import has_valid_bootstrap_browser_proof
from .client_address import ClientAddressResolver
from .http_support import error_response, read_json_object, request_id

_MAX_BODY_BYTES = 4096
_GRANT_COOKIE_NAME = "sentinel_bootstrap"


def bootstrap_authorize_route(
    authority: BootstrapAuthorizationAuthority | None,
    allowed_browser_origins: Collection[str],
    client_address_resolver: ClientAddressResolver | None = None,
) -> Route:
    """Create the public setup-code exchange; missing authority fails closed."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")
    address_resolver = client_address_resolver or ClientAddressResolver()

    async def authorize(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        if not _has_allowed_origin(request, allowed_origins):
            return error_response(request_id_value, "forbidden", 403)
        if not has_valid_bootstrap_browser_proof(request, allowed_origins):
            return error_response(request_id_value, "csrf_failed", 403)
        body = await read_json_object(request, _MAX_BODY_BYTES)
        operator_code = _parse_operator_code(body)
        if operator_code is None:
            return error_response(request_id_value, "invalid_request", 400)
        if authority is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            decision = await authority.exchange(
                operator_code, address_resolver.resolve(request)
            )
        except BootstrapAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        if decision.status is BootstrapAuthorizationStatus.REJECTED:
            return error_response(request_id_value, "forbidden", 403)
        if decision.status is BootstrapAuthorizationStatus.SETUP_CLOSED:
            return error_response(request_id_value, "conflict", 409)
        if decision.status is BootstrapAuthorizationStatus.RATE_LIMITED:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=decision.retry_after_ms,
            )
        grant = decision.grant
        if grant is None:
            return error_response(request_id_value, "service_unavailable", 503)

        csrf_nonce = IssueCsrfNonce().execute(
            request.cookies.get(CSRF_COOKIE_NAME)
        )
        response = JSONResponse(
            {"authorized": True},
            headers={
                "x-request-id": request_id_value,
                "x-sentinel-csrf": csrf_nonce.value,
                "cache-control": "no-store",
                "vary": "Cookie, Origin",
            },
        )
        response.set_cookie(
            _GRANT_COOKIE_NAME,
            grant.opaque_session,
            max_age=grant.expires_in_seconds,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_nonce.value,
            max_age=grant.expires_in_seconds,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    return Route("/api/v1/system/bootstrap/authorize", authorize, methods=["POST"])


def _has_allowed_origin(request: Request, allowed_origins: frozenset[str]) -> bool:
    values = request.headers.getlist("origin")
    if len(values) != 1:
        return False
    try:
        return normalize_browser_origin(values[0]) in allowed_origins
    except ValueError:
        return False


def _parse_operator_code(body: dict[str, object] | None) -> str | None:
    if body is None or set(body) != {"operatorCode"}:
        return None
    code = body.get("operatorCode")
    if not is_valid_bootstrap_operator_code(code):
        return None
    return code
