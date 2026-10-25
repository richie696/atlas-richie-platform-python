"""Logout protocol tests with isolated in-process authorities."""

from __future__ import annotations

import hashlib
import unittest

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.domain.session import SessionRevocationResult

_COOKIE = "synthetic-session-token-for-console-logout-0001"
_CSRF = "synthetic-csrf-token-for-console-logout-000001"
_ORIGIN = "https://console.test"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _UnusedSessionReader:
    async def read_active_session(self, session_digest: str):
        raise AssertionError("logout route must not read the session projection")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("logout route must not read account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("logout route must not read account directory")


class _SessionRevoker:
    def __init__(self, result=SessionRevocationResult.REVOKED, error=None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, object]] = []

    async def revoke_active_session(
        self,
        session_digest: str,
        csrf_digest: str,
        revoked_at,
    ) -> SessionRevocationResult:
        self.calls.append((session_digest, csrf_digest, revoked_at))
        if self.error is not None:
            raise self.error
        return self.result


def _app(revoker: _SessionRevoker, origins=frozenset({_ORIGIN})):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_SetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_UnusedSessionReader(),
        current_session_revoker=revoker,
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=origins,
    )


class LogoutApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_logout_checks_proof_rejects_secrets_and_deletes_cookie(self) -> None:
        revoker = _SessionRevoker()
        async with AsyncClient(
            transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "origin": _ORIGIN,
                    "x-request-id": "logout-success-1",
                    "x-sentinel-csrf": _CSRF,
                },
            )

        self.assertEqual(response.status_code, 204)
        assert_openapi_response("logout", response)
        self.assertEqual(response.content, b"")
        self.assertEqual(response.headers["x-request-id"], "logout-success-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie, Origin")
        deleted_cookies = response.headers.get_list("set-cookie")
        self.assertEqual(len(deleted_cookies), 2)
        self.assertIn("sentinel_session=", deleted_cookies[0].lower())
        self.assertIn("__host-sentinel_csrf=", deleted_cookies[1].lower())
        self.assertIn("samesite=lax", deleted_cookies[0].lower())
        self.assertIn("samesite=strict", deleted_cookies[1].lower())
        for deleted_cookie in deleted_cookies:
            cookie = deleted_cookie.lower()
            self.assertIn("max-age=0", cookie)
            self.assertIn("path=/", cookie)
            self.assertIn("secure", cookie)
            self.assertIn("httponly", cookie)
            self.assertIn("samesite=", cookie)
        self.assertEqual(len(revoker.calls), 1)
        session_digest, csrf_digest, revoked_at = revoker.calls[0]
        self.assertEqual(session_digest, hashlib.sha256(_COOKIE.encode()).hexdigest())
        self.assertEqual(csrf_digest, hashlib.sha256(_CSRF.encode()).hexdigest())
        self.assertIsNotNone(revoked_at.tzinfo)
        self.assertNotIn(_COOKIE, response.text)
        self.assertNotIn(_CSRF, response.text)

    async def test_exact_origin_is_required_before_revocation(self) -> None:
        for origin in (None, "null", "https://console.test.attacker"):
            revoker = _SessionRevoker()
            headers = {
                "x-request-id": "logout-origin-1",
                "x-sentinel-csrf": _CSRF,
            }
            if origin is not None:
                headers["origin"] = origin
            async with AsyncClient(
                transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
            ) as client:
                client.cookies.set("sentinel_session", _COOKIE)
                response = await client.post("/api/v1/auth/logout", headers=headers)
            self.assertEqual(response.status_code, 403)
            assert_openapi_response("logout", response)
            self.assertEqual(response.json()["error"]["code"], "csrf_failed")
            self.assertEqual(revoker.calls, [])

        revoker = _SessionRevoker()
        async with AsyncClient(
            transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            response = await client.post(
                "/api/v1/auth/logout",
                headers=[
                    ("origin", _ORIGIN),
                    ("origin", "https://attacker.test"),
                    ("x-request-id", "logout-duplicate-origin-1"),
                    ("x-sentinel-csrf", _CSRF),
                ],
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(revoker.calls, [])

    async def test_missing_proof_rejects_without_storage_write(self) -> None:
        for cookie, csrf, expected_status, expected_code in (
            (None, _CSRF, 401, "unauthenticated"),
            (_COOKIE, None, 403, "csrf_failed"),
            (_COOKIE, "short", 403, "csrf_failed"),
            (_COOKIE, "different-csrf-token-for-testing-00001", 403, "csrf_failed"),
        ):
            revoker = _SessionRevoker()
            async with AsyncClient(
                transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
            ) as client:
                if cookie is not None:
                    client.cookies.set("sentinel_session", cookie)
                client.cookies.set("__Host-sentinel_csrf", _CSRF)
                headers = {"origin": _ORIGIN, "x-request-id": "logout-negative-1"}
                if csrf is not None:
                    headers["x-sentinel-csrf"] = csrf
                response = await client.post("/api/v1/auth/logout", headers=headers)
            self.assertEqual(response.status_code, expected_status)
            self.assertEqual(response.json()["error"]["code"], expected_code)
            self.assertEqual(revoker.calls, [])

    async def test_bounded_failures_and_invalid_request_id_skip_storage(self) -> None:
        cases = (
            (
                _SessionRevoker(SessionRevocationResult.CSRF_FAILED),
                "logout-csrf-1",
                403,
                "csrf_failed",
            ),
            (
                _SessionRevoker(error=SessionAuthorityUnavailable("private db detail")),
                "logout-store-1",
                503,
                "service_unavailable",
            ),
            (
                _SessionRevoker(result="unexpected"),
                "logout-invalid-result-1",
                503,
                "service_unavailable",
            ),
            (_SessionRevoker(), "bad\nrequest-id", 400, "invalid_request"),
        )
        for revoker, request_id, status, error_code in cases:
            async with AsyncClient(
                transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
            ) as client:
                client.cookies.set("sentinel_session", _COOKIE)
                client.cookies.set("__Host-sentinel_csrf", _CSRF)
                response = await client.post(
                    "/api/v1/auth/logout",
                    headers={
                        "origin": _ORIGIN,
                        "x-request-id": request_id,
                        "x-sentinel-csrf": _CSRF,
                    },
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], error_code)
            self.assertNotIn("private db detail", response.text)
            if error_code == "validation_failed":
                self.assertEqual(revoker.calls, [])

    async def test_duplicate_csrf_headers_are_rejected_before_storage(self) -> None:
        revoker = _SessionRevoker()
        async with AsyncClient(
            transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/logout",
                headers=[
                    ("origin", _ORIGIN),
                    ("x-request-id", "logout-duplicate-csrf-1"),
                    ("x-sentinel-csrf", _CSRF),
                    ("x-sentinel-csrf", "other-valid-csrf-value-000000000000"),
                ],
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(revoker.calls, [])

    async def test_duplicate_session_cookies_are_rejected_before_storage(self) -> None:
        revoker = _SessionRevoker()
        async with AsyncClient(
            transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
        ) as client:
            response = await client.post(
                "/api/v1/auth/logout",
                headers=[
                    ("origin", _ORIGIN),
                    ("x-request-id", "logout-duplicate-cookie-1"),
                    ("x-sentinel-csrf", _CSRF),
                    (
                        "cookie",
                        (
                            f"sentinel_session={_COOKIE}; sentinel_session={_COOKIE}; "
                            f"__Host-sentinel_csrf={_CSRF}"
                        ),
                    ),
                ],
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(revoker.calls, [])

    async def test_duplicate_csrf_cookies_are_rejected_before_storage(self) -> None:
        revoker = _SessionRevoker()
        async with AsyncClient(
            transport=ASGITransport(app=_app(revoker)), base_url=_ORIGIN
        ) as client:
            response = await client.post(
                "/api/v1/auth/logout",
                headers=[
                    ("origin", _ORIGIN),
                    ("x-request-id", "logout-duplicate-csrf-cookie-1"),
                    ("x-sentinel-csrf", _CSRF),
                    (
                        "cookie",
                        (
                            f"sentinel_session={_COOKIE}; "
                            f"__Host-sentinel_csrf={_CSRF}; "
                            f"__Host-sentinel_csrf={_CSRF}"
                        ),
                    ),
                ],
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(revoker.calls, [])

    async def test_origin_configuration_is_explicit_and_normalized(self) -> None:
        with self.assertRaises(ValueError):
            _app(_SessionRevoker(), frozenset())
        with self.assertRaises(ValueError):
            _app(_SessionRevoker(), frozenset({"https://console.test/path"}))

        revoker = _SessionRevoker()
        async with AsyncClient(
            transport=ASGITransport(
                app=_app(revoker, frozenset({"HTTPS://Console.Test:443/"}))
            ),
            base_url=_ORIGIN,
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "origin": _ORIGIN,
                    "x-request-id": "logout-origin-normalized-1",
                    "x-sentinel-csrf": _CSRF,
                },
            )
        self.assertEqual(response.status_code, 204)
