"""Authenticated read endpoint for deployment protocol facts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_session import ReadSession
from ..application.read_system_protocols import ReadSystemProtocols
from ..application.system_protocols_ports import SystemProtocolsAuthorityUnavailable
from ..domain.system_protocols import SystemProtocolsSnapshot
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)


def system_protocols_route(
    read_session: ReadSession,
    read_protocols: ReadSystemProtocols | None,
) -> Route:
    """Create an authenticated route; any signed-in role may inspect protocols."""

    async def read_snapshot(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        if read_protocols is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_protocols.execute()
        except SystemProtocolsAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _snapshot_body(snapshot),
            headers=system_read_headers(request_id_value),
        )

    return Route("/api/v1/system/protocols", read_snapshot, methods=["GET"])


def _snapshot_body(snapshot: SystemProtocolsSnapshot) -> dict[str, object]:
    return {
        "asOf": utc_timestamp(snapshot.as_of),
        "items": [
            {
                "kind": item.kind.value,
                "supported": list(item.supported),
                "active": item.active,
                "compatibility": item.compatibility.value,
                "observedAt": (
                    utc_timestamp(item.observed_at)
                    if item.observed_at is not None
                    else None
                ),
            }
            for item in snapshot.items
        ],
    }
