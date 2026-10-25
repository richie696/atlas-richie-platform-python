"""Authenticated, credential-free reads for monitoring source metadata."""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.monitoring_source_registry import (
    MonitoringSourceNotFound,
    MonitoringSourceCommandForbidden,
    MonitoringSourceCommandUnavailable,
    MonitoringSourceIdempotencyConflict,
    MonitoringSourceMutation,
    MonitoringSourceRegistryPort,
    MonitoringSourceRegistryUnavailable,
    ReadMonitoringSource,
    ReadMonitoringSources,
    ManageMonitoringSource,
    MonitoringCredentialUpdateMode,
    MonitoringSourceSecret,
)
from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..domain.monitoring_sources import MonitoringSource, MonitoringSourcesSnapshot
from ..domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
)
from ..domain.session import AccountRole
from .admin_write_access import authorize_admin_write
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_session_digest
from .http_support import error_response, read_json_object, request_id
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)

_MAX_COMMAND_BYTES = 16 * 1024
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def monitoring_source_read_routes(
    read_session: ReadSession,
    registry: MonitoringSourceRegistryPort | None,
) -> tuple[Route, Route]:
    """Build the safe directory (admin/view) and admin-only detail routes."""

    async def read_directory(request: Request) -> Response:
        request_id, identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if registry is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            snapshot = await ReadMonitoringSources(registry).execute()
        except MonitoringSourceRegistryUnavailable:
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(
            _snapshot_body(snapshot), headers=system_read_headers(request_id)
        )

    async def read_detail(request: Request) -> Response:
        request_id, identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id, "forbidden", 403)
        if registry is None:
            return error_response(request_id, "service_unavailable", 503)
        source_id = request.path_params.get("sourceId", "")
        try:
            source = await ReadMonitoringSource(registry).execute(source_id)
        except MonitoringSourceNotFound:
            return error_response(request_id, "not_found", 404)
        except MonitoringSourceRegistryUnavailable:
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(
            _source_detail_body(source), headers=system_read_headers(request_id)
        )

    return (
        Route("/api/v2/monitoring/sources", read_directory, methods=["GET"]),
        Route(
            "/api/v2/monitoring/sources/{sourceId:str}",
            read_detail,
            methods=["GET"],
        ),
    )


