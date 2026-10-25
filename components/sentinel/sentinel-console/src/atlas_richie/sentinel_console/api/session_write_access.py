"""Session and CSRF proof for stateful reads allowed to both account roles."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.session import SessionIdentity
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_write_proof
from .http_support import error_response, request_id


@dataclass(frozen=True, slots=True)
class SessionWriteAccess:
    """Authenticated session identity and opaque CSRF proof digests."""

    request_id: str
    identity: SessionIdentity
    session_digest: str
    csrf_digest: str


async def authorize_session_write(
    request: Request,
    read_session: ReadSession,
    allowed_browser_origins: Collection[str],
) -> tuple[SessionWriteAccess | None, Response | None]:
    """Require a valid browser write proof and any active user session."""
    request_id_value, valid_request_id = request_id(request)
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
        identity = await read_session.execute(request.cookies.get(SESSION_COOKIE_NAME))
    except SessionAuthorityUnavailable:
        return None, error_response(request_id_value, "service_unavailable", 503)
    if identity is None:
        return None, error_response(request_id_value, "unauthenticated", 401)
    return (
        SessionWriteAccess(request_id_value, identity, proof[0], proof[1]),
        None,
    )


__all__ = ["SessionWriteAccess", "authorize_session_write"]
