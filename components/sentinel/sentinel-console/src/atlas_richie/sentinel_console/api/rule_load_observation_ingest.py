"""mTLS transport for bounded Rule Load Observation V1 ingestion."""

from __future__ import annotations

from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleLoadObservationError,
)
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from ..application.ingest_rule_load_observation import (
    MAX_RULE_LOAD_OBSERVATION_BYTES,
    IngestRuleLoadObservation,
)
from ..application.rule_load_observation_ingest_ports import (
    RuleLoadObservationIngestError,
)
from .reporting_transport import (
    ReportingPayloadTooLarge,
    has_json_content_type,
    read_bounded_body,
    reporting_error,
    verified_reporter_peer,
)

_PATH = "/api/reporting/v1/rule-load-observations"
_ERROR_STATUS = {
    "identity_not_enrolled": 401,
    "identity_revoked": 401,
    "invalid_epoch": 409,
    "stale_sequence": 409,
    "idempotency_conflict": 409,
    "scope_mismatch": 403,
    "binding_not_found": 404,
    "profile_mismatch": 409,
    "storage_unavailable": 503,
}


def rule_load_observation_ingest_route(
    ingest: IngestRuleLoadObservation | None,
) -> Route:
    """Return 204 only after the Collector's durable inbox/outbox commit."""

    async def accept(request: Request) -> Response:
        if ingest is None:
            return reporting_error("service_unavailable", 503)
        if not has_json_content_type(request):
            return reporting_error("invalid_content_type", 415)
        try:
            body = await read_bounded_body(request, MAX_RULE_LOAD_OBSERVATION_BYTES)
        except ReportingPayloadTooLarge:
            return reporting_error("payload_too_large", 413)
        except (ValueError, ClientDisconnect):
            return reporting_error("invalid_request", 400)
        try:
            await ingest.execute(verified_reporter_peer(request), body)
        except RuleLoadObservationError as error:
            status = 413 if error.code.value == "body_size" else 400
            return reporting_error(error.code.value, status)
        except RuleLoadObservationIngestError as error:
            return reporting_error(error.code.value, _ERROR_STATUS[error.code.value])
        return Response(status_code=204, headers={"cache-control": "no-store"})

    return Route(_PATH, accept, methods=["POST"])


__all__ = ["rule_load_observation_ingest_route"]
