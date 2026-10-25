"""mTLS transport for bounded Rule Publication Receipt V1 ingestion."""

from __future__ import annotations

from atlas_richie.contracts.rules.publication_receipt import PublicationReceiptError
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from ..application.ingest_rule_publication_receipt import (
    IngestRulePublicationReceipt,
)
from ..application.metrics_ingest_ports import VerifiedMetricsPeer
from ..application.publication_receipt_ingest_ports import (
    PublicationReceiptIngestError,
)
from ..application.publication_receipt_ingest_ports import (
    PublicationReceiptIngestErrorCode as ErrorCode,
)
from .reporting_transport import (
    ReportingPayloadTooLarge,
    has_json_content_type,
    read_bounded_body,
    reporting_error,
    verified_reporter_peer,
)

_PATH = "/api/reporting/v1/rule-publication-receipts"
_MAX_BODY_BYTES = 16 * 1024
_ERROR_STATUS = {
    ErrorCode.IDENTITY_NOT_ENROLLED: 401,
    ErrorCode.IDENTITY_REVOKED: 401,
    ErrorCode.INVALID_EPOCH: 409,
    ErrorCode.STALE_SEQUENCE: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.SCOPE_MISMATCH: 403,
    ErrorCode.PUBLICATION_NOT_FOUND: 404,
    ErrorCode.TARGET_MISMATCH: 409,
    ErrorCode.DIGEST_MISMATCH: 409,
    ErrorCode.STORAGE_UNAVAILABLE: 503,
}


def rule_publication_receipt_ingest_route(
    ingest: IngestRulePublicationReceipt | None,
) -> Route:
    """Create the HTTPS-only receipt endpoint; success means transaction commit."""

    async def accept_receipt(request: Request) -> Response:
        if ingest is None:
            return reporting_error("service_unavailable", 503)
        if not has_json_content_type(request):
            return reporting_error("invalid_content_type", 415)
        try:
            body = await read_bounded_body(request, _MAX_BODY_BYTES)
        except ReportingPayloadTooLarge:
            return reporting_error("payload_too_large", 413)
        except (ValueError, ClientDisconnect):
            return reporting_error("invalid_request", 400)

        try:
            await ingest.execute(_peer(request), body)
        except PublicationReceiptError as error:
            return reporting_error(error.code.value, 400)
        except PublicationReceiptIngestError as error:
            return reporting_error(error.code.value, _ERROR_STATUS[error.code])
        return Response(status_code=204, headers={"cache-control": "no-store"})

    return Route(_PATH, accept_receipt, methods=["POST"])


def _peer(request: Request) -> VerifiedMetricsPeer | None:
    """Keep the TLS extraction seam narrow and injectable in route contract tests."""
    return verified_reporter_peer(request)


__all__ = ["rule_publication_receipt_ingest_route"]
