"""Shared admin-session and double-submit CSRF gate for console writes."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.session import AccountRole, SessionIdentity
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_write_proof
from .http_support import error_response, strict_request_id


@dataclass(frozen=True, slots=True)
class AdminWriteAccess:
    """Current administrator and opaque proof digests for one request."""

    request_id: str
    identity: SessionIdentity
    session_digest: str
    csrf_digest: str


async def authorize_admin_write(
    request: Request,
    read_session: ReadSession,
    allowed_browser_origins: Collection[str],
) -> tuple[AdminWriteAccess | None, Response | None]:
    """Validate request-id, browser proof, active session and admin role in order."""
    request_id_value, valid_request_id = strict_request_id(request)
    if not valid_request_id:
        return None, error_response(request_id_value, "invalid_request", 400)
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    proof, failure = browser_write_proof(request, allowed_origins)
    if failure is not None:
        return None, error_response(request_id_value, failure[0], failure[1])
    assert proof is not None
    try:
        identity = await read_session.execute(
            request.cookies.get(SESSION_COOKIE_NAME)
        )
    except SessionAuthorityUnavailable:
        return None, error_response(request_id_value, "service_unavailable", 503)
    if identity is None:
        return None, error_response(request_id_value, "unauthenticated", 401)
    if identity.role_id is not AccountRole.ADMIN:
        return None, error_response(request_id_value, "forbidden", 403)
    return AdminWriteAccess(request_id_value, identity, proof[0], proof[1]), None
