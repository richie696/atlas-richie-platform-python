"""HTTP contract tests for bootstrap operator-code exchange."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.authorize_bootstrap import (
    BootstrapAuthorizationDecision,
    BootstrapAuthorizationStatus,
    BootstrapOperatorGrant,
)
from atlas_richie.sentinel_console.application.errors import (
    BootstrapAuthorityUnavailable,
)
from session_test_doubles import UnusedSessionRevoker


class _InitializationReader:
    async def is_initialized(self) -> bool:
        return False


class _SetupWindowReader:
    async def is_setup_window_open(self) -> bool:
        return True


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    async def read_active_session(self, session_digest: str):
        return None


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        return ()

    async def read_account(self, account_id: str):
        return None


class _Authority:
    def __init__(self, decision: BootstrapAuthorizationDecision) -> None:
        self.decision = decision
        self.codes: list[str] = []
        self.addresses: list[str] = []

    async def exchange(self, operator_code: str, client_address: str):
        self.codes.append(operator_code)
        self.addresses.append(client_address)
        return self.decision


class _UnavailableAuthority:
    async def exchange(self, operator_code: str, client_address: str):
        raise BootstrapAuthorityUnavailable("private storage failure")


class BootstrapAuthorizeApiTest(unittest.IsolatedAsyncioTestCase):
    def _build_app(self, authority=None):
        return build_app(
            bootstrap_initialization_reader=_InitializationReader(),
            setup_window_reader=_SetupWindowReader(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=_SessionReader(),
            current_session_revoker=UnusedSessionRevoker(),
            account_directory_reader=_AccountDirectoryReader(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            bootstrap_authorization_authority=authority,
        )

    async def _client(self, app):
        return AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        )

    @staticmethod
    def _headers(*, origin: str = "https://console.test"):
        return {
            "origin": origin,
            "x-request-id": "bootstrap-auth-1",
            "x-sentinel-csrf": "c" * 43,
        }

    @staticmethod
    def _body(code: str = "one-time-setup-code-with-32-char-minimum"):
        return {"operatorCode": code}

    async def test_grant_sets_bounded_cookies_and_never_echoes_code(self) -> None:
        authority = _Authority(
            BootstrapAuthorizationDecision(
                BootstrapAuthorizationStatus.GRANTED,
                BootstrapOperatorGrant("g" * 43, expires_in_seconds=300),
            )
        )
        async with await self._client(self._build_app(authority)) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            response = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json=self._body(),
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authorized": True})
        self.assertEqual(authority.codes, ["one-time-setup-code-with-32-char-minimum"])
        self.assertEqual(authority.addresses, ["127.0.0.1"])
        self.assertNotIn("one-time-setup-code", response.text)
        cookies = response.headers.get_list("set-cookie")
        self.assertEqual(len(cookies), 2)
        grant_cookie = next(
            value for value in cookies if value.startswith("sentinel_bootstrap=")
        )
        csrf_cookie = next(
            value for value in cookies if value.startswith("__Host-sentinel_csrf=")
        )
        for value in (grant_cookie, csrf_cookie):
            self.assertIn("HttpOnly", value)
            self.assertIn("Secure", value)
            self.assertIn("SameSite=strict", value)
            self.assertIn("Max-Age=300", value)
        self.assertNotIn("g" * 43, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_wrong_origin_and_malformed_payload_are_rejected(self) -> None:
        authority = _Authority(
            BootstrapAuthorizationDecision(BootstrapAuthorizationStatus.REJECTED)
        )
        async with await self._client(self._build_app(authority)) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            wrong_origin = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json=self._body(),
                headers=self._headers(origin="https://attacker.test"),
            )
            malformed = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json={**self._body(), "unexpected": "field"},
                headers=self._headers(),
            )
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(authority.codes, [])

    async def test_operator_code_syntax_is_rejected_before_authority_exchange(self) -> None:
        authority = _Authority(
            BootstrapAuthorizationDecision(BootstrapAuthorizationStatus.REJECTED)
        )
        invalid_codes = (
            "x" * 31,
            "x" * 32 + "🌋",
            " " + "x" * 32,
            "x" * 32 + "\ufeff",
            "x" * 1025,
        )
        async with await self._client(self._build_app(authority)) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            responses = [
                await client.post(
                    "/api/v1/system/bootstrap/authorize",
                    json=self._body(code),
                    headers=self._headers(),
                )
                for code in invalid_codes
            ]
        self.assertEqual([response.status_code for response in responses], [400] * 5)
        self.assertTrue(
            all(response.json()["error"]["code"] == "invalid_request" for response in responses)
        )
        self.assertEqual(authority.codes, [])

    async def test_authorize_requires_bootstrap_csrf_cookie_header_pair(self) -> None:
        authority = _Authority(
            BootstrapAuthorizationDecision(BootstrapAuthorizationStatus.REJECTED)
        )
        async with await self._client(self._build_app(authority)) as client:
            response = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json=self._body(),
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "bootstrap-auth-csrf",
                    "x-sentinel-csrf": "c" * 43,
                },
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "csrf_failed")
        self.assertEqual(authority.codes, [])

    async def test_finite_rejections_are_mapped_without_grant_cookie(self) -> None:
        decisions = (
            (BootstrapAuthorizationStatus.REJECTED, 403, "forbidden"),
            (BootstrapAuthorizationStatus.SETUP_CLOSED, 409, "conflict"),
            (BootstrapAuthorizationStatus.RATE_LIMITED, 429, "rate_limited"),
        )
        for status, expected_status, expected_code in decisions:
            with self.subTest(status=status):
                authority = _Authority(
                    BootstrapAuthorizationDecision(
                        status,
                        retry_after_ms=(
                            500
                            if status is BootstrapAuthorizationStatus.RATE_LIMITED
                            else None
                        ),
                    )
                )
                async with await self._client(self._build_app(authority)) as client:
                    client.cookies.set("__Host-sentinel_csrf", "c" * 43)
                    response = await client.post(
                        "/api/v1/system/bootstrap/authorize",
                        json=self._body(),
                        headers=self._headers(),
                    )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["error"]["code"], expected_code)
                self.assertNotIn("set-cookie", response.headers)

    async def test_missing_and_unavailable_authorities_fail_closed(self) -> None:
        async with await self._client(self._build_app()) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            missing = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json=self._body(),
                headers=self._headers(),
            )
        app = self._build_app(_UnavailableAuthority())
        async with await self._client(app) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            unavailable = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json=self._body(),
                headers=self._headers(),
            )
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(unavailable.status_code, 503)
        self.assertNotIn("private storage failure", unavailable.text)

    def test_grant_duration_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            BootstrapOperatorGrant("grant", expires_in_seconds=901)
