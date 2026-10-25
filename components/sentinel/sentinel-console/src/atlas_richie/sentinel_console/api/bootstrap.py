"""HTTP adapter for the Console bootstrap snapshot operation."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.errors import BootstrapAuthorityUnavailable
from ..application.issue_csrf_nonce import IssueCsrfNonce
from ..application.read_bootstrap import ReadBootstrap
from ..domain.bootstrap import InitializedBootstrap, OpenSetupBootstrap
from .browser_security import CSRF_COOKIE_NAME, SECURE_COOKIES
from .http_support import error_response, request_id

_OPERATOR_COOKIE_NAME = "sentinel_bootstrap"


def bootstrap_route(read_bootstrap: ReadBootstrap) -> Route:
    """Create the single bootstrap route with strict, finite wire projection."""

    async def read(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)

        operator_session = request.cookies.get(_OPERATOR_COOKIE_NAME)
        try:
            snapshot = await read_bootstrap.execute(operator_session)
        except BootstrapAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        if isinstance(snapshot, InitializedBootstrap):
            body = {"initialized": True}
        elif isinstance(snapshot, OpenSetupBootstrap):
            body = {
                "initialized": False,
                "setupAvailable": snapshot.setup_available,
                "operatorAuthorized": snapshot.operator_authorized,
            }
        else:  # Defensive against a broken application port implementation.
            return error_response(request_id_value, "service_unavailable", 503)

        csrf_nonce = IssueCsrfNonce().execute(
            request.cookies.get(CSRF_COOKIE_NAME)
        )
        response = JSONResponse(
            body,
            headers={
                "x-request-id": request_id_value,
                "x-sentinel-csrf": csrf_nonce.value,
                "cache-control": "no-store",
                "vary": "Cookie, Origin",
            },
        )
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_nonce.value,
            path="/",
            secure=SECURE_COOKIES,
            httponly=True,
            samesite="strict",
        )
        return response

    return Route("/api/v1/system/bootstrap", read, methods=["GET"])
