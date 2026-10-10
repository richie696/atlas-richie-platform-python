"""HTTP adapters for initialization and safe operation recovery."""

from __future__ import annotations

import re
from collections.abc import Collection

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.bootstrap_initialization import (
    BootstrapInitializationForbidden,
    BootstrapInitializationIdempotencyConflict,
    BootstrapInitializationInput,
    BootstrapInitializationReceipt,
    BootstrapInitializationStatus,
    InitializeConsole,
    ReadBootstrapInitialization,
)
from ..application.errors import BootstrapAuthorityUnavailable
from ..domain.account_password import AccountPassword
from ..domain.account_username import AccountUsername
from .bootstrap_browser_security import has_valid_bootstrap_browser_proof
from .bootstrap_database_check import parse_database_candidate
from .bootstrap_source_check import parse_source_candidate
from .browser_origin import normalize_browser_origin
from .http_support import error_response, read_json_object, strict_request_id

_OPERATOR_COOKIE_NAME = "sentinel_bootstrap"
_MAX_BODY_BYTES = 16_384
_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def bootstrap_initialization_routes(
    initialize_console: InitializeConsole,
    read_operation: ReadBootstrapInitialization,
    allowed_browser_origins: Collection[str],
) -> tuple[Route, Route]:
    """Create setup command and authenticated recovery endpoints.

    The injected initializer owns durable coordination/recovery, the external
    runtime locator, setup-window closure and request-key idempotency.
    """
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def initialize(request: Request) -> Response:
        request_id_value, valid_request_id = strict_request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        if not has_valid_bootstrap_browser_proof(request, allowed_origins):
            return error_response(request_id_value, "csrf_failed", 403)

        payload = await read_json_object(request, _MAX_BODY_BYTES)
        parsed = _parse_command(payload)
        idempotency_keys = request.headers.getlist("idempotency-key")
        if parsed is None or len(idempotency_keys) != 1:
            return error_response(request_id_value, "invalid_request", 400)
        request_key, command = parsed
        if (
            _REQUEST_KEY_PATTERN.fullmatch(idempotency_keys[0]) is None
            or idempotency_keys[0] != request_key
        ):
            return error_response(request_id_value, "idempotency_conflict", 409)

        try:
            receipt = await initialize_console.execute(
                operator_session=request.cookies.get(_OPERATOR_COOKIE_NAME),
                request_key=request_key,
                input=command,
            )
        except BootstrapInitializationForbidden:
            return error_response(request_id_value, "bootstrap_unauthorized", 403)
        except BootstrapInitializationIdempotencyConflict:
            return error_response(request_id_value, "idempotency_conflict", 409)
        except BootstrapAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if (
            receipt.request_key != request_key
            or receipt.status is BootstrapInitializationStatus.NOT_FOUND
        ):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _receipt_body(receipt),
            headers=_response_headers(request_id_value),
        )

    async def read(request: Request) -> Response:
        request_id_value, valid_request_id = strict_request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        request_key = request.path_params.get("request_key", "")
        if _REQUEST_KEY_PATTERN.fullmatch(request_key) is None:
            return error_response(request_id_value, "invalid_request", 400)
        try:
            receipt = await read_operation.execute(
                request.cookies.get(_OPERATOR_COOKIE_NAME), request_key
            )
        except BootstrapInitializationForbidden:
            return error_response(request_id_value, "bootstrap_unauthorized", 403)
        except BootstrapAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if receipt is None:
            body = {"status": "not-found", "requestKey": request_key}
        elif receipt.request_key != request_key:
            return error_response(request_id_value, "service_unavailable", 503)
        else:
            body = _receipt_body(receipt)
        return JSONResponse(body, headers=_response_headers(request_id_value))

    return (
        Route("/api/v1/system/bootstrap/initialize", initialize, methods=["POST"]),
        Route(
            "/api/v1/system/bootstrap/operations/{request_key:str}",
            read,
            methods=["GET"],
        ),
    )


def _parse_command(
    body: dict[str, object] | None,
) -> tuple[str, BootstrapInitializationInput] | None:
    if body is None or set(body) != {"requestKey", "input"}:
        return None
    request_key = body.get("requestKey")
    payload = body.get("input")
    if (
        not isinstance(request_key, str)
        or _REQUEST_KEY_PATTERN.fullmatch(request_key) is None
        or not isinstance(payload, dict)
        or set(payload) != {"database", "admin", "source"}
    ):
        return None
    database = payload.get("database")
    admin = payload.get("admin")
    source = payload.get("source")
    if not isinstance(database, dict) or not isinstance(admin, dict):
        return None
    if set(admin) != {"username", "password"}:
        return None
    username_value = admin.get("username")
    password_value = admin.get("password")
    if not isinstance(username_value, str) or not isinstance(password_value, str):
        return None
    database_candidate = parse_database_candidate(database)
    source_body = source if isinstance(source, dict) else None
    source_candidate = parse_source_candidate(source_body)
    if database_candidate is None or source_candidate is None:
        return None
    try:
        command = BootstrapInitializationInput(
            database=database_candidate,
            admin_username=AccountUsername(username_value),
            admin_password=AccountPassword(password_value),
            source=source_candidate,
        )
    except (TypeError, ValueError):
        return None
    return request_key, command


def _receipt_body(receipt: BootstrapInitializationReceipt) -> dict[str, str]:
    body = {"status": receipt.status.value, "requestKey": receipt.request_key}
    if receipt.operation_id is not None:
        body["operationId"] = receipt.operation_id
    if receipt.reason is not None:
        body["reason"] = receipt.reason.value
    return body


def _response_headers(request_id_value: str) -> dict[str, str]:
    return {
        "x-request-id": request_id_value,
        "cache-control": "no-store",
        "vary": "Cookie, Origin",
    }


__all__ = ["bootstrap_initialization_routes"]
