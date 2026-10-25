"""Authenticated read endpoint for observation environment/application facts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_observation_catalog import ReadObservationCatalog
from ..application.read_session import ReadSession
from ..application.observation_catalog_ports import (
    ObservationCatalogAuthorityUnavailable,
)
from ..domain.observation_catalog import ObservationCatalogSnapshot
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)


def observation_catalog_route(
    read_session: ReadSession,
    read_catalog: ReadObservationCatalog | None,
) -> Route:
    """Create the authenticated catalog route for admin and viewer roles."""

    async def read_snapshot(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        if read_catalog is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_catalog.execute()
        except ObservationCatalogAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _snapshot_body(snapshot),
            headers=system_read_headers(request_id_value),
        )

    return Route("/api/v1/observation/catalog", read_snapshot, methods=["GET"])


def _snapshot_body(snapshot: ObservationCatalogSnapshot) -> dict[str, object]:
    return {
        "asOf": utc_timestamp(snapshot.as_of),
        "environments": [
            {"id": item.id, "name": item.name} for item in snapshot.environments
        ],
        "applications": [
            {
                "id": item.id,
                "environmentId": item.environment_id,
                "name": item.name,
            }
            for item in snapshot.applications
        ],
    }
