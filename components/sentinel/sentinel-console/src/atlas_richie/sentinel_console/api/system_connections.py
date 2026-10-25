"""Authenticated read endpoint for server-probed connection facts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_session import ReadSession
from ..application.read_system_connections import ReadSystemConnections
from ..application.system_connections_ports import (
    SystemConnectionsAuthorityUnavailable,
)
from ..domain.system_connections import SystemConnectionsSnapshot
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)


def system_connections_route(
    read_session: ReadSession,
    read_connections: ReadSystemConnections | None,
) -> Route:
    """Create a session-protected route for all three connection categories."""

    async def read_snapshot(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        if read_connections is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_connections.execute()
        except SystemConnectionsAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _snapshot_body(snapshot), headers=system_read_headers(request_id_value)
        )

    return Route("/api/v1/system/connections", read_snapshot, methods=["GET"])


def _snapshot_body(snapshot: SystemConnectionsSnapshot) -> dict[str, object]:
    return {
        "asOf": utc_timestamp(snapshot.as_of),
        "items": [
            {
                "id": item.id,
                "kind": item.kind.value,
                "sourceId": item.source_id,
                "provider": item.provider.value if item.provider is not None else None,
                "state": item.state.value,
                "checkedAt": (
                    utc_timestamp(item.checked_at)
                    if item.checked_at is not None
                    else None
                ),
                "expiresAt": (
                    utc_timestamp(item.expires_at)
                    if item.expires_at is not None
                    else None
                ),
                "latencyMs": item.latency_ms,
                "capabilities": [capability.value for capability in item.capabilities],
                "reason": item.reason.value if item.reason is not None else None,
            }
            for item in snapshot.items
        ],
    }
