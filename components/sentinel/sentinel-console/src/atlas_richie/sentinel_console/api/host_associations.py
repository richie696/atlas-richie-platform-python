"""Authenticated API for explicit host-to-worker mappings."""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.host_associations import HostAssociationStore, ReadHostAssociations
from ..application.monitoring_probe import MonitoringCredentialReferenceResolver
from ..application.monitoring_source_registry import (
    MonitoringSourceNotFound,
    MonitoringSourceRegistryPort,
    MonitoringSourceRegistryUnavailable,
)
from ..application.read_host_metrics import (
    HostMetricsQueryPort,
    HostMetricsQueryUnavailable,
    ReadHostMetrics,
)
from ..application.read_session import ReadSession
from ..domain.host_associations import (
    HostAssociationConflict,
    HostAssociationIdempotencyConflict,
    HostAssociationNotFound,
    HostAssociationUnavailable,
    HostInstanceAssociation,
)
from ..domain.host_metrics import HostMetricQuality, HostMetricsQuery
from ..domain.session import AccountRole
from .admin_write_access import authorize_admin_write
from .browser_origin import normalize_browser_origin
from .browser_security import browser_session_digest
from .http_support import error_response, read_json_object
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)

_MAX_BODY_BYTES = 4096
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def host_association_routes(
    read_session: ReadSession,
    store: HostAssociationStore | None,
    allowed_browser_origins: Collection[str],
    source_registry: MonitoringSourceRegistryPort | None,
    host_metrics_query: HostMetricsQueryPort | None,
    credential_reference_resolver: MonitoringCredentialReferenceResolver | None,
) -> tuple[Route, Route, Route, Route]:
    """Build viewer reads and CSRF-protected administrator mutations."""
    origins = frozenset(
        normalize_browser_origin(item) for item in allowed_browser_origins
    )
    if not origins:
        raise ValueError("at least one browser origin must be configured")

    async def read(request: Request) -> Response:
        request_id, identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if store is None:
            return error_response(request_id, "service_unavailable", 503)
        if set(request.query_params.keys()) - {
            "environmentId",
            "sourceId",
            "appId",
            "instanceId",
            "page",
            "pageSize",
        }:
            return error_response(request_id, "invalid_request", 400)
        if any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            return error_response(request_id, "invalid_request", 400)
        environment_id = request.query_params.get("environmentId", "")
        source_id = request.query_params.get("sourceId")
        app_id = request.query_params.get("appId")
        instance_id = request.query_params.get("instanceId")
        page = _positive_int(request.query_params.get("page", "1"), maximum=10_000)
        page_size = _positive_int(
            request.query_params.get("pageSize", "100"), maximum=100
        )
        if (
            not _valid(environment_id, 200)
            or (source_id is not None and not _valid(source_id, 200))
            or (app_id is not None and not _valid(app_id, 200))
            or (instance_id is not None and not _valid(instance_id, 200))
            or (instance_id is not None and app_id is None)
            or page is None
            or page_size is None
        ):
            return error_response(request_id, "invalid_request", 400)
        try:
            directory = await ReadHostAssociations(store).execute(
                environment_id,
                source_id=source_id,
                app_id=app_id,
                instance_id=instance_id,
                page=page,
                page_size=page_size,
            )
        except HostAssociationUnavailable:
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(
            {
                "environmentId": environment_id,
                "asOf": utc_timestamp(datetime.now(UTC)),
                "page": directory.page,
                "pageSize": directory.page_size,
                "total": directory.total,
                "associatedHostIds": list(directory.associated_host_ids),
                "hostIdsComplete": directory.host_ids_complete,
                "items": [_association_body(item) for item in directory.items],
            },
            headers=system_read_headers(request_id),
        )

    async def put(request: Request) -> Response:
        access, rejection = await authorize_admin_write(request, read_session, origins)
        if rejection is not None:
            return rejection
        assert access is not None
        body = await read_json_object(request, _MAX_BODY_BYTES)
        fields = {
            "requestKey",
            "environmentId",
            "sourceId",
            "hostId",
            "appId",
            "instanceId",
            "expectedRevision",
        }
        if (
            body is None
            or set(body) != fields
            or not _valid_request_key(body.get("requestKey"))
            or not all(
                _valid(body.get(name), limit)
                for name, limit in {
                    "environmentId": 200,
                    "sourceId": 200,
                    "hostId": 512,
                    "appId": 200,
                    "instanceId": 200,
                }.items()
            )
            or (
                body.get("expectedRevision") is not None
                and not _valid(body.get("expectedRevision"), 36)
            )
        ):
            return error_response(access.request_id, "validation_failed", 422)
        idempotency_keys = request.headers.getlist("idempotency-key")
        if idempotency_keys != [body["requestKey"]]:
            return error_response(access.request_id, "validation_failed", 422)
        if store is None:
            return error_response(access.request_id, "service_unavailable", 503)
        command_fingerprint_payload = {
            key: body[key]
            for key in (
                "sourceId",
                "environmentId",
                "hostId",
                "appId",
                "instanceId",
                "expectedRevision",
            )
        }
        try:
            replay = await store.resolve_host_association_replay(
                body["requestKey"],
                actor_id=access.identity.account_id,
                session_digest=access.session_digest,
                kind="put",
                command=command_fingerprint_payload,
            )
        except HostAssociationIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except HostAssociationUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        if replay is not None:
            return JSONResponse(replay, headers=system_read_headers(access.request_id))
        if source_registry is None or host_metrics_query is None:
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            source = await source_registry.read_monitoring_source(body["sourceId"])
            if source.environment_id != body["environmentId"] or not source.enabled:
                return error_response(access.request_id, "not_found", 404)
            now = datetime.now(UTC)
            step_ms = source.scrape_interval_seconds * 1000
            host_snapshot = await ReadHostMetrics(
                source_registry,
                host_metrics_query,
                credential_reference_resolver,
            ).execute(
                body["sourceId"],
                HostMetricsQuery(
                    start_at=now - timedelta(milliseconds=step_ms * 3),
                    end_at=now,
                    step_ms=step_ms,
                ),
            )
        except MonitoringSourceNotFound:
            return error_response(access.request_id, "not_found", 404)
        except (MonitoringSourceRegistryUnavailable, HostMetricsQueryUnavailable):
            return error_response(access.request_id, "service_unavailable", 503)
        if host_snapshot.quality is HostMetricQuality.UNAVAILABLE:
            return error_response(access.request_id, "service_unavailable", 503)
        if not any(
            host.identity.host_id == body["hostId"] for host in host_snapshot.hosts
        ):
            return error_response(access.request_id, "not_found", 404)
        try:
            item = await store.put_host_association(
                source_id=body["sourceId"],
                environment_id=body["environmentId"],
                host_id=body["hostId"],
                app_id=body["appId"],
                instance_id=body["instanceId"],
                expected_revision=body["expectedRevision"],
                request_key=body["requestKey"],
                actor_id=access.identity.account_id,
                session_digest=access.session_digest,
                request_id=access.request_id,
                now=datetime.now(UTC),
            )
        except HostAssociationNotFound:
            return error_response(access.request_id, "not_found", 404)
        except HostAssociationConflict:
            return error_response(access.request_id, "conflict", 409)
        except HostAssociationIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except HostAssociationUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        return JSONResponse(
            item, status_code=200, headers=system_read_headers(access.request_id)
        )

    async def remove(request: Request) -> Response:
        access, rejection = await authorize_admin_write(request, read_session, origins)
        if rejection is not None:
            return rejection
        assert access is not None
        body = await read_json_object(request, _MAX_BODY_BYTES)
        fields = {
            "requestKey",
            "environmentId",
            "appId",
            "instanceId",
            "expectedRevision",
        }
        if (
            body is None
            or set(body) != fields
            or not _valid_request_key(body.get("requestKey"))
            or not all(
                _valid(body.get(name), 200)
                for name in ("environmentId", "appId", "instanceId")
            )
            or not _valid(body.get("expectedRevision"), 36)
        ):
            return error_response(access.request_id, "validation_failed", 422)
        idempotency_keys = request.headers.getlist("idempotency-key")
        if idempotency_keys != [body["requestKey"]]:
            return error_response(access.request_id, "validation_failed", 422)
        if store is None:
            return error_response(access.request_id, "service_unavailable", 503)
        try:
            removed = await store.delete_host_association(
                environment_id=body["environmentId"],
                app_id=body["appId"],
                instance_id=body["instanceId"],
                expected_revision=body["expectedRevision"],
                request_key=body["requestKey"],
                actor_id=access.identity.account_id,
                session_digest=access.session_digest,
                request_id=access.request_id,
                now=datetime.now(UTC),
            )
        except HostAssociationConflict:
            return error_response(access.request_id, "conflict", 409)
        except HostAssociationIdempotencyConflict:
            return error_response(access.request_id, "idempotency_conflict", 409)
        except HostAssociationUnavailable:
            return error_response(access.request_id, "service_unavailable", 503)
        if removed is None:
            return error_response(access.request_id, "not_found", 404)
        return JSONResponse(removed, headers=system_read_headers(access.request_id))

    async def read_operation(request: Request) -> Response:
        request_id, identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id, "forbidden", 403)
        if store is None:
            return error_response(request_id, "service_unavailable", 503)
        request_key = request.path_params.get("requestKey", "")
        if not _valid_request_key(request_key):
            return error_response(request_id, "not_found", 404)
        session_digest, failure = browser_session_digest(request)
        if failure is not None:
            return error_response(request_id, failure[0], failure[1])
        assert session_digest is not None
        try:
            result = await store.read_host_association_operation(
                request_key,
                actor_id=identity.account_id,
                session_digest=session_digest,
            )
        except HostAssociationIdempotencyConflict:
            return error_response(request_id, "not_found", 404)
        except HostAssociationUnavailable:
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(
            {"status": "not_found", "requestKey": request_key}
            if result is None
            else {"status": "completed", "requestKey": request_key, "result": result},
            headers=system_read_headers(request_id),
        )

    return (
        Route("/api/v2/monitoring/host-associations", read, methods=["GET"]),
        Route("/api/v2/monitoring/host-associations", put, methods=["PUT"]),
        Route("/api/v2/monitoring/host-associations", remove, methods=["DELETE"]),
        Route(
            "/api/v2/monitoring/host-associations/operations/{requestKey:str}",
            read_operation,
            methods=["GET"],
        ),
    )


def _association_body(item: HostInstanceAssociation) -> dict[str, object]:
    return {
        "sourceId": item.source_id,
        "environmentId": item.environment_id,
        "hostId": item.host_id,
        "appId": item.app_id,
        "instanceId": item.instance_id,
        "processId": item.process_id,
        "revision": item.revision,
        "provenance": "operator_confirmed",
        "currentEpoch": item.current_epoch,
        "lastReceivedAt": (
            utc_timestamp(item.last_received_at) if item.last_received_at else None
        ),
        "reporterActive": item.reporter_active,
        "createdAt": utc_timestamp(item.created_at),
    }


def _valid(value: object, limit: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= limit
        and value.strip() == value
        and not any(ord(character) < 32 for character in value)
    )


def _valid_request_key(value: object) -> bool:
    return isinstance(value, str) and _REQUEST_KEY.fullmatch(value) is not None


def _positive_int(value: str, *, maximum: int) -> int | None:
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        return None
    parsed = int(value)
    return parsed if 1 <= parsed <= maximum else None


__all__ = ["host_association_routes"]
