"""HTTP adapter for the operator-authorized, read-only DB connectivity check."""

from __future__ import annotations

from collections.abc import Collection

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckUnavailable,
    BootstrapDatabaseChecker,
    BootstrapDatabaseKind,
)
from ..application.errors import BootstrapAuthorityUnavailable
from ..application.read_bootstrap import ReadBootstrap
from ..domain.bootstrap import OpenSetupBootstrap
from ..domain.wire_strings import (
    has_no_wire_boundary_blank,
    is_bounded_wire_identifier,
    is_bounded_wire_text,
)
from .bootstrap_browser_security import has_valid_bootstrap_browser_proof
from .browser_origin import normalize_browser_origin
from .http_support import error_response, read_json_object, request_id

_OPERATOR_COOKIE_NAME = "sentinel_bootstrap"
_MAX_BODY_BYTES = 8192


def bootstrap_database_check_route(
    read_bootstrap: ReadBootstrap,
    checker: BootstrapDatabaseChecker | None,
    allowed_browser_origins: Collection[str],
) -> Route:
    """Create a guarded check route; missing infrastructure always fails closed."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def check(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)

        if not has_valid_bootstrap_browser_proof(request, allowed_origins):
            return error_response(request_id_value, "csrf_failed", 403)

        try:
            bootstrap = await read_bootstrap.execute(
                request.cookies.get(_OPERATOR_COOKIE_NAME)
            )
        except BootstrapAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if not isinstance(bootstrap, OpenSetupBootstrap) or not (
            bootstrap.setup_available and bootstrap.operator_authorized
        ):
            return error_response(request_id_value, "bootstrap_unauthorized", 403)

        candidate = parse_database_candidate(
            await read_json_object(request, _MAX_BODY_BYTES)
        )
        if candidate is None:
            return error_response(request_id_value, "invalid_request", 400)
        if checker is None:
            return error_response(request_id_value, "service_unavailable", 503)

        try:
            result = await checker.check(candidate)
        except BootstrapDatabaseCheckUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)

        body: dict[str, str] = {
            "status": "reachable" if result.reachable else "unreachable"
        }
        if result.reason is not None:
            body["reason"] = result.reason.value
        return JSONResponse(
            body,
            headers={
                "x-request-id": request_id_value,
                "cache-control": "no-store",
                "vary": "Cookie, Origin",
            },
        )

    return Route(
        "/api/v1/system/bootstrap/database-check", check, methods=["POST"]
    )


def parse_database_candidate(
    body: dict[str, object] | None,
) -> BootstrapDatabaseCandidate | None:
    if body is None:
        return None
    try:
        kind = BootstrapDatabaseKind(body.get("kind"))
    except (TypeError, ValueError):
        return None

    if kind is BootstrapDatabaseKind.SQLITE:
        if set(body) != {"kind"}:
            return None
        return BootstrapDatabaseCandidate(kind=kind)

    if set(body) != {"kind", "host", "port", "database", "username", "password"}:
        return None
    host = body.get("host")
    port = body.get("port")
    database = body.get("database")
    username = body.get("username")
    password = body.get("password")
    if (
        not is_bounded_wire_text(host, 253)
        or not isinstance(host, str)
        or not has_no_wire_boundary_blank(host)
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or not is_bounded_wire_text(database, 200)
        or not isinstance(database, str)
        or not database
        or not is_bounded_wire_identifier(username, 200)
        or not isinstance(password, str)
        or not password
        or not is_bounded_wire_text(password, 1024)
    ):
        return None
    return BootstrapDatabaseCandidate(
        kind=kind,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )


__all__ = ["bootstrap_database_check_route", "parse_database_candidate"]
