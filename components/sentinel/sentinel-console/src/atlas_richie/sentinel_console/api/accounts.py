"""HTTP adapters for administrator-only account directory reads."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.account_directory_ports import (
    MAX_ACCOUNT_DIRECTORY_IDENTIFIER_UNITS,
    MAX_ACCOUNT_DIRECTORY_PAGE,
    MAX_ACCOUNT_DIRECTORY_PAGE_SIZE,
    AccountDirectoryAuthorityUnavailable,
    AccountDirectoryContractViolation,
    AccountDirectoryQuery,
    AccountDirectoryStatus,
)
from ..application.errors import SessionAuthorityUnavailable
from ..application.read_account_directory import ReadAccountDirectory
from ..application.read_session import ReadSession
from ..domain.session import AccountRole, SessionIdentity
from ..domain.wire_strings import is_bounded_wire_identifier
from .account_serialization import account_item_body
from .browser_security import SESSION_COOKIE_NAME
from .http_support import error_response, request_id
from .query_parsing import MIN_QUERY_INTEGER, parse_integer, parse_query_values

_PAGE_KEYS = frozenset({"page", "pageSize", "search", "status"})
_REQUIRED_QUERY_KEYS = frozenset({"page", "pageSize", "search"})


def account_directory_routes(
    read_session: ReadSession, read_directory: ReadAccountDirectory
) -> tuple[Route, Route]:
    """Create account list/detail routes with per-request admin authorization."""

    async def list_accounts(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        query = _parse_query(request)
        if query is None:
            return error_response(request_id_value, "invalid_request", 400)
        identity, failure = await _authorized_admin(request, read_session)
        if failure is not None:
            return error_response(request_id_value, *failure)
        assert identity is not None
        try:
            page = await read_directory.list(query)
        except (
            AccountDirectoryAuthorityUnavailable,
            AccountDirectoryContractViolation,
        ):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            {
                "items": [account_item_body(item) for item in page.items],
                "page": page.page,
                "pageSize": page.page_size,
                "total": page.total,
            },
            headers=_response_headers(request_id_value),
        )

    async def read_account(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        account_id = request.path_params.get("account_id", "")
        if not is_bounded_wire_identifier(
            account_id, MAX_ACCOUNT_DIRECTORY_IDENTIFIER_UNITS
        ):
            return error_response(request_id_value, "invalid_request", 400)
        identity, failure = await _authorized_admin(request, read_session)
        if failure is not None:
            return error_response(request_id_value, *failure)
        assert identity is not None
        try:
            item = await read_directory.read(account_id)
        except (
            AccountDirectoryAuthorityUnavailable,
            AccountDirectoryContractViolation,
        ):
            return error_response(request_id_value, "service_unavailable", 503)
        return JSONResponse(
            account_item_body(item) if item is not None else None,
            headers=_response_headers(request_id_value),
        )

    return (
        Route("/api/v1/accounts", list_accounts, methods=["GET"]),
        Route("/api/v1/accounts/{account_id:str}", read_account, methods=["GET"]),
    )


async def _authorized_admin(
    request: Request, read_session: ReadSession
) -> tuple[SessionIdentity | None, tuple[str, int] | None]:
    try:
        identity = await read_session.execute(request.cookies.get(SESSION_COOKIE_NAME))
    except SessionAuthorityUnavailable:
        return None, ("service_unavailable", 503)
    if identity is None:
        return None, ("unauthenticated", 401)
    if identity.role_id is not AccountRole.ADMIN:
        return None, ("forbidden", 403)
    return identity, None


def _parse_query(request: Request) -> AccountDirectoryQuery | None:
    try:
        values = parse_query_values(
            request, _REQUIRED_QUERY_KEYS, _PAGE_KEYS - _REQUIRED_QUERY_KEYS
        )
    except ValueError:
        return None
    try:
        page = parse_integer(
            values["page"], MIN_QUERY_INTEGER, MAX_ACCOUNT_DIRECTORY_PAGE
        )
        page_size = parse_integer(
            values["pageSize"], MIN_QUERY_INTEGER, MAX_ACCOUNT_DIRECTORY_PAGE_SIZE
        )
    except ValueError:
        return None
    try:
        return AccountDirectoryQuery(
            page=page,
            page_size=page_size,
            search=values["search"],
            status=(
                AccountDirectoryStatus(values["status"]) if "status" in values else None
            ),
        )
    except ValueError:
        return None


def _response_headers(request_id_value: str) -> dict[str, str]:
    return {
        "x-request-id": request_id_value,
        "cache-control": "no-store",
        "vary": "Cookie",
    }
