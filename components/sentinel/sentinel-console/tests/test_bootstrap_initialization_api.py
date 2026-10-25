"""Contract tests for initialization command and receipt-recovery routes."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseCandidate,
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.bootstrap_initialization import (
    BootstrapInitializationIdempotencyConflict,
    BootstrapInitializationInput,
    BootstrapInitializationReceipt,
    BootstrapInitializationStatus,
)
from atlas_richie.sentinel_console.application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    BootstrapSourceProvider,
    NoSourceAuthentication,
)
from atlas_richie.sentinel_console.application.issue_csrf_nonce import IssueCsrfNonce
from atlas_richie.sentinel_console.domain.account_password import AccountPassword
from atlas_richie.sentinel_console.domain.account_username import AccountUsername


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return False


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return True


class _ClosedSetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return opaque_session == "operator-session"


class _SessionReader:
    async def read_active_session(self, session_digest: str):
        return None


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class _Initializer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, BootstrapInitializationInput]] = []

    async def initialize(self, *, operator_session, request_key, input):
        self.calls.append((operator_session, request_key, input))
        return BootstrapInitializationReceipt(
            request_key,
            BootstrapInitializationStatus.PENDING,
            "operation-001234",
        )


class _ConflictingInitializer:
    async def initialize(self, *, operator_session, request_key, input):
        raise BootstrapInitializationIdempotencyConflict


class _OperationReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def read(self, operator_session: str, request_key: str):
        self.calls.append((operator_session, request_key))
        return BootstrapInitializationReceipt(
            request_key,
            BootstrapInitializationStatus.COMPLETED,
            "operation-001234",
        )


class BootstrapInitializationApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(
        self, *, initializer=None, operation_reader=None, setup_window_reader=None
    ):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=setup_window_reader or _SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            bootstrap_initializer=initializer,
            bootstrap_initialization_operation_reader=operation_reader,
        )

    async def _client(self, app):
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        )

    @staticmethod
    def _nonce() -> str:
        return IssueCsrfNonce().execute(None).value

    @staticmethod
    def _payload(*, password="secret-password-123"):
        return {
            "requestKey": "setup-request-001",
            "input": {
                "database": {"kind": "sqlite"},
                "admin": {"username": "admin", "password": password},
                "source": {
                    "provider": "nacos",
                    "endpoint": "https://nacos.internal:8848",
                    "namespace": "sentinel",
                    "authentication": {"mode": "none"},
                },
            },
        }

    @staticmethod
    def _headers(nonce: str, request_key="setup-request-001"):
        return {
            "origin": "https://console.test",
            "x-request-id": "bootstrap-init-1",
            "x-sentinel-csrf": nonce,
            "idempotency-key": request_key,
        }

    @staticmethod
    def _cookies(nonce: str, operator_session="operator-session"):
        return {
            "__Host-sentinel_csrf": nonce,
            "sentinel_bootstrap": operator_session,
        }

    def _set_client_cookies(
        self, client: AsyncClient, nonce: str, operator_session="operator-session"
    ) -> None:
        client.cookies.clear()
        client.cookies.update(self._cookies(nonce, operator_session))

    def test_initialization_input_rejects_untyped_authority_values(self):
        valid = {
            "database": BootstrapDatabaseCandidate(BootstrapDatabaseKind.SQLITE),
            "admin_username": AccountUsername("admin"),
            "admin_password": AccountPassword("secret-password-123"),
            "source": BootstrapSourceCandidate(
                provider=BootstrapSourceProvider.NACOS,
                endpoint="https://nacos.internal:8848",
                location="sentinel",
                authentication=NoSourceAuthentication(),
            ),
        }
        for field_name, invalid_value in (
            ("database", {"kind": "sqlite"}),
            ("admin_username", "admin"),
            ("admin_password", "secret-password-123"),
            ("source", {"provider": "nacos"}),
        ):
            with (
                self.subTest(field=field_name),
                self.assertRaises(TypeError),
            ):
                BootstrapInitializationInput(**{**valid, field_name: invalid_value})

    async def test_command_maps_typed_input_and_returns_secret_free_receipt(self):
        nonce = self._nonce()
        initializer = _Initializer()
        app = self._build_app(initializer=initializer)
        async with await self._client(app) as client:
            self._set_client_cookies(client, nonce)
            response = await client.post(
                "/api/v1/system/bootstrap/initialize",
                json=self._payload(),
                headers=self._headers(nonce),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "pending",
                "requestKey": "setup-request-001",
                "operationId": "operation-001234",
            },
        )
        self.assertEqual(len(initializer.calls), 1)
        operator, request_key, command = initializer.calls[0]
        self.assertEqual(
            (operator, request_key), ("operator-session", "setup-request-001")
        )
        self.assertEqual(command.admin_username.value, "admin")
        self.assertEqual(command.source.location, "sentinel")
        self.assertNotIn("secret-password-123", repr(command))
        self.assertNotIn("secret-password-123", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_changed_payload_for_existing_request_key_returns_conflict(self):
        nonce = self._nonce()
        app = self._build_app(initializer=_ConflictingInitializer())
        async with await self._client(app) as client:
            self._set_client_cookies(client, nonce)
            response = await client.post(
                "/api/v1/system/bootstrap/initialize",
                json=self._payload(),
                headers=self._headers(nonce),
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "idempotency_conflict")

    async def test_closed_setup_rejects_later_initialization_as_bootstrap_unauthorized(
        self,
    ):
        nonce = self._nonce()
        initializer = _Initializer()
        app = self._build_app(
            initializer=initializer,
            setup_window_reader=_ClosedSetupWindowReader(),
        )
        async with await self._client(app) as client:
            self._set_client_cookies(client, nonce)
            response = await client.post(
                "/api/v1/system/bootstrap/initialize",
                json=self._payload(),
                headers=self._headers(nonce),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "bootstrap_unauthorized")
        self.assertEqual(initializer.calls, [])

    async def test_database_and_source_credentials_never_escape_command_repr(self):
        nonce = self._nonce()
        initializer = _Initializer()
        payload = {
            "requestKey": "setup-request-001",
            "input": {
                "database": {
                    "kind": "mysql",
                    "host": "db.internal",
                    "port": 3306,
                    "database": "sentinel_console",
                    "username": "console_user",
                    "password": "database-secret-value",
                },
                "admin": {"username": "admin", "password": "admin-secret-value"},
                "source": {
                    "provider": "consul",
                    "endpoint": "https://consul.internal:8501",
                    "datacenter": "dc1",
                    "authentication": {
                        "mode": "direct",
                        "aclToken": "source-secret-value",
                    },
                },
            },
        }
        app = self._build_app(initializer=initializer)
        async with await self._client(app) as client:
            self._set_client_cookies(client, nonce)
            response = await client.post(
                "/api/v1/system/bootstrap/initialize",
                json=payload,
                headers=self._headers(nonce),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(initializer.calls), 1)
        command = initializer.calls[0][2]
        rendered = f"{command!r} {response.text}"
        for credential in (
            "database-secret-value",
            "admin-secret-value",
            "source-secret-value",
        ):
            with self.subTest(credential=credential):
                self.assertNotIn(credential, rendered)

    async def test_request_key_conflict_and_missing_csrf_never_reach_initializer(self):
        initializer = _Initializer()
        scenarios = (
            ("mismatch", self._headers(self._nonce(), "different-key"), 409),
            (
                "csrf",
                {"origin": "https://console.test", "x-request-id": "bootstrap-init-2"},
                403,
            ),
        )
        for name, headers, expected_status in scenarios:
            with self.subTest(name=name):
                nonce = headers.get("x-sentinel-csrf", self._nonce())
                async with await self._client(
                    self._build_app(initializer=initializer)
                ) as client:
                    self._set_client_cookies(client, nonce)
                    response = await client.post(
                        "/api/v1/system/bootstrap/initialize",
                        json=self._payload(),
                        headers=headers,
                    )
                self.assertEqual(response.status_code, expected_status)
        self.assertEqual(initializer.calls, [])

    async def test_invalid_secret_or_source_shape_is_rejected_before_authority(self):
        initializer = _Initializer()
        for payload in (
            self._payload(password="short"),
            {**self._payload(), "unknown": "field"},
        ):
            nonce = self._nonce()
            async with await self._client(
                self._build_app(initializer=initializer)
            ) as client:
                self._set_client_cookies(client, nonce)
                response = await client.post(
                    "/api/v1/system/bootstrap/initialize",
                    json=payload,
                    headers=self._headers(nonce),
                )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(initializer.calls, [])

    async def test_database_wire_boundaries_are_rejected_before_initializer(self):
        initializer = _Initializer()
        invalid_databases = (
            {"kind": "sqlite", "path": "/tmp/browser-selected.db"},
            {
                "kind": "postgresql",
                "host": "🌋" * 127,
                "port": 5432,
                "database": "sentinel_console",
                "username": "console_user",
                "password": "database-secret",
            },
            {
                "kind": "postgresql",
                "host": "db.internal\x1c",
                "port": 5432,
                "database": "sentinel_console",
                "username": "console_user",
                "password": "database-secret",
            },
            {
                "kind": "postgresql",
                "host": "db.internal",
                "port": 5432,
                "database": "sentinel_console",
                "username": "\u0085",
                "password": "database-secret",
            },
            {
                "kind": "postgresql",
                "host": "db.internal",
                "port": 5432,
                "database": "sentinel_console",
                "username": "console_user",
                "password": "🌋" * 513,
            },
        )
        for database in invalid_databases:
            payload = self._payload()
            payload["input"]["database"] = database
            nonce = self._nonce()
            async with await self._client(
                self._build_app(initializer=initializer)
            ) as client:
                self._set_client_cookies(client, nonce)
                response = await client.post(
                    "/api/v1/system/bootstrap/initialize",
                    json=payload,
                    headers=self._headers(nonce),
                )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(initializer.calls, [])

    async def test_operation_read_is_bound_to_verified_bootstrap_grant(self):
        reader = _OperationReader()
        app = self._build_app(operation_reader=reader)
        async with await self._client(app) as client:
            self._set_client_cookies(client, self._nonce())
            accepted = await client.get(
                "/api/v1/system/bootstrap/operations/setup-request-001",
                headers={"x-request-id": "bootstrap-read-1"},
            )
            self._set_client_cookies(client, self._nonce(), "other-session")
            denied = await client.get(
                "/api/v1/system/bootstrap/operations/setup-request-001",
                headers={"x-request-id": "bootstrap-read-2"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "completed")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(reader.calls, [("operator-session", "setup-request-001")])

    async def test_missing_persistence_authorities_fail_closed(self):
        nonce = self._nonce()
        async with await self._client(self._build_app()) as client:
            self._set_client_cookies(client, nonce)
            response = await client.post(
                "/api/v1/system/bootstrap/initialize",
                json=self._payload(),
                headers=self._headers(nonce),
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("secret-password-123", response.text)


if __name__ == "__main__":
    unittest.main()
