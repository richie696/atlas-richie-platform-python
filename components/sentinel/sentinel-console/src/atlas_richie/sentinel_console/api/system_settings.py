"""Authenticated system display settings endpoints."""

from __future__ import annotations

from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_session import ReadSession
from .admin_write_access import authorize_admin_write
from .http_support import error_response
from .system_observation_access import authorize_system_read, system_read_headers


class SystemSettingsStore(Protocol):
    """Persistence boundary used by this API adapter."""

    async def read_time_zone(self) -> tuple[str, int]: ...

    async def update_time_zone(self, time_zone: str) -> tuple[str, int]: ...


def system_settings_routes(
    read_session: ReadSession,
    store: SystemSettingsStore,
    origins: frozenset[str],
) -> list[Route]:
    """Build the authenticated read and administrator-only timezone update routes."""

    async def read_settings(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(request, read_session)
        if rejection is not None:
            return rejection
        try:
            time_zone, revision = await store.read_time_zone()
        except Exception:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            {"timeZone": time_zone, "revision": revision},
            headers=system_read_headers(request_id_value),
        )

    async def update_settings(request: Request) -> Response:
        access, rejection = await authorize_admin_write(request, read_session, origins)
        if rejection is not None:
            return rejection
        assert access is not None
        try:
            body = await request.json()
        except Exception:
            return error_response(access.request_id, "invalid_request", 400)
        if not isinstance(body, dict) or set(body) != {"timeZone"}:
            return error_response(access.request_id, "invalid_request", 400)
        time_zone = body.get("timeZone")
        if not isinstance(time_zone, str) or len(time_zone) > 128:
            return error_response(access.request_id, "invalid_request", 400)
        try:
            ZoneInfo(time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            return error_response(access.request_id, "invalid_request", 400)
        try:
            saved_zone, revision = await store.update_time_zone(time_zone)
        except Exception:
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            {"timeZone": saved_zone, "revision": revision},
            headers=system_read_headers(access.request_id),
        )

    return [
        Route("/api/v1/system/settings", read_settings, methods=["GET"]),
        Route("/api/v1/system/settings", update_settings, methods=["PUT"]),
    ]
