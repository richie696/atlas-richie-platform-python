"""Admin-only HTTP adapter for bounded system audit reads."""

from __future__ import annotations

import re
from datetime import datetime

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_session import ReadSession
from ..application.read_system_audit import ReadSystemAudit
from ..application.system_audit_ports import SystemAuditAuthorityUnavailable
from ..domain.session import AccountRole
from ..domain.system_audit import AuditAction, AuditQuery, AuditResult, SystemAuditPage
from ..domain.wire_strings import is_bounded_wire_identifier
from .http_support import error_response
from .query_parsing import (
    MAX_QUERY_PAGE_NUMBER,
    MAX_QUERY_PAGE_SIZE,
    MIN_QUERY_INTEGER,
    parse_integer,
    parse_query_values,
)
from .system_observation_access import (
    authorize_system_read,
    system_read_headers,
    utc_timestamp,
)

_ALLOWED_QUERY_KEYS = frozenset(
    {"start", "end", "actorId", "action", "result", "page", "pageSize"}
)
_REQUIRED_QUERY_KEYS = frozenset({"start", "end", "page", "pageSize"})
_UTC_MILLISECOND_PATTERN = re.compile(
    r"^(?:19[7-9]\d|[2-9]\d{3})-"
    r"(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T"
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}Z$"
)


def system_audit_route(
    read_session: ReadSession,
    read_audit: ReadSystemAudit | None,
) -> Route:
    """Create the admin-only audit route with strict filters and safe projections."""

    async def read_page(request: Request) -> Response:
        request_id_value, identity, rejection = await authorize_system_read(
            request,
            read_session,
            invalid_request_code="invalid_request",
        )
        if rejection is not None:
            return rejection
        assert identity is not None
        if identity.role_id is not AccountRole.ADMIN:
            return error_response(request_id_value, "forbidden", 403)
        query = _parse_query(request)
        if query is None:
            return error_response(request_id_value, "invalid_request", 400)
        if read_audit is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            page = await read_audit.execute(query)
        except SystemAuditAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            _page_body(page), headers=system_read_headers(request_id_value)
        )

    return Route("/api/v1/system/audit", read_page, methods=["GET"])


def _parse_query(request: Request) -> AuditQuery | None:
    try:
        values = parse_query_values(
            request, _REQUIRED_QUERY_KEYS, _ALLOWED_QUERY_KEYS - _REQUIRED_QUERY_KEYS
        )
    except ValueError:
        return None
    actor_id = values.get("actorId", "")
    if actor_id and not is_bounded_wire_identifier(actor_id, 200):
        return None
    start = _parse_utc_instant(values["start"])
    end = _parse_utc_instant(values["end"])
    if start is None or end is None:
        return None
    try:
        page = parse_integer(values["page"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER)
        page_size = parse_integer(
            values["pageSize"], MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE
        )
        action = AuditAction(values["action"]) if "action" in values else None
        result = AuditResult(values["result"]) if "result" in values else None
        return AuditQuery(start, end, actor_id, action, result, page, page_size)
    except (ValueError, OverflowError):
        return None


def _parse_utc_instant(value: str) -> datetime | None:
    if _UTC_MILLISECOND_PATTERN.fullmatch(value) is None:
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _page_body(page: SystemAuditPage) -> dict[str, object]:
    query = page.query
    return {
        "query": {
            "start": utc_timestamp(query.start),
            "end": utc_timestamp(query.end),
            "actorId": query.actor_id,
            "action": query.action.value if query.action is not None else None,
            "result": query.result.value if query.result is not None else None,
            "page": query.page,
            "pageSize": query.page_size,
        },
        "asOf": utc_timestamp(page.as_of),
        "total": page.total,
        "items": [
            {
                "id": item.id,
                "occurredAt": utc_timestamp(item.occurred_at),
                "actorId": item.actor_id,
                "action": item.action.value,
                "targetId": item.target_id,
                "result": item.result.value,
                "requestId": item.request_id,
                "environmentId": item.environment_id,
                "appId": item.app_id,
                "bindingId": item.binding_id,
                "publicationId": item.publication_id,
            }
            for item in page.items
        ],
    }
