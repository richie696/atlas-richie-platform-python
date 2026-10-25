"""HTTP contract tests for the guarded bootstrap database check route."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseCheckResult,
    BootstrapDatabaseCheckUnavailable,
    BootstrapDatabaseFailureReason,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.issue_csrf_nonce import IssueCsrfNonce
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_connector import (
    BootstrapDatabaseConnector,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)


class _InitializationReader:
    def __init__(self, initialized: bool) -> None:
        self.initialized = initialized

    async def is_initialized(self) -> bool:
        return self.initialized


class _SetupWindowReader:
    def __init__(self, is_open: bool) -> None:
        self.is_open = is_open

    async def is_setup_window_open(self) -> bool:
        return self.is_open


class _OperatorVerifier:
    def __init__(self, expected: str | None) -> None:
        self.expected = expected

    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == self.expected and self.expected is not None


class _SessionReader:
    async def read_active_session(self, session_digest: str):
        return None


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class _Checker:
    def __init__(self, result: BootstrapDatabaseCheckResult) -> None:
        self.result = result
        self.candidates: list[BootstrapDatabaseCandidate] = []

    async def check(self, candidate: BootstrapDatabaseCandidate):
        self.candidates.append(candidate)
        return self.result


class _UnavailableChecker:
    async def check(self, candidate: BootstrapDatabaseCandidate):
        raise BootstrapDatabaseCheckUnavailable("private connector detail")


def _sqlite_checker(database_path: Path) -> BootstrapDatabaseConnector:
    policy = BootstrapDatabaseTargetPolicy(
        (
            BootstrapDatabaseTargetRule.create(
                BootstrapDatabaseKind.POSTGRESQL,
                "10.30.0.0/16",
                frozenset({5432}),
            ),
        )
    )
    return BootstrapDatabaseConnector(policy, sqlite_database_path=database_path)


class BootstrapDatabaseCheckApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(
        self,
        *,
        initialized: bool = False,
        setup_open: bool = True,
        operator_session: str | None = "operator-session",
        checker=None,
    ):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(initialized),
            setup_window_reader=_SetupWindowReader(setup_open),
            bootstrap_operator_verifier=_OperatorVerifier(operator_session),
            current_session_reader=_SessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            bootstrap_database_checker=checker,
        )

    async def _client(self, app):
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        )

    @staticmethod
    def _headers(nonce: str, *, origin: str = "https://console.test"):
        return {
            "origin": origin,
            "x-request-id": "database-check-1",
            "x-sentinel-csrf": nonce,
        }

    @staticmethod
    def _cookies(nonce: str, operator_session: str | None = "operator-session"):
        cookies = {"__Host-sentinel_csrf": nonce}
        if operator_session is not None:
            cookies["sentinel_bootstrap"] = operator_session
        return cookies

    @staticmethod
    def _postgresql_body():
        return {
            "kind": "postgresql",
            "host": "db.internal.example",
            "port": 5432,
            "database": "sentinel_console",
            "username": "bootstrap_user",
            "password": "secret-that-must-not-leak",
        }

    async def test_authorized_probe_returns_only_the_reachability_fact(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapDatabaseCheckResult(reachable=True))
        async with await self._client(self._build_app(checker=checker)) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/database-check",
                json=self._postgresql_body(),
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("checkBootstrapDatabase", response)
        self.assertEqual(response.json(), {"status": "reachable"})
        self.assertEqual(response.headers["x-request-id"], "database-check-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(len(checker.candidates), 1)
        candidate = checker.candidates[0]
        self.assertEqual(candidate.host, "db.internal.example")
        self.assertNotIn("secret-that-must-not-leak", repr(candidate))
        self.assertNotIn("secret-that-must-not-leak", response.text)

    async def test_unreachable_reasons_are_bounded_and_safe(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        reasons = (
            BootstrapDatabaseFailureReason.AUTHENTICATION,
            BootstrapDatabaseFailureReason.CONNECTION,
            BootstrapDatabaseFailureReason.UNSUPPORTED,
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                checker = _Checker(
                    BootstrapDatabaseCheckResult(reachable=False, reason=reason)
                )
                app = self._build_app(checker=checker)
                async with await self._client(app) as client:
                    response = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json=self._postgresql_body(),
                        headers=self._headers(nonce),
                        cookies=self._cookies(nonce),
                    )
                self.assertEqual(
                    response.json(), {"status": "unreachable", "reason": reason.value}
                )

    async def test_missing_authority_or_checker_fails_closed(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        for checker in (None, _UnavailableChecker()):
            with self.subTest(checker=type(checker).__name__ if checker else None):
                app = self._build_app(checker=checker)
                async with await self._client(app) as client:
                    response = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json=self._postgresql_body(),
                        headers=self._headers(nonce),
                        cookies=self._cookies(nonce),
                    )
                self.assertEqual(response.status_code, 503)
                assert_openapi_response("checkBootstrapDatabase", response)
                error_code = response.json()["error"]["code"]
                self.assertEqual(error_code, "service_unavailable")
                self.assertNotIn("secret-that-must-not-leak", response.text)
                self.assertNotIn("private connector detail", response.text)

    async def test_access_checks_precede_any_network_probe(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapDatabaseCheckResult(reachable=True))
        scenarios = (
            (
                True,
                True,
                "operator-session",
                self._headers(nonce),
                self._cookies(nonce),
            ),
            (
                False,
                False,
                "operator-session",
                self._headers(nonce),
                self._cookies(nonce),
            ),
            (
                False,
                True,
                "wrong-operator-session",
                self._headers(nonce),
                self._cookies(nonce),
            ),
            (
                False,
                True,
                "operator-session",
                self._headers(nonce, origin="https://evil.test"),
                self._cookies(nonce),
            ),
            (
                False,
                True,
                "operator-session",
                self._headers("x" * 32),
                self._cookies(nonce),
            ),
        )
        for initialized, setup_open, operator_session, headers, cookies in scenarios:
            with self.subTest(
                initialized=initialized,
                setup_open=setup_open,
                origin=headers["origin"],
            ):
                app = self._build_app(
                    initialized=initialized,
                    setup_open=setup_open,
                    operator_session=operator_session,
                    checker=checker,
                )
                async with await self._client(app) as client:
                    response = await client.post(
                        "/api/v1/system/bootstrap/database-check",
                        json=self._postgresql_body(),
                        headers=headers,
                        cookies=cookies,
                    )
                self.assertIn(response.status_code, {403})
        self.assertEqual(checker.candidates, [])

    async def test_candidate_schema_rejects_extra_fields_and_boolean_port(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapDatabaseCheckResult(reachable=True))
        bodies = (
            {**self._postgresql_body(), "writeToDatabase": True},
            {**self._postgresql_body(), "port": True},
            {**self._postgresql_body(), "host": "🌋" * 127},
            {**self._postgresql_body(), "host": "db.internal\u001c"},
            {**self._postgresql_body(), "database": "🌋" * 101},
            {**self._postgresql_body(), "username": "\u0085"},
            {**self._postgresql_body(), "username": "🌋" * 101},
            {**self._postgresql_body(), "password": "🌋" * 513},
            {"kind": "sqlite", "path": "/tmp/not-allowed"},
        )
        async with await self._client(self._build_app(checker=checker)) as client:
            responses = [
                await client.post(
                    "/api/v1/system/bootstrap/database-check",
                    json=body,
                    headers=self._headers(nonce),
                    cookies=self._cookies(nonce),
                )
                for body in bodies
            ]
            surrogate = await client.post(
                "/api/v1/system/bootstrap/database-check",
                content=(
                    b'{"kind":"postgresql","host":"db.internal.example",'
                    b'"port":5432,"database":"sentinel_console",'
                    b'"username":"invalid-\\ud800","password":"secret"}'
                ),
                headers={
                    **self._headers(nonce),
                    "content-type": "application/json",
                },
                cookies=self._cookies(nonce),
            )
        status_codes = [response.status_code for response in responses]
        self.assertEqual(status_codes, [400] * len(bodies))
        self.assertEqual(surrogate.status_code, 400)
        self.assertEqual(checker.candidates, [])

    async def test_authorized_api_uses_real_deployment_owned_sqlite_probe_read_only(
        self,
    ) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "console.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute("CREATE TABLE probe_fixture (value INTEGER)")
                connection.execute("INSERT INTO probe_fixture VALUES (7)")
            original_bytes = database_path.read_bytes()
            checker = _sqlite_checker(database_path)
            app = self._build_app(checker=checker)
            async with await self._client(app) as client:
                response = await client.post(
                    "/api/v1/system/bootstrap/database-check",
                    json={"kind": "sqlite"},
                    headers=self._headers(nonce),
                    cookies=self._cookies(nonce),
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "reachable"})
            self.assertEqual(database_path.read_bytes(), original_bytes)

    async def test_authorized_api_reports_missing_sqlite_without_creating_it(
        self,
    ) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "not-created.db"
            checker = _sqlite_checker(database_path)
            app = self._build_app(checker=checker)
            async with await self._client(app) as client:
                response = await client.post(
                    "/api/v1/system/bootstrap/database-check",
                    json={"kind": "sqlite"},
                    headers=self._headers(nonce),
                    cookies=self._cookies(nonce),
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {"status": "unreachable", "reason": "connection"},
            )
            self.assertFalse(database_path.exists())

    async def test_sqlite_probe_has_no_path_or_write_fields(self) -> None:
        nonce = IssueCsrfNonce().execute(None).value
        checker = _Checker(BootstrapDatabaseCheckResult(reachable=True))
        async with await self._client(self._build_app(checker=checker)) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/database-check",
                json={"kind": "sqlite"},
                headers=self._headers(nonce),
                cookies=self._cookies(nonce),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(checker.candidates[0].database, None)
