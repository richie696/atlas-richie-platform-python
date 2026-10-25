"""Admin-only, CSRF-protected registered-source check adapter."""

from __future__ import annotations

from collections.abc import Collection

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.check_registered_source import (
    CheckRegisteredSource,
    RegisteredSourceCheckRateLimited,
    RegisteredSourceCheckUnavailable,
    SourceConnectionInput,
)
from ..application.read_session import ReadSession
from .admin_write_access import authorize_admin_write
from .browser_origin import normalize_browser_origin
from .http_support import error_response, read_json_object
from .source_connection_parsing import parse_source_connection
from .system_observation_access import system_read_headers, utc_timestamp

_MAX_BODY_BYTES = 8192


def registered_source_check_route(
    read_session: ReadSession,
    check_source: CheckRegisteredSource | None,
    allowed_browser_origins: Collection[str],
) -> Route:
    """Create a session/admin/CSRF guarded non-mutating source probe."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def check(request: Request) -> Response:
        access, rejection = await authorize_admin_write(
            request, read_session, allowed_origins
        )
        if rejection is not None:
            return rejection
        assert access is not None
        request_id_value = access.request_id
        command = _parse_command(await read_json_object(request, _MAX_BODY_BYTES))
        if command is None:
            return error_response(request_id_value, "invalid_request", 400)
        if check_source is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            result = await check_source.execute(command, access.identity.account_id)
        except RegisteredSourceCheckRateLimited as error:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=error.retry_after_ms,
            )
        except RegisteredSourceCheckUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        body: dict[str, object] = {
            "status": "reachable" if result.reachable else "unreachable",
            "checkedAt": utc_timestamp(result.checked_at),
            "expiresAt": utc_timestamp(result.expires_at),
        }
        if result.reachable:
            body["capabilities"] = [
                capability.value for capability in result.capabilities
            ]
        else:
            body["reason"] = result.reason.value
        return JSONResponse(
            body,
            headers=system_read_headers(request_id_value),
        )

    return Route("/api/v1/system/sources/check", check, methods=["POST"])


def _parse_command(
    body: dict[str, object] | None,
) -> SourceConnectionInput | None:
    if body is None or set(body) != {"sourceId", "expectedRevision", "source"}:
        return None
    source = body.get("source")
    if not isinstance(source, dict):
        return None
    return parse_source_connection(
        source,
        source_id=body.get("sourceId"),
        expected_revision=body.get("expectedRevision"),
    )
