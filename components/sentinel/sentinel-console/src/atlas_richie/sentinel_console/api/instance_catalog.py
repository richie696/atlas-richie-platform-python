"""Authenticated read endpoint for paged instance and process facts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceCatalogRateLimited,
    InstanceCatalogTargetNotFound,
)
from ..application.read_instance_catalog import ReadInstanceCatalog
from ..application.read_session import ReadSession
from ..domain.instance_catalog import (
    InstanceCatalogQuery,
    InstanceCatalogSnapshot,
    ObservationScope,
    ObservationWindow,
)
from ..domain.session import SessionCapability
from .http_support import error_response
from .instance_serializers import coverage_body, instance_body
from .query_parsing import (
    MAX_QUERY_PAGE_NUMBER,
    MAX_QUERY_PAGE_SIZE,
    MIN_QUERY_INTEGER,
    parse_integer,
    parse_query_values,
    parse_utc_timestamp,
)
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)

_REQUIRED_QUERY_FIELDS = frozenset(
    {
        "environmentId",
        "scope",
        "from",
        "to",
        "page",
        "pageSize",
        "search",
        "attentionOnly",
    }
)
_OPTIONAL_QUERY_FIELDS = frozenset({"appId"})


def instance_catalog_route(
    read_session: ReadSession,
    read_catalog: ReadInstanceCatalog | None,
) -> Route:
    """Create a metrics:view route with strict filter parsing and bounded output."""

    async def read_page(request: Request) -> Response:
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
        if read_catalog is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            snapshot = await read_catalog.execute(query)
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
            _snapshot_body(snapshot), headers=system_read_headers(request_id_value)
        )

    return Route("/api/v1/instances", read_page, methods=["GET"])


def _parse_query(request: Request) -> InstanceCatalogQuery:
    supplied = parse_query_values(
        request, _REQUIRED_QUERY_FIELDS, _OPTIONAL_QUERY_FIELDS
    )

    scope = ObservationScope(supplied["scope"])
    starts_at = parse_utc_timestamp(supplied["from"])
    ends_at = parse_utc_timestamp(supplied["to"])
    page = parse_integer(supplied["page"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER)
    page_size = parse_integer(
        supplied["pageSize"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE
    )
    attention_only = supplied["attentionOnly"]
    if attention_only not in ("true", "false"):
        raise ValueError("attentionOnly must be a boolean")
    return InstanceCatalogQuery(
        environment_id=supplied["environmentId"],
        app_id=supplied.get("appId"),
        instance_id=None,
        resource=None,
        scope=scope,
        window=ObservationWindow(starts_at, ends_at),
        page=page,
        page_size=page_size,
        search=supplied["search"],
        attention_only=attention_only == "true",
    )


def _snapshot_body(snapshot: InstanceCatalogSnapshot) -> dict[str, object]:
    query = snapshot.query
    return {
        "query": {
            "context": {
                "environmentId": query.environment_id,
                "appId": query.app_id,
                "instanceId": query.instance_id,
                "resource": query.resource,
                "scope": query.scope.value,
                "window": {
                    "from": utc_timestamp(query.window.starts_at),
                    "to": utc_timestamp(query.window.ends_at),
                },
            },
            "page": query.page,
            "pageSize": query.page_size,
            "search": query.search,
            "attentionOnly": query.attention_only,
        },
        "asOf": utc_timestamp(snapshot.as_of),
        "coverage": coverage_body(snapshot.coverage),
        "totalInstances": snapshot.total_instances,
        "attentionInstances": snapshot.attention_instances,
        "filteredTotal": snapshot.filtered_total,
        "items": [instance_body(instance) for instance in snapshot.items],
    }
