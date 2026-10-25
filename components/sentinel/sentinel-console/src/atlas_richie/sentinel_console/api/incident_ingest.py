"""ASGI transport for authenticated Incident Event V1 reports."""

from __future__ import annotations

from atlas_richie.contracts.incidents.v1 import (
    IncidentProtocolError,
    encode_incident_receipt,
)
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from ..application.incident_ingest_ports import (
    IncidentIngestError,
    IncidentIngestErrorCode,
)
from ..application.ingest_incident_event import (
    MAX_INCIDENT_EVENT_BODY_BYTES,
    IngestIncidentEvent,
)
from .reporting_transport import (
    ReportingPayloadTooLarge,
    has_json_content_type,
    read_bounded_body,
    reporting_error,
    verified_reporter_peer,
)

_INCIDENT_PATH = "/api/reporting/v1/incidents"
_ERROR_STATUS = {
    IncidentIngestErrorCode.IDENTITY_NOT_ENROLLED: 401,
    IncidentIngestErrorCode.IDENTITY_MISMATCH: 409,
    IncidentIngestErrorCode.IDEMPOTENCY_CONFLICT: 409,
    IncidentIngestErrorCode.STORAGE_UNAVAILABLE: 503,
}


def incident_ingest_route(ingest: IngestIncidentEvent | None) -> Route:
    """Create the mTLS-only, bounded Incident Event V1 collector route."""

    async def accept_event(request: Request) -> Response:
        if ingest is None:
            return reporting_error("service_unavailable", 503)
        if not has_json_content_type(request):
            return reporting_error("invalid_content_type", 415)
        try:
            body = await read_bounded_body(request, MAX_INCIDENT_EVENT_BODY_BYTES)
        except ReportingPayloadTooLarge:
            return reporting_error("payload_too_large", 413)
        except (ValueError, ClientDisconnect):
            return reporting_error("invalid_request", 400)

        try:
            receipt = await ingest.execute(verified_reporter_peer(request), body)
        except IncidentProtocolError as error:
            status = 413 if error.code.value == "payload_too_large" else 400
            return reporting_error(error.code.value, status)
        except IncidentIngestError as error:
            return reporting_error(error.code.value, _ERROR_STATUS[error.code])

        return Response(
            encode_incident_receipt(receipt),
            status_code=200,
            media_type="application/json",
            headers={"cache-control": "no-store"},
        )

    return Route(_INCIDENT_PATH, accept_event, methods=["POST"])


__all__ = ["incident_ingest_route"]
