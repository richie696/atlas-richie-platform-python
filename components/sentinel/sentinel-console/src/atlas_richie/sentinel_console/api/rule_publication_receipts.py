"""Authenticated paginated reads of exact-publication instance receipts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.read_rule_publication_receipts import ReadRulePublicationReceipts
from ..application.read_session import ReadSession
from ..application.rule_publication_errors import InvalidPublicationReceiptQuery
from ..application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationNotFound,
    RulePublicationRateLimited,
)
from ..domain.rule_publications import (
    MAX_PUBLICATION_RECEIPT_PAGE,
    MAX_PUBLICATION_RECEIPT_PAGE_SIZE,
)
from .http_support import error_response
from .query_parsing import MIN_QUERY_INTEGER, parse_integer, parse_query_values
from .rule_publication_serializers import rule_publication_receipt_page_body
from .system_observation_access import authorize_system_read, system_read_headers

_PAGE_QUERY_FIELDS = (
    ("page", MAX_PUBLICATION_RECEIPT_PAGE),
    ("pageSize", MAX_PUBLICATION_RECEIPT_PAGE_SIZE),
)
_REQUIRED_QUERY_FIELDS = frozenset(name for name, _maximum in _PAGE_QUERY_FIELDS)


def rule_publication_receipts_route(
    read_session: ReadSession,
    read_receipts: ReadRulePublicationReceipts | None,
) -> Route:
    """Create the session-protected publication receipt page endpoint."""

    async def read_page(request: Request) -> Response:
        request_id_value, _identity, rejection = await authorize_system_read(
            request, read_session, invalid_request_code="invalid_request"
        )
        if rejection is not None:
            return rejection

        binding_id = request.path_params["bindingId"]
        publication_id = request.path_params["publicationId"]
        try:
            page, page_size = _page_arguments(request)
        except (ValueError, TypeError):
            return error_response(request_id_value, "invalid_request", 400)
        if read_receipts is None:
            return error_response(request_id_value, "service_unavailable", 503)

        try:
            receipt_page = await read_receipts.execute(
                binding_id, publication_id, page, page_size
            )
        except InvalidPublicationReceiptQuery:
            return error_response(request_id_value, "invalid_request", 400)
        except RulePublicationNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RulePublicationRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RulePublicationAuthorityUnavailable, ValueError):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            rule_publication_receipt_page_body(receipt_page),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/publications/{publicationId:str}/receipts",
        read_page,
        methods=["GET"],
    )


def _page_arguments(request: Request) -> tuple[int, int]:
    """Parse only the required, unique pagination fields within wire bounds."""
    supplied = parse_query_values(request, _REQUIRED_QUERY_FIELDS)

    parsed: list[int] = []
    for name, maximum in _PAGE_QUERY_FIELDS:
        parsed.append(parse_integer(supplied[name], MIN_QUERY_INTEGER, maximum))
    return parsed[0], parsed[1]
