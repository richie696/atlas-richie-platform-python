"""Authenticated, process-epoch-bound instance observation endpoint."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceCatalogRateLimited,
    InstanceCatalogTargetNotFound,
    InstanceIncarnationRetired,
)
from ..application.read_instance_observation import ReadInstanceObservation
from ..application.read_session import ReadSession
from ..domain.instance_catalog import InstanceLayer, ObservationWindow
from ..domain.instance_observation import (
    InstanceDetailQuery,
    InstanceObservation,
)
from ..domain.session import SessionCapability
from .http_support import error_response
from .instance_serializers import instance_body
from .metric_serializers import context_body, metric_bundle_body
from .query_parsing import parse_integer, parse_utc_timestamp
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)

_REQUIRED_QUERY_FIELDS = frozenset(
    {"environmentId", "appId", "scope", "from", "to", "processEpoch", "stepMs"}
)
_OPTIONAL_QUERY_FIELDS = frozenset({"resource"})


def instance_observation_route(
    read_session: ReadSession,
    read_observation: ReadInstanceObservation | None,
) -> Route:
    """Create a detail route guarded by metrics:view and exact query identity."""

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
        try:
            query = _parse_query(request)
        except ValueError:
            return error_response(request_id_value, "invalid_request", 400)
        if read_observation is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            result = await read_observation.execute(query)
        except InstanceIncarnationRetired:
            return error_response(request_id_value, "target_retired", 410)
        except InstanceCatalogTargetNotFound:
            return error_response(request_id_value, "not_found", 404)
        except InstanceCatalogRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (InstanceCatalogAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _observation_body(result), headers=system_read_headers(request_id_value)
        )

    return Route(
        "/api/v1/instances/{instance_id}", read_detail, methods=["GET"]
    )


def _parse_query(request: Request) -> InstanceDetailQuery:
    supplied: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if (
            name not in _REQUIRED_QUERY_FIELDS | _OPTIONAL_QUERY_FIELDS
            or name in supplied
        ):
            raise ValueError("query parameters must be known and unique")
        supplied[name] = value
    if not _REQUIRED_QUERY_FIELDS.issubset(supplied):
        raise ValueError("required instance detail query field is missing")
    return InstanceDetailQuery(
        environment_id=supplied["environmentId"],
        app_id=supplied["appId"],
        instance_id=request.path_params["instance_id"],
        resource=supplied.get("resource"),
        scope=InstanceLayer(supplied["scope"]),
        window=ObservationWindow(
            parse_utc_timestamp(supplied["from"]),
            parse_utc_timestamp(supplied["to"]),
        ),
        process_epoch=supplied["processEpoch"],
        step_ms=parse_integer(supplied["stepMs"], 1, 604_800_000),
    )


def _observation_body(result: InstanceObservation) -> dict[str, object]:
    query = result.query
    return {
        "query": {
            "context": context_body(query.context),
            "processEpoch": query.process_epoch,
            "stepMs": query.step_ms,
        },
        "asOf": utc_timestamp(result.as_of),
        "instance": instance_body(result.instance),
        "metrics": metric_bundle_body(result.metrics) if result.metrics else None,
    }
