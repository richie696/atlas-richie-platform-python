"""HTTP adapter for the authenticated-session observation endpoint."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.session import SessionIdentity
from .browser_security import SESSION_COOKIE_NAME
from .http_support import error_response, request_id


def _identity_body(identity: SessionIdentity | None) -> dict[str, object] | None:
    if identity is None:
        return None
    return {
        "accountId": identity.account_id,
        "username": identity.username,
        "roleId": identity.role_id.value,
        "capabilities": [capability.value for capability in identity.capabilities],
        "sessionEpoch": identity.session_epoch,
    }


def session_route(read_session: ReadSession) -> Route:
    """Create the strict ``GET /auth/me`` protocol adapter."""

    async def read(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)

        try:
            identity = await read_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        return JSONResponse(
            _identity_body(identity),
            headers={
                "x-request-id": request_id_value,
                "cache-control": "no-store",
                "vary": "Cookie",
            },
        )

    return Route("/api/v1/auth/me", read, methods=["GET"])
