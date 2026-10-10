"""Authenticated read endpoint for filtered incident timeline pages."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.incident_timeline_ports import (
    IncidentTimelineAuthorityUnavailable,
    IncidentTimelineRateLimited,
    IncidentTimelineTargetNotFound,
)
from ..application.read_incident_timeline import ReadIncidentTimeline
from ..application.read_session import ReadSession
from ..domain.session import SessionCapability
from .http_support import error_response
from .incident_query_parsing import parse_incident_timeline_query
from .incident_serializers import incident_page_body
from .system_observation_access import authorize_system_read, system_read_headers

def incidents_route(
    read_session: ReadSession,
    read_timeline: ReadIncidentTimeline | None,
) -> Route:
    """Create the metrics:view timeline endpoint with bounded query parsing."""

    async def read_page(request: Request) -> Response:
        request_id_value, identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection
        if (
            identity is None
            or SessionCapability.METRICS_VIEW not in identity.capabilities
        ):
            return error_response(request_id_value, "forbidden", 403)
        try:
            query = parse_incident_timeline_query(request)
        except ValueError:
            return error_response(request_id_value, "invalid_request", 400)
        if read_timeline is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            page = await read_timeline.execute(query)
        except IncidentTimelineTargetNotFound:
            return error_response(request_id_value, "not_found", 404)
        except IncidentTimelineRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (IncidentTimelineAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            incident_page_body(page), headers=system_read_headers(request_id_value)
        )

    return Route("/api/v1/incidents", read_page, methods=["GET"])
