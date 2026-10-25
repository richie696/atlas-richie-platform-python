"""Authenticated API adapters for monitoring-source candidate checks."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.check_monitoring_source import (
    CheckMonitoringSource,
    CheckMonitoringSourceInput,
    MonitoringProbeReceiptAuthorityUnavailable,
    MonitoringProbeReceiptReader,
    MonitoringSourceCheckReceipt,
)
from ..application.errors import SessionAuthorityUnavailable
from ..application.monitoring_probe import (
    MonitoringCredentialReferenceResolver,
    MonitoringCredentialReferenceUnavailable,
    MonitoringIdentityPreview,
    MonitoringProbeCredentials,
    MonitoringProbeResult,
)
from ..application.read_session import ReadSession
from ..domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from ..domain.session import AccountRole
from .admin_write_access import authorize_admin_write
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_session_digest
from .http_support import error_response, read_json_object, request_id
from .system_observation_access import system_read_headers, utc_timestamp

_MAX_BODY_BYTES = 16 * 1024


def monitoring_source_check_routes(
    read_session: ReadSession,
    check_source: CheckMonitoringSource | None,
    receipt_reader: MonitoringProbeReceiptReader | None,
    allowed_browser_origins: Collection[str],
    credential_reference_resolver: MonitoringCredentialReferenceResolver | None = None,
) -> tuple[Route, Route]:
    """Build an admin-only candidate probe and an exact-session receipt read."""
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
        body = await read_json_object(request, _MAX_BODY_BYTES)
        parsed = _parse_candidate(body)
        if parsed is None:
            return error_response(access.request_id, "validation_failed", 422)
        command, reference = parsed
        if reference is not None:
            if credential_reference_resolver is None:
                return error_response(access.request_id, "service_unavailable", 503)
            try:
                credentials = await credential_reference_resolver.resolve(reference)
            except MonitoringCredentialReferenceUnavailable:
                return error_response(access.request_id, "service_unavailable", 503)
            if credentials is None:
                return error_response(access.request_id, "validation_failed", 422)
            command = CheckMonitoringSourceInput(command.source, credentials, reference)
        if check_source is None:
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            receipt = await check_source.execute(
                command,
                actor_id=access.identity.account_id,
                session_digest=access.session_digest,
            )
        except ValueError:
            return error_response(access.request_id, "validation_failed", 422)
        except MonitoringProbeReceiptAuthorityUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            _receipt_body(receipt),
            headers=system_read_headers(access.request_id),
        )

    async def read_receipt(request: Request) -> Response:
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
        if receipt_reader is None:
            return error_response(request_id_value, "service_unavailable", 503)
        check_id = request.path_params.get("checkId", "")
        try:
            UUID(check_id)
        except (TypeError, ValueError):
            return error_response(request_id_value, "invalid_request", 400)
        try:
            receipt = await receipt_reader.read_monitoring_probe_receipt(
                check_id,
                actor_id=identity.account_id,
                session_digest=session_digest,
                now=datetime.now(UTC),
            )
        except MonitoringProbeReceiptAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if receipt is None:
            return error_response(request_id_value, "not_found", 404)
        return JSONResponse(
            _receipt_body(receipt),
            headers=system_read_headers(request_id_value),
        )

    return (
        Route(
            "/api/v2/monitoring/sources/check",
            check,
            methods=["POST"],
        ),
        Route(
            "/api/v2/monitoring/sources/checks/{checkId:str}",
            read_receipt,
            methods=["GET"],
        ),
    )


def _parse_candidate(
    body: dict[str, object] | None,
) -> tuple[CheckMonitoringSourceInput, str | None] | None:
    if body is None or set(body) != {"source", "credentials"}:
        return None
    raw = body["source"]
    if not isinstance(raw, dict):
        return None
    expected = {
        "sourceId",
        "revision",
        "displayName",
        "environmentId",
        "endpoint",
        "provider",
        "profile",
        "authenticationMode",
        "credentialConfigured",
        "enabled",
        "identityLabels",
        "selectorLabels",
        "scrapeIntervalSeconds",
        "staleAfterSeconds",
    }
    if set(raw) != expected:
        return None
    try:
        source = MonitoringSource(
            source_id=raw["sourceId"],
            revision=raw["revision"],
            display_name=raw["displayName"],
            environment_id=raw["environmentId"],
            endpoint=raw["endpoint"],
            provider=MonitoringProvider(raw["provider"]),
            profile=MonitoringProfile(raw["profile"]),
            authentication_mode=MonitoringAuthenticationMode(raw["authenticationMode"]),
            credential_configured=raw["credentialConfigured"],
            enabled=raw["enabled"],
            identity_labels=tuple(raw["identityLabels"]),
            selector_labels=tuple(
                MonitoringLabel(item["name"], item["value"])
                for item in raw["selectorLabels"]
            ),
            scrape_interval_seconds=raw["scrapeIntervalSeconds"],
            stale_after_seconds=raw["staleAfterSeconds"],
        )
        credentials, reference = _parse_credentials(
            raw["authenticationMode"], body["credentials"]
        )
        return CheckMonitoringSourceInput(source, credentials), reference
    except (KeyError, TypeError, ValueError):
        return None


def _parse_credentials(
    mode: object, raw: object
) -> tuple[MonitoringProbeCredentials | None, str | None]:
    if mode == MonitoringAuthenticationMode.NONE.value:
        return (None, None) if raw is None else _invalid_credentials()
    if not isinstance(raw, dict):
        return _invalid_credentials()
    if mode == MonitoringAuthenticationMode.DIRECT_BASIC.value and set(raw) == {
        "username",
        "password",
    }:
        return MonitoringProbeCredentials(raw["username"], raw["password"]), None
    if mode == MonitoringAuthenticationMode.DIRECT_BEARER.value and set(raw) == {
        "bearerToken"
    }:
        return MonitoringProbeCredentials(bearer_token=raw["bearerToken"]), None
    if (
        mode == MonitoringAuthenticationMode.CREDENTIAL_REFERENCE.value
        and set(raw) == {"reference"}
        and isinstance(raw["reference"], str)
        and 1 <= len(raw["reference"]) <= 256
        and not any(char in raw["reference"] for char in "\r\n\x00")
    ):
        return None, raw["reference"]
    return _invalid_credentials()


def _invalid_credentials() -> None:
    raise ValueError("monitoring credentials do not match the selected mode")


def _receipt_body(receipt: MonitoringSourceCheckReceipt) -> dict[str, object]:
    result: MonitoringProbeResult = receipt.result
    identity: MonitoringIdentityPreview = result.identity
    return {
        "checkId": receipt.check_id,
        "sourceId": receipt.source_id,
        "sourceRevision": receipt.source_revision,
        "checkedAt": utc_timestamp(receipt.checked_at),
        "expiresAt": utc_timestamp(receipt.expires_at),
        "candidateFingerprint": receipt.candidate_fingerprint,
        "result": {
            "connection": result.connection.value,
            "queryApi": result.query_api.value,
            "profile": result.profile.value,
            "identity": {
                "observed": identity.observed,
                "unique": identity.unique,
                "missing": identity.missing,
                "conflicting": identity.conflicting,
            },
            "failure": result.failure.value if result.failure else None,
        },
    }


__all__ = ["monitoring_source_check_routes"]
