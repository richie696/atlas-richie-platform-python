"""HTTP adapter for operator-authorized, read-only source connectivity checks."""

from __future__ import annotations

from collections.abc import Collection

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceCheckUnavailable,
    CheckBootstrapSource,
    BootstrapSourceFailureReason,
    BootstrapSourceProvider,
    ConsulDirectCredentials,
    NacosDirectCredentials,
    NoSourceAuthentication,
    SourceAuthentication,
    SourceCredentialReference,
)
from ..application.errors import BootstrapAuthorityUnavailable
from ..application.read_bootstrap import ReadBootstrap
from ..domain.bootstrap import OpenSetupBootstrap
from ..domain.source_endpoint import (
    MAX_SOURCE_ENDPOINT_UNITS,
    is_safe_source_endpoint,
)
from ..domain.wire_strings import (
    is_bounded_wire_identifier,
    is_bounded_wire_text,
)
from .bootstrap_browser_security import has_valid_bootstrap_browser_proof
from .browser_origin import normalize_browser_origin
from .http_support import error_response, read_json_object, request_id

_OPERATOR_COOKIE_NAME = "sentinel_bootstrap"
_MAX_BODY_BYTES = 8192


def bootstrap_source_check_route(
    read_bootstrap: ReadBootstrap,
    check_source: CheckBootstrapSource | None,
    allowed_browser_origins: Collection[str],
) -> Route:
    """Create a guarded source-check route; absent connector fails closed."""
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

        candidate = parse_source_candidate(
            await read_json_object(request, _MAX_BODY_BYTES)
        )
        if candidate is None:
            return error_response(request_id_value, "invalid_request", 400)
        if check_source is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            result = await check_source.execute(candidate)
        except BootstrapSourceCheckUnavailable:
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

    return Route("/api/v1/system/bootstrap/source-check", check, methods=["POST"])


def parse_source_candidate(
    body: dict[str, object] | None,
) -> BootstrapSourceCandidate | None:
    if body is None:
        return None
    provider_value = body.get("provider")
    try:
        provider = BootstrapSourceProvider(provider_value)
    except (TypeError, ValueError):
        return None
    location_name = (
        "namespace"
        if provider is BootstrapSourceProvider.NACOS
        else "datacenter"
    )
    expected_fields = {"provider", "endpoint", location_name, "authentication"}
    if set(body) != expected_fields:
        return None

    endpoint = body.get("endpoint")
    location = body.get(location_name)
    authentication = body.get("authentication")
    if (
        not is_bounded_wire_text(endpoint, MAX_SOURCE_ENDPOINT_UNITS)
        or not is_safe_source_endpoint(endpoint)
        or not is_bounded_wire_text(location, 200)
        or not isinstance(authentication, dict)
    ):
        return None

    parsed_authentication = _parse_authentication(provider, authentication)
    if parsed_authentication is None:
        return None
    return BootstrapSourceCandidate(
        provider=provider,
        endpoint=endpoint,
        location=location,
        authentication=parsed_authentication,
    )


__all__ = ["bootstrap_source_check_route", "parse_source_candidate"]


def _parse_authentication(
    provider: BootstrapSourceProvider, body: dict[str, object]
) -> SourceAuthentication | None:
    mode = body.get("mode")
    if mode == "none" and set(body) == {"mode"}:
        return NoSourceAuthentication()
    if mode == "credential-reference" and set(body) == {"mode", "reference"}:
        reference = body.get("reference")
        if is_bounded_wire_identifier(reference, 512):
            return SourceCredentialReference(reference)
        return None
    if mode != "direct":
        return None
    if provider is BootstrapSourceProvider.NACOS:
        if set(body) != {"mode", "username", "password"}:
            return None
        username, password = body.get("username"), body.get("password")
        if (
            is_bounded_wire_identifier(username, 200)
            and isinstance(password, str)
            and password
            and is_bounded_wire_text(password, 1024)
        ):
            return NacosDirectCredentials(username, password)
        return None
    if set(body) != {"mode", "aclToken"}:
        return None
    token = body.get("aclToken")
    if isinstance(token, str) and token and is_bounded_wire_text(token, 1024):
        return ConsulDirectCredentials(token)
    return None
