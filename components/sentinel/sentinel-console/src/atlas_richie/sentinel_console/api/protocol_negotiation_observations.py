"""Authenticated, separately versioned per-worker protocol read contract."""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ..application.negotiate_agent_reporting import ProtocolNegotiationUnavailable
from ..application.read_agent_reporting_negotiations import (
    ReadAgentReportingNegotiations,
    ReadIncidentEventNegotiations,
)
from ..application.read_session import ReadSession
from ..domain.protocol_negotiations import ProtocolNegotiationPage
from .http_support import error_response
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)

_ALLOWED_QUERY_KEYS = frozenset({"page", "pageSize"})


def agent_reporting_observations_route(
    read_session: ReadSession,
    read_observations: ReadAgentReportingNegotiations | None,
) -> Route:
    """Expose each enrolled worker without altering Console API 0.5.0."""
    return _protocol_observations_route(
        "/api/v2/system/protocol-observations/agent-reporting",
        "agent-reporting",
        read_session,
        read_observations,
    )


def incident_event_observations_route(
    read_session: ReadSession,
    read_observations: ReadIncidentEventNegotiations | None,
) -> Route:
    """Expose Incident Event facts independently from Agent Reporting."""
    return _protocol_observations_route(
        "/api/v2/system/protocol-observations/incident-events",
        "incident-events",
        read_session,
        read_observations,
    )


def _protocol_observations_route(
    path: str,
    boundary: str,
    read_session: ReadSession,
    read_observations: ReadAgentReportingNegotiations
    | ReadIncidentEventNegotiations
    | None,
) -> Route:
    """Build the shared authenticated paging transport for one boundary."""

    async def read_page(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session
        )
        if rejection is not None:
            return rejection
        if read_observations is None:
            return error_response(request_id_value, "service_unavailable", 503)
        query_keys = set(request.query_params.keys())
        if query_keys - _ALLOWED_QUERY_KEYS or any(
            len(request.query_params.getlist(key)) != 1 for key in query_keys
        ):
            return error_response(request_id_value, "invalid_request", 400)
        try:
            page_value = _query_integer(request.query_params.get("page", "1"))
            page_size = _query_integer(request.query_params.get("pageSize", "20"))
        except ValueError:
            return error_response(request_id_value, "invalid_request", 400)
        try:
            snapshot = await read_observations.execute(
                page=page_value, page_size=page_size
            )
        except ValueError:
            return error_response(request_id_value, "invalid_request", 400)
        except ProtocolNegotiationUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return Response(
            _page_body(snapshot, boundary),
            status_code=200,
            media_type="application/json",
            headers=system_read_headers(request_id_value),
        )

    return Route(
        path,
        read_page,
        methods=["GET"],
    )


def _query_integer(value: str) -> int:
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        raise ValueError("invalid paging query")
    return int(value)


def _page_body(snapshot: ProtocolNegotiationPage, boundary: str) -> bytes:
    return json.dumps(
        {
            "asOf": utc_timestamp(snapshot.as_of),
            "page": snapshot.page,
            "pageSize": snapshot.page_size,
            "total": snapshot.total,
            "items": [
                {
                    "environmentId": item.environment_id,
                    "appId": item.app_id,
                    "instanceId": item.instance_id,
                    "processId": item.process_id,
                    "reporterId": item.reporter_id,
                    "boundary": boundary,
                    "collectorSupported": list(item.collector_supported),
                    "runtimeVersion": item.runtime_version,
                    "compatibility": item.compatibility.value,
                    "observedAt": (
                        utc_timestamp(item.observed_at)
                        if item.observed_at is not None
                        else None
                    ),
                }
                for item in snapshot.items
            ],
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")


__all__ = [
    "agent_reporting_observations_route",
    "incident_event_observations_route",
]
