"""Account directory authorization and wire-safety tests."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
from starlette.datastructures import QueryParams
from starlette.requests import Request

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.api.accounts import _parse_query
from atlas_richie.sentinel_console.application.account_directory_ports import (
    AccountDirectoryAuthorityUnavailable,
    AccountDirectoryItem,
    AccountDirectoryPage,
)
from atlas_richie.sentinel_console.application.errors import (
    SessionAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "account-directory-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0001"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _OpenSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if self.role == "unavailable":
            raise SessionAuthorityUnavailable("private backend detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "admin", self.role, "epoch-1")


class _DirectoryReader:
    def __init__(self, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.item = AccountDirectoryItem(
            "account-1", "admin", "admin", "active", True,
            datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC), 3, True,
        )

    async def list_accounts(self, query):
        if self.unavailable:
            raise AccountDirectoryAuthorityUnavailable("private query details")
        return AccountDirectoryPage((self.item,), query.page, query.page_size, 1)

    async def read_account(self, account_id: str):
        if self.unavailable:
            raise AccountDirectoryAuthorityUnavailable("private query details")
        return self.item if account_id == self.item.account_id else None


def _app(role: str | None, directory: _DirectoryReader | None = None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=directory or _DirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
    )


class AccountDirectoryApiTest(unittest.IsolatedAsyncioTestCase):
    def test_directory_item_enforces_browser_record_invariants(self) -> None:
        item = _DirectoryReader().item
        invalid_items = (
            {"role_id": "unknown"},
            {"status": "pending"},
            {"username": "\u0085\ufeff"},
            {"revision": 0},
            {"built_in": 1},
            {"built_in": False, "status": "disabled", "last_active_admin": True},
        )
        fields = (
            item.account_id,
            item.username,
            item.role_id,
            item.status,
            item.built_in,
            item.last_login_at,
            item.revision,
            item.last_active_admin,
        )
        field_names = (
            "account_id",
            "username",
            "role_id",
            "status",
            "built_in",
            "last_login_at",
            "revision",
            "last_active_admin",
        )
        for overrides in invalid_items:
            values = dict(zip(field_names, fields, strict=True))
            values.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                AccountDirectoryItem(
                    **values,
                )

    def test_directory_page_enforces_browser_pagination_invariants(self) -> None:
        item = _DirectoryReader().item
        invalid_pages = (
            ((item,), 1, 20, 2),
            ((item, item), 1, 20, 2),
            ((item,), 1, 20, -1),
            ((), True, 20, 0),
        )
        for args in invalid_pages:
            with self.subTest(args=args), self.assertRaises(ValueError):
                AccountDirectoryPage(*args)

        later_page = AccountDirectoryPage((item,), 2, 20, 21)
        self.assertEqual((later_page.page, later_page.page_size, later_page.total), (2, 20, 21))

    async def test_directory_authority_cannot_return_cross_query_or_wrong_target_facts(self) -> None:
        class MismatchedDirectoryReader(_DirectoryReader):
            async def list_accounts(self, query):
                page = query.page if query.status is not None else query.page + 1
                return AccountDirectoryPage((self.item,), page, query.page_size, 1)

            async def read_account(self, account_id: str):
                return self.item

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", MismatchedDirectoryReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            page_mismatch = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
            status_mismatch = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=&status=disabled",
                headers=_REQUEST_HEADERS,
            )
            target_mismatch = await client.get(
                "/api/v1/accounts/account-2", headers=_REQUEST_HEADERS
            )

        for response in (page_mismatch, status_mismatch, target_mismatch):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_malformed_account_authority_record_fails_closed(self) -> None:
        class MalformedDirectoryReader(_DirectoryReader):
            async def list_accounts(self, query):
                invalid = AccountDirectoryItem(
                    "account-2", "viewer", "view", "disabled", True, None, 1, False
                )
                return AccountDirectoryPage((invalid,), query.page, query.page_size, 1)

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", MalformedDirectoryReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private", response.text)

    async def test_query_parser_rejects_non_scalar_unicode_without_encoding_error(self) -> None:
        request = SimpleNamespace(
            query_params=QueryParams(
                [("page", "1"), ("pageSize", "20"), ("search", "\ud800")]
            )
        )
        self.assertIsNone(_parse_query(request))

    async def test_detail_route_rejects_non_scalar_account_id_before_authorization(self) -> None:
        app = _app("admin")
        route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/v1/accounts/{account_id:str}"
        )
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/accounts/\ud800",
                "headers": [(b"x-request-id", b"account-directory-1")],
                "query_string": b"",
                "path_params": {"account_id": "\ud800"},
            }
        )
        response = await route.endpoint(request)
        self.assertEqual(response.status_code, 400)

    async def test_admin_list_and_detail_return_only_safe_wire_fields(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin")), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            listed = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=admin",
                headers=_REQUEST_HEADERS,
            )
            detail = await client.get(
                "/api/v1/accounts/account-1", headers=_REQUEST_HEADERS
            )
            missing = await client.get(
                "/api/v1/accounts/unknown", headers=_REQUEST_HEADERS
            )

        expected = {
            "id", "username", "roleId", "status", "builtIn", "lastLoginAt",
            "revision", "lastActiveAdmin",
        }
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["page"], 1)
        self.assertEqual(listed.json()["pageSize"], 20)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(set(listed.json()["items"][0]), expected)
        self.assertEqual(listed.json()["items"][0]["revision"], "3")
        self.assertEqual(listed.json()["items"][0]["lastLoginAt"], "2026-10-08T00:00:00.000Z")
        self.assertEqual(detail.json(), listed.json()["items"][0])
        self.assertEqual((missing.status_code, missing.json()), (200, None))
        self.assertNotIn("password", listed.text)
        self.assertNotIn("hash", listed.text)
        self.assertEqual(listed.headers["cache-control"], "no-store")
        self.assertEqual(listed.headers["vary"], "Cookie")

    async def test_anonymous_and_viewer_are_rejected(self) -> None:
        for role, expected_status, expected_code in [
            (None, 401, "unauthenticated"),
            ("view", 403, "forbidden"),
        ]:
            async with AsyncClient(
                transport=ASGITransport(app=_app(role)), base_url="http://test"
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/accounts?page=1&pageSize=20&search=",
                    headers=_REQUEST_HEADERS,
                )
            self.assertEqual(response.status_code, expected_status)
            self.assertEqual(response.json()["error"]["code"], expected_code)

    async def test_invalid_query_and_directory_failure_are_bounded(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin")), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            invalid = await client.get(
                "/api/v1/accounts?page=1&page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
            unknown = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=&extra=x",
                headers=_REQUEST_HEADERS,
            )
            overlong_search = await client.get(
                "/api/v1/accounts",
                params={"page": "1", "pageSize": "20", "search": "😀" * 101},
                headers=_REQUEST_HEADERS,
            )
        unavailable = _SessionReader("unavailable")
        async with AsyncClient(
            transport=ASGITransport(app=build_app(
                bootstrap_initialization_reader=_Initialized(),
                setup_window_reader=_OpenSetupWindow(),
                bootstrap_operator_verifier=_OperatorVerifier(),
                current_session_reader=unavailable,
                current_session_revoker=UnusedSessionRevoker(),
                account_directory_reader=_DirectoryReader(),
                allowed_browser_origins=frozenset({"https://console.test"}),
            )), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            failure = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(overlong_search.status_code, 400)
        self.assertEqual(failure.status_code, 503)
        self.assertNotIn("private backend detail", failure.text)

    async def test_directory_authority_failure_does_not_leak_adapter_details(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", _DirectoryReader(unavailable=True))),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private query details", response.text)
