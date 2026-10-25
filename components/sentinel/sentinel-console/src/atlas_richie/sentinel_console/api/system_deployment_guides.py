"""Authenticated, read-only deployment guide catalog endpoint."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.deployment_guides import (
    DeploymentGuidesAuthorityUnavailable,
    DeploymentGuidesReader,
    ReadDeploymentGuides,
)
from ..application.read_session import ReadSession
from .http_support import error_response
from .system_observation_access import authorize_system_read, system_read_headers


def system_deployment_guides_route(
    read_session: ReadSession,
    reader: DeploymentGuidesReader | None,
) -> Route:
    """Build the admin/view route; no request-derived host becomes an endpoint."""

    async def read_catalog(request: Request) -> Response:
        request_id, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        if reader is None:
            return error_response(request_id, "service_unavailable", 503)
        try:
            snapshot = await ReadDeploymentGuides(reader).execute()
        except DeploymentGuidesAuthorityUnavailable:
            return error_response(request_id, "service_unavailable", 503)
        return JSONResponse(
            {
                "catalogRevision": snapshot.catalog_revision,
                "runtimeCollector": {
                    "state": (
                        "configured"
                        if snapshot.runtime_collector_endpoint is not None
                        else "not_configured"
                    ),
                    "endpoint": snapshot.runtime_collector_endpoint,
                },
                "paths": [
                    {
                        "id": path.guide_id,
                        "readiness": path.readiness,
                        "profileRevision": path.profile_revision,
                    }
                    for path in snapshot.paths
                ],
            },
            headers=system_read_headers(request_id),
        )

    return Route(
        "/api/v1/system/deployment-guides", read_catalog, methods=["GET"]
    )


__all__ = ["system_deployment_guides_route"]
