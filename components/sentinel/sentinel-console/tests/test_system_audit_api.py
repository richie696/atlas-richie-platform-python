"""Admin-only system audit API and query-contract tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.system_audit_ports import (
    SystemAuditAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.domain.system_audit import (
    AuditAction,
    AuditQuery,
    AuditRecord,
    AuditResult,
    SystemAuditPage,
)

_REQUEST_HEADERS = {"x-request-id": "audit-read-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0001"
_START = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
_END = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
_AS_OF = datetime(2026, 10, 9, 1, 2, 3, 456789, tzinfo=UTC)


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
            raise SessionAuthorityUnavailable("private session-store detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AuditReader:
    def __init__(self, page: SystemAuditPage | None = None) -> None:
        self.page = page or _page()
        self.query: AuditQuery | None = None
        self.calls = 0

    async def read_system_audit(self, query: AuditQuery) -> SystemAuditPage:
        self.calls += 1
        self.query = query
        if query != self.page.query:
            return SystemAuditPage(query, _AS_OF, 0, ())
        return self.page


class _UnavailableAuditReader:
    async def read_system_audit(self, query: AuditQuery) -> SystemAuditPage:
        raise SystemAuditAuthorityUnavailable("private audit-store detail")


class _MismatchedAuditReader:
    async def read_system_audit(self, query: AuditQuery) -> SystemAuditPage:
        return _page()


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("audit read must not touch the account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("audit read must not touch the account directory")


def _query() -> AuditQuery:
    return AuditQuery(_START, _END, "", None, None, 1, 20)


def _page() -> SystemAuditPage:
    return SystemAuditPage(
        _query(),
        _AS_OF,
        1,
        (
            AuditRecord(
                "event-1",
                datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
                "account-1",
                AuditAction.ACCOUNT_CREATE,
                "account-2",
                AuditResult.SUCCESS,
                "request-1",
            ),
        ),
    )


def _app(role: str | None, *, reader=None, session_reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        system_audit_reader=reader,
    )


def _params() -> dict[str, str]:
    return {
        "start": "2026-10-08T00:00:00.000Z",
        "end": "2026-10-09T00:00:00.000Z",
        "page": "1",
        "pageSize": "20",
    }


class SystemAuditApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_receives_bounded_safe_audit_projection(self) -> None:
        reader = _AuditReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/audit", params=_params(), headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readSystemAudit", response)
        self.assertEqual(response.headers["x-request-id"], "audit-read-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie")
        self.assertEqual(
            response.json(),
            {
                "query": {
                    "start": "2026-10-08T00:00:00.000Z",
                    "end": "2026-10-09T00:00:00.000Z",
                    "actorId": "",
                    "action": None,
                    "result": None,
                    "page": 1,
                    "pageSize": 20,
                },
                "asOf": "2026-10-09T01:02:03.456Z",
                "total": 1,
                "items": [
                    {
                        "id": "event-1",
                        "occurredAt": "2026-10-08T12:00:00.000Z",
                        "actorId": "account-1",
                        "action": "account-create",
                        "targetId": "account-2",
                        "result": "success",
                        "requestId": "request-1",
                        "environmentId": None,
                        "appId": None,
                        "bindingId": None,
                        "publicationId": None,
                    }
                ],
            },
        )
        self.assertNotIn("password", response.text)
        self.assertNotIn("traceback", response.text)
        self.assertNotIn("requestKey", response.json()["items"][0])
        self.assertEqual(reader.calls, 1)

    async def test_mismatched_authority_query_is_not_returned_as_success(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=_MismatchedAuditReader())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/audit",
                params={**_params(), "action": AuditAction.PLAN_ACTIVATE.value},
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 503)
        assert_openapi_response("readSystemAudit", response)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("account-create", response.text)

    async def test_viewer_and_anonymous_are_rejected_before_audit_read(self) -> None:
        for role, status, code in (
            (None, 401, "unauthenticated"),
            ("view", 403, "forbidden"),
        ):
            reader = _AuditReader()
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/audit", params=_params(), headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, status)
            assert_openapi_response("readSystemAudit", response)
            self.assertEqual(response.json()["error"]["code"], code)
            self.assertEqual(reader.calls, 0)

    async def test_system_plan_action_filter_is_a_supported_api_value(self) -> None:
        reader = _AuditReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/audit",
                params={**_params(), "action": AuditAction.PLAN_ACTIVATE.value},
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readSystemAudit", response)
        self.assertIsNotNone(reader.query)
        self.assertEqual(reader.query.action, AuditAction.PLAN_ACTIVATE)
        self.assertEqual(response.json()["query"]["action"], "plan-activate")

    async def test_invalid_query_and_request_id_return_invalid_request(self) -> None:
        invalid_queries = (
            {},
            {**_params(), "extra": "1"},
            [*_params().items(), ("page", "2")],
            {**_params(), "start": "2026-02-30T00:00:00.000Z"},
            {**_params(), "start": "2026-10-08T00:00:00Z"},
            {**_params(), "start": "2026-10-08T00:00:00.000+00:00"},
            {**_params(), "start": "2026-10-08T00:00:00.000000Z"},
            {**_params(), "start": "1969-12-31T23:59:59.999Z"},
            {**_params(), "end": "2026-10-08T00:00:00.000Z"},
            {**_params(), "end": "2026-11-09T00:00:00.000Z"},
            {**_params(), "page": "01"},
            {**_params(), "pageSize": "101"},
            {**_params(), "action": "unknown-action"},
            {**_params(), "actorId": "😀" * 101},
            *(
                {**_params(), "actorId": blank}
                for blank in ("\x1c", "\x85", "\ufeff", "\u3000")
            ),
        )
        reader = _AuditReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            responses = []
            for query in invalid_queries:
                responses.append(
                    await client.get(
                        "/api/v1/system/audit", params=query, headers=_REQUEST_HEADERS
                    )
                )
            invalid_request_id = await client.get(
                "/api/v1/system/audit",
                params=_params(),
                headers={"x-request-id": "bad\nrequest"},
            )

        self.assertTrue(all(response.status_code == 400 for response in responses))
        for response in responses:
            assert_openapi_response("readSystemAudit", response)
        self.assertTrue(
            all(
                response.json()["error"]["code"] == "invalid_request"
                for response in responses
            )
        )
        self.assertEqual(invalid_request_id.status_code, 400)
        assert_openapi_response("readSystemAudit", invalid_request_id)
        self.assertEqual(invalid_request_id.json()["error"]["code"], "invalid_request")
        self.assertEqual(reader.calls, 0)

    async def test_audit_domain_rejects_surrogate_actor_filter_without_encoding_failure(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "actor filter is invalid"):
            AuditQuery(_START, _END, "\ud800", None, None, 1, 20)

    async def test_authority_failures_are_bounded_and_do_not_leak(self) -> None:
        for role, reader in (
            ("unavailable", _AuditReader()),
            ("admin", None),
            ("admin", _UnavailableAuditReader()),
        ):
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app(role, reader=reader, session_reader=_SessionReader(role))
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/audit", params=_params(), headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, 503)
            assert_openapi_response("readSystemAudit", response)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
            self.assertNotIn("private", response.text)

    async def test_domain_rejects_out_of_query_records_and_unstable_order(self) -> None:
        query = _query()
        record = _page().items[0]
        with self.assertRaises(ValueError):
            SystemAuditPage(
                query,
                _AS_OF,
                1,
                (
                    AuditRecord(
                        record.id,
                        _END,
                        record.actor_id,
                        record.action,
                        record.target_id,
                        record.result,
                        record.request_id,
                    ),
                ),
            )
        with self.assertRaises(ValueError):
            AuditQuery(
                _START,
                _END + timedelta(days=31),
                "",
                None,
                None,
                1,
                20,
            )

    async def test_domain_requires_actor_for_account_owned_audit_actions(self) -> None:
        record = _page().items[0]
        with self.assertRaisesRegex(ValueError, "requires an account actor"):
            AuditRecord(
                record.id,
                record.occurred_at,
                None,
                AuditAction.ACCOUNT_CREATE,
                record.target_id,
                record.result,
                record.request_id,
            )
        for action in (
            AuditAction.SYSTEM_INITIALIZE,
            AuditAction.PLAN_ACTIVATE,
            AuditAction.PLAN_RESTORE,
        ):
            AuditRecord(
                record.id,
                record.occurred_at,
                None,
                action,
                record.target_id,
                record.result,
                record.request_id,
            )
