"""Session API and persistence checks against isolated SQLite only."""

from __future__ import annotations

import hashlib
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "session-read-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0001"


class _OpenSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, session: ActiveAccountSession | None = None) -> None:
        self.session = session
        self.digests: list[str] = []

    async def read_active_session(
        self, session_digest: str
    ) -> ActiveAccountSession | None:
        self.digests.append(session_digest)
        return self.session


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("session route must not read account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("session route must not read account directory")


def _app(session_reader) -> object:
    class _Initialized:
        async def is_initialized(self) -> bool:
            return True

    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader,
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
    )


class SessionApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_malformed_cookie_is_anonymous(self) -> None:
        reader = _SessionReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(reader)), base_url="http://test"
        ) as client:
            anonymous = await client.get("/api/v1/auth/me", headers=_REQUEST_HEADERS)
            client.cookies.set("sentinel_session", "short-token")
            malformed = await client.get("/api/v1/auth/me", headers=_REQUEST_HEADERS)

        self.assertEqual(anonymous.status_code, 200)
        self.assertIsNone(anonymous.json())
        self.assertEqual(malformed.status_code, 200)
        self.assertIsNone(malformed.json())
        self.assertEqual(reader.digests, [])

    async def test_valid_cookie_is_hashed_and_response_is_safe(self) -> None:
        reader = _SessionReader(
            ActiveAccountSession("account-7", "Admin", "admin", "epoch-7")
        )
        async with AsyncClient(
            transport=ASGITransport(app=_app(reader)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get("/api/v1/auth/me", headers=_REQUEST_HEADERS)

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "session-read-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie")
        self.assertEqual(
            body,
            {
                "accountId": "account-7",
                "username": "Admin",
                "roleId": "admin",
                "capabilities": ["metrics:view", "rules:write"],
                "sessionEpoch": "epoch-7",
            },
        )
        self.assertEqual(
            reader.digests,
            [hashlib.sha256(_OPAQUE_COOKIE.encode("ascii")).hexdigest()],
        )
        self.assertNotIn(_OPAQUE_COOKIE, response.text)
        self.assertNotIn("password", response.text)
        self.assertNotIn("session_hash", response.text)

    async def test_bad_request_id_is_rejected_before_session_lookup(self) -> None:
        reader = _SessionReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(reader)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/auth/me", headers={"x-request-id": "invalid\nrequest"}
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertEqual(reader.digests, [])

    async def test_invalid_persisted_role_fails_closed(self) -> None:
        reader = _SessionReader(
            ActiveAccountSession("account-8", "BadRole", "owner", "epoch-8")
        )
        async with AsyncClient(
            transport=ASGITransport(app=_app(reader)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get("/api/v1/auth/me", headers=_REQUEST_HEADERS)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("owner", response.text)
