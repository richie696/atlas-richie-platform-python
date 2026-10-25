"""ASGI contract tests for the independent Console bootstrap read."""

from __future__ import annotations

import unittest
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from session_test_doubles import UnusedSessionRevoker
from atlas_richie.sentinel_console.application.errors import BootstrapAuthorityUnavailable


class _InitializationReader:
    def __init__(self, initialized: bool | str = False, error: Exception | None = None):
        self.initialized = initialized
        self.error = error
        self.reads = 0

    async def is_initialized(self) -> bool:
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.initialized  # type: ignore[return-value]


class _SetupWindowReader:
    def __init__(self, is_open: bool | str = False, error: Exception | None = None):
        self.is_open = is_open
        self.error = error
        self.reads = 0

    async def is_setup_window_open(self) -> bool:
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.is_open  # type: ignore[return-value]


class _OperatorVerifier:
    def __init__(self, authorized: bool | Exception = False):
        self.authorized = authorized
        self.sessions: list[str | None] = []

    async def is_current_operator(self, opaque_session: str | None) -> bool:
        self.sessions.append(opaque_session)
        if isinstance(self.authorized, Exception):
            raise self.authorized
        return self.authorized


class _AnonymousSessionReader:
    async def read_active_session(self, session_digest: str):
        raise AssertionError("bootstrap route must not read account sessions")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("bootstrap route must not read account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("bootstrap route must not read account directory")


class BootstrapApiTest(unittest.IsolatedAsyncioTestCase):
    async def _client(
        self,
        reader: _InitializationReader,
        verifier: _OperatorVerifier,
        setup_window: _SetupWindowReader | None = None,
    ) -> AsyncClient:
        app = build_app(
            bootstrap_initialization_reader=reader,
            setup_window_reader=(
                setup_window if setup_window is not None else _SetupWindowReader()
            ),
            bootstrap_operator_verifier=verifier,
            current_session_reader=_AnonymousSessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_UnusedAccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
        )
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        )

    async def test_bootstrap_issues_and_reuses_private_csrf_cookie(self) -> None:
        async with await self._client(
            _InitializationReader(initialized=True), _OperatorVerifier()
        ) as client:
            first = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-csrf-1"}
            )
            first_nonce = first.headers["x-sentinel-csrf"]
            self.assertRegex(first_nonce, r"^[A-Za-z0-9_-]{32,256}$")
            self.assertEqual(first.headers["cache-control"], "no-store")
            set_cookie = first.headers["set-cookie"].lower()
            self.assertIn("__host-sentinel_csrf=", set_cookie)
            self.assertIn("secure", set_cookie)
            self.assertIn("httponly", set_cookie)
            self.assertIn("samesite=strict", set_cookie)
            self.assertIn("path=/", set_cookie)
            self.assertNotIn("domain=", set_cookie)

            reused = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-csrf-2"}
            )
            self.assertEqual(reused.headers["x-sentinel-csrf"], first_nonce)

            client.cookies.set("__Host-sentinel_csrf", "invalid")
            rotated = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-csrf-3"}
            )
            self.assertNotEqual(rotated.headers["x-sentinel-csrf"], first_nonce)

    async def test_initialized_is_minimal_and_does_not_read_other_authorities(self) -> None:
        reader = _InitializationReader(initialized=True)
        setup_window = _SetupWindowReader(is_open=True)
        verifier = _OperatorVerifier(authorized=True)
        async with await self._client(reader, verifier, setup_window) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-1"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"initialized": True})
        self.assertEqual(response.headers["x-request-id"], "boot-read-1")
        self.assertEqual(setup_window.reads, 0)
        self.assertEqual(verifier.sessions, [])

    async def test_open_setup_reports_authorization_only_for_this_request_cookie(self) -> None:
        reader = _InitializationReader(initialized=False)
        setup_window = _SetupWindowReader(is_open=True)
        verifier = _OperatorVerifier(authorized=True)
        async with await self._client(reader, verifier, setup_window) as client:
            client.cookies.set("sentinel_bootstrap", "opaque-test-session")
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-2"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "initialized": False,
                "setupAvailable": True,
                "operatorAuthorized": True,
            },
        )
        self.assertEqual(setup_window.reads, 1)
        self.assertEqual(verifier.sessions, ["opaque-test-session"])

    async def test_closed_setup_never_reports_an_operator_grant(self) -> None:
        reader = _InitializationReader(initialized=False)
        setup_window = _SetupWindowReader(is_open=False)
        verifier = _OperatorVerifier(authorized=True)
        async with await self._client(reader, verifier, setup_window) as client:
            client.cookies.set("sentinel_bootstrap", "opaque-test-session")
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-3"}
            )

        self.assertEqual(response.json()["operatorAuthorized"], False)
        self.assertEqual(setup_window.reads, 1)
        self.assertEqual(verifier.sessions, [])

    async def test_missing_or_invalid_request_id_is_rejected_without_reflection(self) -> None:
        reader = _InitializationReader(initialized=False)
        verifier = _OperatorVerifier()
        async with await self._client(reader, verifier) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "bad\nrequest"}
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        response_request_id = response.json()["error"]["requestId"]
        self.assertEqual(response_request_id, response.headers["x-request-id"])
        self.assertNotEqual(response_request_id, "bad\nrequest")
        UUID(response_request_id)
        self.assertEqual(reader.reads, 0)

    async def test_unavailable_initialization_authority_is_not_reported_as_uninitialized(self) -> None:
        reader = _InitializationReader(
            error=BootstrapAuthorityUnavailable("private DSN must not leak")
        )
        verifier = _OperatorVerifier()
        setup_window = _SetupWindowReader(is_open=True)
        async with await self._client(reader, verifier, setup_window) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-4"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"error": {"code": "service_unavailable", "requestId": "boot-read-4"}},
        )
        self.assertNotIn("private DSN", response.text)
        self.assertEqual(setup_window.reads, 0)

    async def test_unavailable_setup_window_authority_fails_closed(self) -> None:
        reader = _InitializationReader(initialized=False)
        setup_window = _SetupWindowReader(
            is_open=False,
            error=BootstrapAuthorityUnavailable("private marker storage error"),
        )
        verifier = _OperatorVerifier()
        async with await self._client(reader, verifier, setup_window) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-5"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private marker storage error", response.text)
        self.assertEqual(verifier.sessions, [])

    async def test_unavailable_operator_authority_is_not_reported_as_unauthorized(self) -> None:
        reader = _InitializationReader(initialized=False)
        verifier = _OperatorVerifier(
            authorized=BootstrapAuthorityUnavailable("private session storage error")
        )
        async with await self._client(reader, verifier, _SetupWindowReader(is_open=True)) as client:
            client.cookies.set("sentinel_bootstrap", "opaque-test-session")
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-6"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private session storage error", response.text)

    async def test_invalid_initialization_authority_result_fails_closed(self) -> None:
        reader = _InitializationReader(initialized="yes")
        verifier = _OperatorVerifier()
        async with await self._client(reader, verifier) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-7"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertEqual(verifier.sessions, [])

    async def test_invalid_setup_window_authority_result_fails_closed(self) -> None:
        reader = _InitializationReader(initialized=False)
        setup_window = _SetupWindowReader(is_open="yes")
        verifier = _OperatorVerifier()
        async with await self._client(reader, verifier, setup_window) as client:
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-8"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertEqual(verifier.sessions, [])

    async def test_invalid_operator_authority_result_fails_closed(self) -> None:
        reader = _InitializationReader(initialized=False)
        verifier = _OperatorVerifier(authorized="yes")  # type: ignore[arg-type]
        async with await self._client(reader, verifier, _SetupWindowReader(is_open=True)) as client:
            client.cookies.set("sentinel_bootstrap", "opaque-test-session")
            response = await client.get(
                "/api/v1/system/bootstrap", headers={"x-request-id": "boot-read-9"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
