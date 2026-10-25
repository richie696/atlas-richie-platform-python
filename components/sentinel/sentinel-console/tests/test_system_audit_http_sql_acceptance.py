"""SQLite-backed HTTP acceptance for the Console system-audit read path."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from session_test_doubles import UnusedSessionRevoker
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.system_audit_reader import (
    SqlAlchemySystemAuditReader,
)

_REQUEST_HEADERS = {"x-request-id": "audit-sql-http-acceptance"}
_SESSION_COOKIE = "synthetic-session-token-for-sql-audit-http-0001"
_START = "2026-10-13T00:00:00.000Z"
_END = "2026-10-14T00:00:00.000Z"
_CREATED_AT = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)
_AS_OF = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str) -> None:
        self._role = role

    async def read_active_session(self, session_digest: str) -> ActiveAccountSession:
        return ActiveAccountSession("admin-1", "operator", self._role, "epoch-1")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("audit read must not access the account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("audit read must not access the account directory")


class SystemAuditSqlHttpAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="admin-1",
                    username="operator",
                    username_key="operator",
                    password_hash="$argon2id$synthetic-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=_CREATED_AT,
                    updated_at=_CREATED_AT,
                )
            )
            await connection.execute(
                insert(AuditEventRecord).values(
                    event_id="00000000-0000-4000-8000-000000000001",
                    request_id="rule-save-request-1",
                    actor_account_id="admin-1",
                    action="rules.save_draft",
                    outcome="completed",
                    target_kind="rule-draft",
                    target_id="draft-1",
                    created_at=_CREATED_AT,
                )
            )
        self.reader = SqlAlchemySystemAuditReader(self.engine, clock=lambda: _AS_OF)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _app(self, role: str):
        return build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_ClosedSetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(role),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_UnusedAccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            system_audit_reader=self.reader,
        )

    async def test_http_returns_actual_filtered_sql_audit_facts(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self._app("admin")),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _SESSION_COOKIE)
            response = await client.get(
                "/api/v1/system/audit",
                params={
                    "start": _START,
                    "end": _END,
                    "action": "draft-save",
                    "result": "success",
                    "page": "1",
                    "pageSize": "5",
                },
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["x-request-id"], _REQUEST_HEADERS["x-request-id"]
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(body["query"]["start"], _START)
        self.assertEqual(body["query"]["end"], _END)
        self.assertEqual(body["query"]["action"], "draft-save")
        self.assertEqual(body["query"]["result"], "success")
        self.assertEqual(body["asOf"], "2026-10-14T01:00:00.000Z")
        self.assertEqual(body["total"], 1)
        self.assertEqual(
            body["items"][0],
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "occurredAt": "2026-10-13T12:30:00.000Z",
                "actorId": "admin-1",
                "action": "draft-save",
                "targetId": "draft-1",
                "result": "success",
                "requestId": "rule-save-request-1",
                "environmentId": None,
                "appId": None,
                "bindingId": None,
                "publicationId": None,
            },
        )
        self.assertNotIn("password_hash", response.text)

    async def test_view_role_cannot_read_sql_audit(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self._app("view")),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _SESSION_COOKIE)
            response = await client.get(
                "/api/v1/system/audit",
                params={"start": _START, "end": _END, "page": "1", "pageSize": "5"},
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")
