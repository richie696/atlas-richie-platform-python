"""Shared authenticated access and wire primitives for system observations."""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import Response

from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.session import SessionIdentity
from .browser_security import SESSION_COOKIE_NAME
from .http_support import error_response, request_id


async def authorize_system_read(
    request: Request,
    read_session: ReadSession,
    *,
    invalid_request_code: str = "invalid_request",
) -> tuple[str, SessionIdentity | None, Response | None]:
    """Validate correlation and require an active browser session for read access."""
    request_id_value, valid_request_id = request_id(request)
    if not valid_request_id:
        return (
            request_id_value,
            None,
            error_response(request_id_value, invalid_request_code, 400),
        )
    try:
        identity = await read_session.execute(
            request.cookies.get(SESSION_COOKIE_NAME)
        )
    except SessionAuthorityUnavailable:
        return (
            request_id_value,
            None,
            error_response(request_id_value, "service_unavailable", 503),
        )
    if identity is None:
        return (
            request_id_value,
            None,
            error_response(request_id_value, "unauthenticated", 401),
        )
    return request_id_value, identity, None


def system_read_headers(request_id_value: str) -> dict[str, str]:
    """Prevent caching of account-bound operational observations."""
    return {
        "x-request-id": request_id_value,
        "cache-control": "no-store",
        "vary": "Cookie",
    }


def utc_timestamp(value: datetime) -> str:
    """Serialize a wire-range, timezone-aware instant as UTC milliseconds."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Console timestamps must be timezone-aware")

    try:
        normalized = value.astimezone(UTC)
    except OverflowError as error:
        message = "Console UTC timestamps must be from 1970 through 9999"
        raise ValueError(message) from error

    if not 1970 <= normalized.year <= 9999:
        raise ValueError("Console UTC timestamps must be from 1970 through 9999")

    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")
