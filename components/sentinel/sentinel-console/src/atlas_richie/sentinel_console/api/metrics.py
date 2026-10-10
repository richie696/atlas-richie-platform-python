"""Authenticated read endpoint for exact metric windows and selections."""

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
from ..application.read_metrics import ReadMetrics
from ..application.read_session import ReadSession
from ..domain.instance_catalog import METRIC_UNITS, ObservationScope, ObservationWindow
from ..domain.instance_observation import MetricQuery, ObservationContext
from ..domain.session import SessionCapability
from .http_support import error_response
from .metric_serializers import metric_bundle_body
from .query_parsing import parse_integer, parse_utc_timestamp
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
)

_REQUIRED_QUERY_FIELDS = frozenset(
    {"environmentId", "scope", "from", "to", "metrics", "stepMs"}
)
_OPTIONAL_QUERY_FIELDS = frozenset({"appId", "instanceId", "resource"})
_MAX_METRIC_SELECTION_LENGTH = len(",".join(METRIC_UNITS))


def metrics_route(
    read_session: ReadSession,
    read_metrics: ReadMetrics | None,
) -> Route:
    """Create a metrics:view endpoint with strict, bounded query parsing."""

    async def read_bundle(request: Request) -> Response:
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
        if read_metrics is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            bundle = await read_metrics.execute(query)
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
            metric_bundle_body(bundle),
            headers=system_read_headers(request_id_value),
        )

    return Route("/api/v1/metrics/query", read_bundle, methods=["GET"])


def _parse_query(request: Request) -> MetricQuery:
    supplied: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if (
            name not in _REQUIRED_QUERY_FIELDS | _OPTIONAL_QUERY_FIELDS
            or name in supplied
        ):
            raise ValueError("query parameters must be known and unique")
        supplied[name] = value
    if not _REQUIRED_QUERY_FIELDS.issubset(supplied):
        raise ValueError("required metric query field is missing")
    metric_selection = supplied["metrics"]
    if not 1 <= len(metric_selection) <= _MAX_METRIC_SELECTION_LENGTH:
        raise ValueError("metric selection length is out of range")
    metrics = tuple(metric_selection.split(","))
    return MetricQuery(
        context=ObservationContext(
            environment_id=supplied["environmentId"],
            app_id=supplied.get("appId"),
            instance_id=supplied.get("instanceId"),
            resource=supplied.get("resource"),
            scope=ObservationScope(supplied["scope"]),
            window=ObservationWindow(
                parse_utc_timestamp(supplied["from"]),
                parse_utc_timestamp(supplied["to"]),
            ),
        ),
        metrics=metrics,
        step_ms=parse_integer(supplied["stepMs"], 1, 604_800_000),
    )
