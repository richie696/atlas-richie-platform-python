"""mTLS-only transport for independently scoped protocol hello/accept exchanges."""

from __future__ import annotations

import json

from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from ..application.negotiate_agent_reporting import (
    NegotiateAgentReporting,
    ProtocolNegotiationIdentityUnavailable,
    ProtocolNegotiationUnavailable,
)
from ..application.negotiate_incident_events import NegotiateIncidentEvents
from ..application.negotiate_rule_load_observation import (
    NegotiateRuleLoadObservation,
)
from ..domain.protocol_negotiations import MAX_PROTOCOL_VERSION_LENGTH
from .reporting_transport import (
    ReportingPayloadTooLarge,
    has_json_content_type,
    read_bounded_body,
    reporting_error,
    verified_reporter_peer,
)

_MAX_NEGOTIATION_BODY_BYTES = 1024
_NEGOTIATION_PATH = "/api/reporting/v1/protocol-negotiations/agent"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _runtime_version(body: bytes) -> str:
    try:
        decoded = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("invalid negotiation request") from None
    if (
        not isinstance(decoded, dict)
        or set(decoded) != {"protocol_version"}
        or not isinstance(decoded["protocol_version"], str)
        or not decoded["protocol_version"]
        or len(decoded["protocol_version"]) > MAX_PROTOCOL_VERSION_LENGTH
        or not decoded["protocol_version"].isascii()
        or any(
            ord(character) < 0x21 or ord(character) > 0x7E
            for character in decoded["protocol_version"]
        )
    ):
        raise ValueError("invalid negotiation request")
    return decoded["protocol_version"]


def agent_reporting_negotiation_route(
    negotiate: NegotiateAgentReporting | None,
) -> Route:
    """Accept Agent Reporting's active version over an enrolled mTLS identity."""
    return _negotiation_route(
        _NEGOTIATION_PATH,
        "agent-reporting",
        negotiate,
    )


def incident_event_negotiation_route(
    negotiate: NegotiateIncidentEvents | None,
) -> Route:
    """Negotiate the independent Incident Event protocol over enrolled mTLS."""
    return _negotiation_route(
        "/api/reporting/v1/protocol-negotiations/incident-events",
        "incident-events",
        negotiate,
    )


def rule_load_observation_negotiation_route(
    negotiate: NegotiateRuleLoadObservation | None,
) -> Route:
    """Negotiate only Rule Load Observation over the enrolled mTLS identity."""
    return _negotiation_route(
        "/api/reporting/v1/protocol-negotiations/rule-load-observation",
        "rule-load-observation",
        negotiate,
    )


def _negotiation_route(
    path: str,
    boundary: str,
    negotiate: (
        NegotiateAgentReporting
        | NegotiateIncidentEvents
        | NegotiateRuleLoadObservation
        | None
    ),
) -> Route:
    """Share strict hello parsing and response semantics across protocol facts."""

    async def accept(request: Request) -> Response:
        if negotiate is None:
            return reporting_error("service_unavailable", 503)
        peer = verified_reporter_peer(request)
        if peer is None:
            return reporting_error("identity_not_enrolled", 401)
        if not has_json_content_type(request):
            return reporting_error("invalid_content_type", 415)
        try:
            body = await read_bounded_body(request, _MAX_NEGOTIATION_BODY_BYTES)
            runtime_version = _runtime_version(body)
        except ReportingPayloadTooLarge:
            return reporting_error("payload_too_large", 413)
        except (ValueError, ClientDisconnect):
            return reporting_error("invalid_request", 400)
        try:
            observation = await negotiate.execute(peer, runtime_version)
        except ProtocolNegotiationIdentityUnavailable:
            return reporting_error("identity_not_enrolled", 401)
        except ProtocolNegotiationUnavailable:
            return reporting_error("service_unavailable", 503)
        body = json.dumps(
            {
                "protocol_version": "atlas-richie.protocol-negotiation/v1",
                "boundary": boundary,
                "runtime_version": observation.runtime_version,
                "collector_supported": list(observation.collector_supported),
                "compatibility": observation.compatibility.value,
                "observed_at": observation.observed_at.isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z"),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return Response(
            body,
            status_code=200,
            media_type="application/json",
            headers={"cache-control": "no-store"},
        )

    return Route(path, accept, methods=["POST"])


__all__ = [
    "agent_reporting_negotiation_route",
    "incident_event_negotiation_route",
    "rule_load_observation_negotiation_route",
]
