"""Local ASGI-to-SQLAlchemy bootstrap integration tests using disposable SQLite."""

from __future__ import annotations

import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from atlas_richie.sentinel_console.app import build_app
from session_test_doubles import UnusedSessionRevoker
from atlas_richie.sentinel_console.infrastructure.persistence.bootstrap_initialization_reader import (
    SqlAlchemyBootstrapInitializationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import ConsoleGuardRecord


class _OpenSetupWindow:
    def __init__(self) -> None:
        self.reads = 0

    async def is_setup_window_open(self) -> bool:
        self.reads += 1
        return True


class _OperatorVerifier:
    def __init__(self) -> None:
        self.sessions: list[str | None] = []

    async def is_current_operator(self, opaque_session: str | None) -> bool:
        self.sessions.append(opaque_session)
        return True


class _AnonymousSessionReader:
    async def read_active_session(self, session_digest: str):
        raise AssertionError("bootstrap route must not read account sessions")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("bootstrap route must not read account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("bootstrap route must not read account directory")


class BootstrapPersistenceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.setup_window = _OpenSetupWindow()
        self.operator_verifier = _OperatorVerifier()
        self.app = build_app(
            bootstrap_initialization_reader=SqlAlchemyBootstrapInitializationReader(
                self.engine
            ),
            setup_window_reader=self.setup_window,
            bootstrap_operator_verifier=self.operator_verifier,
            current_session_reader=_AnonymousSessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_UnusedAccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_bootstrap_endpoint_reads_database_then_short_circuits_after_initialization(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_bootstrap", "synthetic-operator-cookie")
            before = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "db-bootstrap-1"}
            )

            async with self.engine.begin() as connection:
                await connection.execute(
                    ConsoleGuardRecord.__table__.update()
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .values(initialized=True)
                )

            after = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "db-bootstrap-2"}
            )

        self.assertEqual(before.status_code, 200)
        self.assertEqual(
            before.json(),
            {
                "initialized": False,
                "setupAvailable": True,
                "operatorAuthorized": True,
            },
        )
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json(), {"initialized": True})
        self.assertEqual(self.setup_window.reads, 1)
        self.assertEqual(self.operator_verifier.sessions, ["synthetic-operator-cookie"])

    async def test_missing_guard_fails_closed_at_http_boundary(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(ConsoleGuardRecord.__table__.delete())

        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "db-bootstrap-3"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"error": {"code": "service_unavailable", "requestId": "db-bootstrap-3"}},
        )
        self.assertEqual(self.setup_window.reads, 0)
        self.assertEqual(self.operator_verifier.sessions, [])

    async def test_database_connection_failure_fails_closed_without_leaking_driver_error(self) -> None:
        missing_database_path = (
            f"/private/tmp/sentinel-console-no-directory-{uuid4().hex}/console.db"
        )
        unavailable_engine = create_async_engine(
            f"sqlite+aiosqlite:///{missing_database_path}"
        )
        app = build_app(
            bootstrap_initialization_reader=SqlAlchemyBootstrapInitializationReader(
                unavailable_engine
            ),
            setup_window_reader=self.setup_window,
            bootstrap_operator_verifier=self.operator_verifier,
            current_session_reader=_AnonymousSessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_UnusedAccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/system/bootstrap",
                    headers={"x-request-id": "db-bootstrap-4"},
                )
        finally:
            await unavailable_engine.dispose()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"error": {"code": "service_unavailable", "requestId": "db-bootstrap-4"}},
        )
        self.assertNotIn(missing_database_path, response.text)
        self.assertEqual(self.setup_window.reads, 0)
        self.assertEqual(self.operator_verifier.sessions, [])
