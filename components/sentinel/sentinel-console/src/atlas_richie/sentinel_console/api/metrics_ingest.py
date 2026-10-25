"""ASGI transport boundary for mutually authenticated Metrics V2 snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from atlas_richie.contracts.reporting.v2 import (
    MetricsV2ProtocolError,
    encode_metrics_receipt,
)
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.ingest_metrics import MAX_METRICS_BODY_BYTES, IngestMetrics
from ..application.metrics_ingest_ports import (
    MetricsIngestError,
    MetricsIngestErrorCode,
)
from .reporting_transport import (
    ReportingPayloadTooLarge,
    has_json_content_type,
    read_bounded_body,
    reporting_error,
    verified_reporter_peer,
)

_SNAPSHOT_PATH = "/api/reporting/v2/snapshots"
_ERROR_STATUS: Mapping[MetricsIngestErrorCode, int] = {
    MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED: 401,
    MetricsIngestErrorCode.IDENTITY_REVOKED: 401,
    MetricsIngestErrorCode.IDENTITY_MISMATCH: 403,
    MetricsIngestErrorCode.IDEMPOTENCY_CONFLICT: 409,
    MetricsIngestErrorCode.STALE_SEQUENCE: 409,
    MetricsIngestErrorCode.INVALID_EPOCH: 409,
    MetricsIngestErrorCode.ELAPSED_TIME_REGRESSION: 409,
    MetricsIngestErrorCode.STORAGE_UNAVAILABLE: 503,
}


def metrics_ingest_route(ingest: IngestMetrics | None) -> Route:
    """Create the bounded, certificate-authenticated Metrics V2 ingest route."""

    async def accept_snapshot(request: Request) -> Response:
        if ingest is None:
            return _error("service_unavailable", 503)
        if not has_json_content_type(request):
            return _error("invalid_content_type", 415)
        try:
            body = await read_bounded_body(request, MAX_METRICS_BODY_BYTES)
        except ReportingPayloadTooLarge:
            return _error("payload_too_large", 413)
        except (ValueError, ClientDisconnect):
            return _error("invalid_request", 400)

        try:
            receipt = await ingest.execute(verified_reporter_peer(request), body)
        except MetricsV2ProtocolError as error:
            status = 413 if error.code == "payload_too_large" else 400
            return _error(error.code.value, status)
        except MetricsIngestError as error:
            return _error(error.code.value, _ERROR_STATUS[error.code])

        return Response(
            encode_metrics_receipt(receipt),
            status_code=200,
            media_type="application/json",
            headers={"cache-control": "no-store"},
        )

    return Route(_SNAPSHOT_PATH, accept_snapshot, methods=["POST"])


def _error(code: str, status: int) -> JSONResponse:
    return reporting_error(code, status)


__all__ = ["metrics_ingest_route"]
