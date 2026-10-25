"""System display settings read and administrator-only time zone update."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from openapi_contract_support import assert_openapi_response

_ORIGIN = "https://console.test"
_SESSION_COOKIE = "synthetic-system-settings-admin-session-token-001"
_VIEW_SESSION_COOKIE = "synthetic-system-settings-view-session-token-0001"
_CSRF = "synthetic-system-settings-admin-csrf-token-000001"


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
            raise SessionAuthorityUnavailable("private session detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("system settings reads do not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("system settings reads do not access accounts")


class _SettingsStore:
    """In-memory stand-in for the persisted Console system settings row."""

    def __init__(
        self,
        *,
        time_zone: str = "Asia/Shanghai",
        revision: int = 3,
        unavailable: bool = False,
    ) -> None:
        self.time_zone = time_zone
        self.revision = revision
        self.unavailable = unavailable
        self.written: list[str] = []

    async def read_time_zone(self) -> tuple[str, int]:
        if self.unavailable:
            raise RuntimeError("private settings detail")
        return self.time_zone, self.revision

    async def update_time_zone(self, time_zone: str) -> tuple[str, int]:
        if self.unavailable:
            raise RuntimeError("private settings detail")
        self.written.append(time_zone)
        self.time_zone = time_zone
        self.revision += 1
        return self.time_zone, self.revision


def _app(role: str | None, store: _SettingsStore):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=_SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({_ORIGIN}),
        system_settings_store=store,
    )


def _write_headers(request_id: str) -> dict[str, str]:
    return {
        "origin": _ORIGIN,
        "x-request-id": request_id,
        "x-sentinel-csrf": _CSRF,
        "content-type": "application/json",
    }


class SystemSettingsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_reader_sees_the_configured_time_zone(self):
        store = _SettingsStore()
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", store)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _VIEW_SESSION_COOKIE)
            response = await client.get(
                "/api/v1/system/settings",
                headers={"x-request-id": "settings-read-view"},
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readSystemSettings", response)
        self.assertEqual(response.json(), {"timeZone": "Asia/Shanghai", "revision": 3})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie")

    async def test_anonymous_reader_is_rejected_before_the_store_is_read(self):
        store = _SettingsStore()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, store)), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/system/settings",
                headers={"x-request-id": "settings-read-anonymous"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(store.written, [])

    async def test_unavailable_store_returns_redacted_service_error(self):
        store = _SettingsStore(unavailable=True)
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _SESSION_COOKIE)
            response = await client.get(
                "/api/v1/system/settings",
                headers={"x-request-id": "settings-read-unavailable"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private settings detail", response.text)

    async def test_administrator_updates_the_time_zone_and_revision(self):
        store = _SettingsStore()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _SESSION_COOKIE)
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.put(
                "/api/v1/system/settings",
                headers=_write_headers("settings-update-admin"),
                json={"timeZone": "Europe/Berlin"},
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("updateSystemTimeZone", response)
        self.assertEqual(response.json(), {"timeZone": "Europe/Berlin", "revision": 4})
        self.assertEqual(store.written, ["Europe/Berlin"])

    async def test_view_role_cannot_update_the_time_zone(self):
        store = _SettingsStore()
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", store)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _VIEW_SESSION_COOKIE)
            client.cookies.set("__Host-sentinel_csrf", _CSRF)
            response = await client.put(
                "/api/v1/system/settings",
                headers=_write_headers("settings-update-view"),
                json={"timeZone": "Europe/Berlin"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(store.written, [])

    async def test_write_without_browser_proof_is_rejected(self):
        store = _SettingsStore()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store)), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _SESSION_COOKIE)
            response = await client.put(
                "/api/v1/system/settings",
                headers={"x-request-id": "settings-update-no-proof"},
                json={"timeZone": "Europe/Berlin"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(store.written, [])

    async def test_unknown_and_malformed_time_zones_are_rejected_before_the_write(self):
        store = _SettingsStore()
        for request_id, payload in (
            ("settings-update-unknown-zone", {"timeZone": "Mars/Olympus"}),
            ("settings-update-extra-field", {"timeZone": "UTC", "revision": 9}),
            ("settings-update-empty-body", {}),
        ):
            with self.subTest(payload=payload):
                async with AsyncClient(
                    transport=ASGITransport(app=_app("admin", store)), base_url="http://test"
                ) as client:
                    client.cookies.set("sentinel_session", _SESSION_COOKIE)
                    client.cookies.set("__Host-sentinel_csrf", _CSRF)
                    response = await client.put(
                        "/api/v1/system/settings",
                        headers=_write_headers(request_id),
                        json=payload,
                    )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")

        self.assertEqual(store.written, [])


if __name__ == "__main__":
    unittest.main()
