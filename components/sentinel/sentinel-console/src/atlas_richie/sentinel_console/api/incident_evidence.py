"""Authenticated endpoint for one explicit incident's read-only evidence."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.incident_evidence_ports import (
    IncidentEvidenceAuthorityUnavailable,
    IncidentEvidenceNotFound,
    IncidentEvidenceRateLimited,
)
from ..application.read_incident_evidence import ReadIncidentEvidence
from ..application.read_session import ReadSession
from ..domain.session import SessionCapability
from .http_support import error_response
from .incident_query_parsing import parse_incident_detail_query
from .incident_serializers import incident_evidence_body
from .system_observation_access import authorize_system_read, system_read_headers


def incident_evidence_route(
    read_session: ReadSession,
    read_evidence: ReadIncidentEvidence | None,
) -> Route:
    """Create the metrics:view evidence endpoint with non-disclosing 404s."""

    async def read_detail(request: Request) -> Response:
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
        event_id = request.path_params["incident_id"]
        try:
            query = parse_incident_detail_query(request, event_id)
        except ValueError:
            return error_response(request_id_value, "invalid_request", 400)
        if read_evidence is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            evidence = await read_evidence.execute(query)
        except IncidentEvidenceNotFound:
            return error_response(request_id_value, "not_found", 404)
        except IncidentEvidenceRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (IncidentEvidenceAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            incident_evidence_body(evidence),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/incidents/{incident_id}/evidence", read_detail, methods=["GET"]
    )
