"""Authenticated rule-catalog projection and bounded source-refresh routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_catalog import ReadRuleCatalog
from ..application.read_session import ReadSession
from ..application.refresh_rule_catalog import RefreshRuleCatalog
from .http_support import error_response, read_json_object
from .rule_catalog_parsing import parse_rule_catalog_query, parse_rule_catalog_refresh
from .rule_catalog_serializers import (
    rule_catalog_page_body,
    rule_catalog_refresh_body,
)
from .session_write_access import authorize_session_write
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
)

_MAX_BODY_BYTES = 2048


def rule_catalog_routes(
    read_session: ReadSession,
    read_catalog: ReadRuleCatalog | None,
    refresh_catalog: RefreshRuleCatalog | None,
    allowed_browser_origins: frozenset[str],
) -> tuple[Route, Route]:
    """Create read and read-only refresh operations for the SQL rule projection."""

    async def read_page(request: Request) -> Response:
        request_id, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        try:
            query = parse_rule_catalog_query(request)
        except (TypeError, ValueError):
            return error_response(request_id, "invalid_request", 400)
        if read_catalog is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            body = rule_catalog_page_body(await read_catalog.execute(query))
        except (RuntimeError, TypeError, ValueError):
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(body, headers=system_read_headers(request_id))

    async def refresh(request: Request) -> Response:
        access, rejection = await authorize_session_write(
            request, read_session, allowed_browser_origins
        )
        if rejection is not None:
            return rejection
        assert access is not None
        try:
            environment_id, app_id = parse_rule_catalog_refresh(
                await read_json_object(request, _MAX_BODY_BYTES)
            )
        except (TypeError, ValueError):
            return error_response(access.request_id, "validation_failed", 422)
        if refresh_catalog is None:
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            body = rule_catalog_refresh_body(
                await refresh_catalog.execute(environment_id, app_id)
            )
        except (RuntimeError, TypeError, ValueError):
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(body, headers=system_read_headers(access.request_id))

    return (
        Route("/api/v2/rules/catalog", read_page, methods=["GET"]),
        Route("/api/v2/rules/catalog/refresh", refresh, methods=["POST"]),
    )


__all__ = ["rule_catalog_routes"]