def monitoring_source_management_routes(
    read_session: ReadSession,
    registry: MonitoringSourceRegistryPort | None,
    allowed_browser_origins: Collection[str],
    fingerprint_key: bytes | None,
) -> tuple[Route, Route]:
    """Create idempotent admin commands and same-session operation readback."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def command(request: Request) -> Response:
        access, rejection = await authorize_admin_write(
            request, read_session, allowed_origins
        )
        if rejection is not None:
            return rejection
        assert access is not None
        parsed = _parse_mutation(
            await read_json_object(request, _MAX_COMMAND_BYTES),
            actor_id=access.identity.account_id,
            session_digest=access.session_digest,
            request_id=access.request_id,
        )
        keys = request.headers.getlist("idempotency-key")
        if parsed is None or len(keys) != 1 or keys[0] != parsed.request_key:
            return error_response(access.request_id, "validation_failed", 422)
        if registry is None or fingerprint_key is None:
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            operation = await ManageMonitoringSource(
                registry, fingerprint_key
            ).execute(parsed)
        except MonitoringSourceCommandForbidden:
            return error_response(access.request_id, "forbidden", 403)
        except MonitoringSourceIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except MonitoringSourceCommandUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            _operation_body(operation),
            status_code=202,
            headers=system_read_headers(access.request_id),
        )

    async def read_operation(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        session_digest, failure = browser_session_digest(request)
        if failure is not None:
            return error_response(request_id_value, failure[0], failure[1])
        assert session_digest is not None
        try:
            identity = await read_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if identity is None:
            return error_response(request_id_value, "unauthenticated", 401)
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id_value, "forbidden", 403)
        request_key = request.path_params.get("requestKey", "")
        if _REQUEST_KEY.fullmatch(request_key) is None:
            return error_response(request_id_value, "not_found", 404)
        if registry is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            operation = await registry.read_monitoring_source_operation(
                request_key,
                actor_id=identity.account_id,
                session_digest=session_digest,
            )
        except MonitoringSourceCommandForbidden:
            return error_response(request_id_value, "forbidden", 403)
        except MonitoringSourceCommandUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if operation is None:
            return JSONResponse(
                {"status": "not_found", "requestKey": request_key},
                headers=system_read_headers(request_id_value),
            )
        return JSONResponse(
            _operation_body(operation), headers=system_read_headers(request_id_value)
        )

    return (
        Route("/api/v2/monitoring/sources/commands", command, methods=["POST"]),
        Route(
            "/api/v2/monitoring/sources/operations/{requestKey:str}",
            read_operation,
            methods=["GET"],
        ),
    )


def _parse_mutation(
    body: dict[str, object] | None,
    *,
    actor_id: str,
    session_digest: str,
    request_id: str,
) -> MonitoringSourceMutation | None:
    if body is None:
        return None
    kind = body.get("kind")
    request_key = body.get("requestKey")
    if not isinstance(request_key, str) or _REQUEST_KEY.fullmatch(request_key) is None:
        return None
    if kind == "set-enabled":
        if set(body) != {"kind", "requestKey", "sourceId", "expectedRevision", "enabled"}:
            return None
        source_id, revision = body.get("sourceId"), body.get("expectedRevision")
        enabled = body.get("enabled")
        if not _valid_identifier(source_id, 200) or not _valid_identifier(revision, 200) or type(enabled) is not bool:
            return None
        return MonitoringSourceMutation(
            request_key=request_key,
            kind="set-enabled",
            actor_id=actor_id,
            session_digest=session_digest,
            request_id=request_id,
            source_id=source_id,
            expected_revision=revision,
            enabled=enabled,
            now=datetime.now(UTC),
        )
    if kind == "delete":
        if set(body) != {"kind", "requestKey", "sourceId", "expectedRevision"}:
            return None
        source_id, revision = body.get("sourceId"), body.get("expectedRevision")
        if not _valid_identifier(source_id, 200) or not _valid_identifier(revision, 200):
            return None
        return MonitoringSourceMutation(
            request_key=request_key,
            kind="delete",
            actor_id=actor_id,
            session_digest=session_digest,
            request_id=request_id,
            source_id=source_id,
            expected_revision=revision,
            now=datetime.now(UTC),
        )
    common = {"kind", "requestKey", "source", "credentials", "credentialUpdate"}
    is_create = kind == "create"
    expected_fields = common | ({"checkId", "skipCheck"} if is_create else {"expectedRevision", "checkId", "skipCheck"})
    if set(body) != expected_fields:
        return None
    credential_update_value = body.get("credentialUpdate")
    try:
        credential_update = MonitoringCredentialUpdateMode(credential_update_value)
    except ValueError:
        return None
    parsed = _parse_source_candidate(
        body.get("source"), body.get("credentials"), credential_update
    )
    if parsed is None or (
        is_create and credential_update is MonitoringCredentialUpdateMode.KEEP
    ):
        return None
    source, secret = parsed
    check_id = body.get("checkId")
    skip_check = body.get("skipCheck")
    if type(skip_check) is not bool:
        return None
    if check_id is not None:
        try:
            UUID(check_id)
        except (TypeError, ValueError):
            return None
    if (check_id is None) == (not skip_check):
        return None
    if credential_update is MonitoringCredentialUpdateMode.KEEP and not skip_check:
        return None
    expected_revision = None
    if not is_create:
        expected_revision = body.get("expectedRevision")
        if not _valid_identifier(expected_revision, 200) or source.revision != expected_revision:
            return None
    return MonitoringSourceMutation(
        request_key=request_key,
        kind="create" if is_create else "update",
        actor_id=actor_id,
        session_digest=session_digest,
        request_id=request_id,
        source=source,
        expected_revision=expected_revision,
        credential_update=credential_update,
        secret=secret,
        check_id=check_id,
        skip_check=skip_check,
        now=datetime.now(UTC),
    )


def _parse_source_candidate(
    raw_source: object,
    raw_credentials: object,
    credential_update: MonitoringCredentialUpdateMode,
) -> tuple[MonitoringSource, MonitoringSourceSecret | None] | None:
    expected = {
        "sourceId", "revision", "displayName", "environmentId", "endpoint",
        "provider", "profile", "authenticationMode", "credentialConfigured",
        "enabled", "identityLabels", "selectorLabels", "scrapeIntervalSeconds",
        "staleAfterSeconds",
    }
    if not isinstance(raw_source, dict) or set(raw_source) != expected:
        return None
    try:
        source = MonitoringSource(
            source_id=raw_source["sourceId"],
            revision=raw_source["revision"],
            display_name=raw_source["displayName"],
            environment_id=raw_source["environmentId"],
            endpoint=raw_source["endpoint"],
            provider=MonitoringProvider(raw_source["provider"]),
            profile=MonitoringProfile(raw_source["profile"]),
            authentication_mode=MonitoringAuthenticationMode(raw_source["authenticationMode"]),
            credential_configured=raw_source["credentialConfigured"],
            enabled=raw_source["enabled"],
            identity_labels=tuple(raw_source["identityLabels"]),
            selector_labels=tuple(
                MonitoringLabel(item["name"], item["value"])
                for item in raw_source["selectorLabels"]
            ),
            scrape_interval_seconds=raw_source["scrapeIntervalSeconds"],
            stale_after_seconds=raw_source["staleAfterSeconds"],
        )
        mode = source.authentication_mode
        if credential_update in {
            MonitoringCredentialUpdateMode.KEEP,
            MonitoringCredentialUpdateMode.CLEAR,
        }:
            if raw_credentials is not None:
                return None
            if credential_update is MonitoringCredentialUpdateMode.KEEP:
                return (source, None) if mode is not MonitoringAuthenticationMode.NONE else None
            return (source, None) if mode is MonitoringAuthenticationMode.NONE else None
        if mode is MonitoringAuthenticationMode.NONE:
            return None
        if not isinstance(raw_credentials, dict):
            return None
        if mode is MonitoringAuthenticationMode.DIRECT_BASIC and set(raw_credentials) == {"username", "password"}:
            secret = MonitoringSourceSecret(raw_credentials["username"], raw_credentials["password"])
        elif mode is MonitoringAuthenticationMode.DIRECT_BEARER and set(raw_credentials) == {"bearerToken"}:
            secret = MonitoringSourceSecret(bearer_token=raw_credentials["bearerToken"])
        elif mode is MonitoringAuthenticationMode.CREDENTIAL_REFERENCE and set(raw_credentials) == {"reference"}:
            secret = MonitoringSourceSecret(credential_reference=raw_credentials["reference"])
        else:
            return None
        return source, secret
    except (KeyError, TypeError, ValueError):
        return None


def _operation_body(operation) -> dict[str, object]:
    result: dict[str, object] = {
        "status": operation.status.value,
        "requestKey": operation.request_key,
    }
    if operation.source_id is not None:
        result["sourceId"] = operation.source_id
    if operation.source_revision is not None:
        result["sourceRevision"] = operation.source_revision
    if operation.enabled is not None:
        result["enabled"] = operation.enabled
    if operation.verified is not None:
        result["verified"] = operation.verified
    if operation.reason is not None:
        result["reason"] = operation.reason.value
    return result


def _valid_identifier(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum and value.strip() == value


def _snapshot_body(snapshot: MonitoringSourcesSnapshot) -> dict[str, object]:
    return {
        "asOf": utc_timestamp(snapshot.as_of),
        "items": [_directory_item(source) for source in snapshot.items],
    }


def _directory_item(source: MonitoringSource) -> dict[str, object]:
    return {
        "id": source.source_id,
        "revision": source.revision,
        "displayName": source.display_name,
        "environmentId": source.environment_id,
        "provider": source.provider.value,
        "profile": source.profile.value,
        "enabled": source.enabled,
        "authenticationMode": source.authentication_mode.value,
        "credentialConfigured": source.credential_configured,
    }


def _source_detail_body(source: MonitoringSource) -> dict[str, object]:
    return {
        **_directory_item(source),
        "endpointOrigin": _endpoint_origin(source.endpoint),
        "identityLabels": list(source.identity_labels),
        "selectorLabels": [
            {"name": label.name, "value": label.value}
            for label in source.selector_labels
        ],
        "scrapeIntervalSeconds": source.scrape_interval_seconds,
        "staleAfterSeconds": source.stale_after_seconds,
    }


def _endpoint_origin(endpoint: str) -> str:
    """Return only scheme/authority, never a path that might carry a token."""
    parts = urlsplit(endpoint)
    host = parts.hostname
    if host is None:
        raise MonitoringSourceRegistryUnavailable
    rendered_host = f"[{host}]" if ":" in host else host
    authority = rendered_host
    if parts.port is not None:
        authority = f"{authority}:{parts.port}"
    return urlunsplit((parts.scheme, authority, "", "", ""))


__all__ = ["monitoring_source_management_routes", "monitoring_source_read_routes"]
