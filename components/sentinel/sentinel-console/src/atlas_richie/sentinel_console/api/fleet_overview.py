"""Authenticated fleet overview endpoint with strict query identity parsing."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.fleet_overview_ports import (
    FleetOverviewAuthorityUnavailable,
    FleetOverviewRateLimited,
    FleetOverviewTargetNotFound,
)
from ..application.read_fleet_overview import ReadFleetOverview
from ..application.read_session import ReadSession
from ..domain.fleet_overview import FleetQuery
from ..domain.instance_catalog import ObservationScope, ObservationWindow
from ..domain.instance_observation import ObservationContext
from ..domain.session import SessionCapability
from .fleet_serializers import fleet_snapshot_body
from .http_support import error_response
from .query_parsing import (
    MAX_QUERY_PAGE_NUMBER,
    MAX_QUERY_PAGE_SIZE,
    MAX_QUERY_STEP_MS,
    MIN_QUERY_INTEGER,
    parse_integer,
    parse_query_values,
    parse_utc_timestamp,
)
from .system_observation_access import authorize_system_read, system_read_headers

_REQUIRED_QUERY_FIELDS = frozenset(
    {
        "environmentId",
        "scope",
        "from",
        "to",
        "page",
        "pageSize",
        "search",
        "stepMs",
    }
)
_OPTIONAL_QUERY_FIELDS = frozenset({"appId"})


def fleet_overview_route(
    read_session: ReadSession,
    read_fleet: ReadFleetOverview | None,
) -> Route:
    """Create the metrics:view fleet summary and application page endpoint."""

    async def read_snapshot(request: Request) -> Response:
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
            query = _parse_query(request)
        except ValueError:
            return error_response(request_id_value, "invalid_request", 400)
        if read_fleet is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_fleet.execute(query)
        except FleetOverviewTargetNotFound:
            return error_response(request_id_value, "not_found", 404)
        except FleetOverviewRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (FleetOverviewAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            fleet_snapshot_body(snapshot),
            headers=system_read_headers(request_id_value),
        )

    return Route("/api/v1/fleet/overview", read_snapshot, methods=["GET"])


def _parse_query(request: Request) -> FleetQuery:
    supplied = parse_query_values(
        request, _REQUIRED_QUERY_FIELDS, _OPTIONAL_QUERY_FIELDS
    )
    app_id = supplied.get("appId")
    return FleetQuery(
        context=ObservationContext(
            environment_id=supplied["environmentId"],
            app_id=app_id,
            instance_id=None,
            resource=None,
            scope=ObservationScope(supplied["scope"]),
            window=ObservationWindow(
                parse_utc_timestamp(supplied["from"]),
                parse_utc_timestamp(supplied["to"]),
            ),
        ),
        page=parse_integer(supplied["page"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER),
        page_size=parse_integer(
            supplied["pageSize"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE
        ),
        search=supplied["search"],
        step_ms=parse_integer(supplied["stepMs"], MIN_QUERY_INTEGER, MAX_QUERY_STEP_MS),
    )
