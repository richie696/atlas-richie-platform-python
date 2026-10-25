"""Account directory authorization and wire-safety tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from atlas_richie.sentinel_console.api.accounts import _parse_query
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.account_directory_ports import (
    AccountDirectoryAuthorityUnavailable,
    AccountDirectoryItem,
    AccountDirectoryPage,
    AccountDirectoryStatus,
)
from atlas_richie.sentinel_console.application.errors import (
    SessionAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker
from starlette.datastructures import QueryParams
from starlette.requests import Request

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
            "account-1",
            "admin",
            "admin",
            "active",
            True,
            datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC),
            3,
            True,
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
        self.assertEqual(
            (later_page.page, later_page.page_size, later_page.total), (2, 20, 21)
        )

    async def test_directory_authority_cannot_return_cross_query_or_wrong_target_facts(
        self,
    ) -> None:
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

    async def test_account_row_type_violation_fails_closed(self) -> None:
        class MalformedDatabaseReader(_DirectoryReader):
            async def list_accounts(self, _query):
                raise TypeError("private database projection detail")

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", MalformedDatabaseReader())),
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

    async def test_malformed_directory_port_return_type_fails_closed(self) -> None:
        class MalformedReturnReader(_DirectoryReader):
            async def list_accounts(self, _query):
                return None

            async def read_account(self, _account_id):
                return {"account_id": "account-1"}

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", MalformedReturnReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            list_response = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
            detail_response = await client.get(
                "/api/v1/accounts/account-1",
                headers={"x-request-id": "account-directory-detail-1"},
            )

        for response in (list_response, detail_response):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_query_parser_rejects_non_scalar_unicode_without_encoding_error(
        self,
    ) -> None:
        request = SimpleNamespace(
            query_params=QueryParams(
                [("page", "1"), ("pageSize", "20"), ("search", "\ud800")]
            )
        )
        self.assertIsNone(_parse_query(request))

    async def test_query_parser_rejects_unknown_status_before_directory_call(self):
        request = SimpleNamespace(
            query_params=QueryParams(
                [
                    ("page", "1"),
                    ("pageSize", "20"),
                    ("search", ""),
                    ("status", "pending"),
                ]
            )
        )
        self.assertIsNone(_parse_query(request))

    async def test_query_parser_maps_wire_status_to_enum(self):
        request = SimpleNamespace(
            query_params=QueryParams(
                [
                    ("page", "1"),
                    ("pageSize", "20"),
                    ("search", ""),
                    ("status", "active"),
                ]
            )
        )
        query = _parse_query(request)
        self.assertIsNotNone(query)
        assert query is not None
        self.assertIs(query.status, AccountDirectoryStatus.ACTIVE)

    async def test_detail_route_rejects_non_scalar_account_id_before_authorization(
        self,
    ) -> None:
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
            "id",
            "username",
            "roleId",
            "status",
            "builtIn",
            "lastLoginAt",
            "revision",
            "lastActiveAdmin",
        }
        self.assertEqual(listed.status_code, 200)
        assert_openapi_response("listAccounts", listed)
        assert_openapi_response("readAccount", detail)
        assert_openapi_response("readAccount", missing)
        self.assertEqual(listed.json()["page"], 1)
        self.assertEqual(listed.json()["pageSize"], 20)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(set(listed.json()["items"][0]), expected)
        self.assertEqual(listed.json()["items"][0]["revision"], "3")
        self.assertEqual(
            listed.json()["items"][0]["lastLoginAt"], "2026-10-08T00:00:00.000Z"
        )
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
            assert_openapi_response("listAccounts", response)
            self.assertEqual(response.json()["error"]["code"], expected_code)

    async def test_viewer_detail_is_rejected_before_directory_access(self) -> None:
        class _UnexpectedDirectoryReader:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def list_accounts(self, _query):
                self.calls.append("list")
                raise AssertionError("viewer request reached account directory")

            async def read_account(self, _account_id: str):
                self.calls.append("detail")
                raise AssertionError("viewer request reached account directory")

        directory = _UnexpectedDirectoryReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", directory)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/accounts/account-1", headers=_REQUEST_HEADERS
            )

        self.assertEqual(
            (response.status_code, response.json()["error"]["code"]),
            (403, "forbidden"),
        )
        assert_openapi_response("readAccount", response)
        self.assertEqual(directory.calls, [], "authorization must precede account lookup")

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
            transport=ASGITransport(
                app=build_app(
                    bootstrap_initialization_reader=_Initialized(),
                    setup_window_reader=_OpenSetupWindow(),
                    bootstrap_operator_verifier=_OperatorVerifier(),
                    current_session_reader=unavailable,
                    current_session_revoker=UnusedSessionRevoker(),
                    account_directory_reader=_DirectoryReader(),
                    allowed_browser_origins=frozenset({"https://console.test"}),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            failure = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(invalid.status_code, 400)
        assert_openapi_response("listAccounts", invalid)
        assert_openapi_response("listAccounts", unknown)
        assert_openapi_response("listAccounts", overlong_search)
        assert_openapi_response("listAccounts", failure)
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(overlong_search.status_code, 400)
        self.assertEqual(failure.status_code, 503)
        self.assertNotIn("private backend detail", failure.text)

    async def test_search_limit_counts_utf16_units_and_rejects_before_directory_read(
        self,
    ) -> None:
        class RecordingDirectoryReader(_DirectoryReader):
            def __init__(self) -> None:
                super().__init__()
                self.queries = []

            async def list_accounts(self, query):
                self.queries.append(query)
                return await super().list_accounts(query)

        directory = RecordingDirectoryReader()
        accepted_searches = ("a" * 200, "😀" * 100)
        rejected_searches = ("a" * 201, ("😀" * 100) + "a")

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", directory)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            accepted_responses = [
                await client.get(
                    "/api/v1/accounts",
                    params={"page": "1", "pageSize": "20", "search": search},
                    headers=_REQUEST_HEADERS,
                )
                for search in accepted_searches
            ]
            rejected_responses = [
                await client.get(
                    "/api/v1/accounts",
                    params={"page": "1", "pageSize": "20", "search": search},
                    headers=_REQUEST_HEADERS,
                )
                for search in rejected_searches
            ]

        for response in accepted_responses:
            assert_openapi_response("listAccounts", response)
            self.assertEqual(response.status_code, 200)
        for response in rejected_responses:
            assert_openapi_response("listAccounts", response)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertEqual(
            [query.search for query in directory.queries], list(accepted_searches)
        )

    async def test_directory_authority_failure_does_not_leak_adapter_details(
        self,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("admin", _DirectoryReader(unavailable=True))
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/accounts?page=1&pageSize=20&search=",
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(response.status_code, 503)
        assert_openapi_response("readAccount", response)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private query details", response.text)
