"""Focused deployment-authority tests for bootstrap grants and retry limits."""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from starlette.applications import Starlette

from atlas_richie.sentinel_console.api.bootstrap_authorize import (
    bootstrap_authorize_route,
    bootstrap_local_authorize_route,
)
from atlas_richie.sentinel_console.application.authorize_bootstrap import (
    BootstrapAuthorizationStatus,
)
from atlas_richie.sentinel_console.application.errors import (
    BootstrapAuthorityUnavailable,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    bootstrap_authorization_file_authority as auth_file,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    setup_window_file_store as setup_store,
)

_OPERATOR_CODE = "operator-code-with-at-least-32-characters"
_FINGERPRINT_KEY = b"k" * 32
_CLIENT_ADDRESS = "192.0.2.42"


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 9, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current


class BootstrapAuthorizationFileAuthorityTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.state_path = self.root / "bootstrap-authority.json"
        self.setup_window = setup_store.SetupWindowFileStore(
            self.root / "setup-window.json"
        )
        await self.setup_window.set_setup_window_open(True, expected_revision=None)
        self.clock = _Clock()

    def _authority(
        self,
        *,
        operator_code: str = _OPERATOR_CODE,
        grant_ttl_seconds: int = 60,
        failure_limit: int = 2,
        allow_loopback_without_code: bool = False,
    ):
        return auth_file.BootstrapAuthorizationConfiguration(
            state_path=self.state_path,
            operator_code=operator_code,
            fingerprint_key=_FINGERPRINT_KEY,
            grant_ttl_seconds=grant_ttl_seconds,
            failure_limit=failure_limit,
            allow_loopback_without_code=allow_loopback_without_code,
        ).create_authority(self.setup_window, clock=self.clock)

    async def test_closed_setup_rejects_exchange_without_state_file(self) -> None:
        await self.setup_window.close_setup_window_if_open()

        result = await self._authority().exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)

        self.assertIs(result.status, BootstrapAuthorizationStatus.SETUP_CLOSED)
        self.assertFalse(self.state_path.exists())

    async def test_retry_limit_survives_restart_without_storing_code(self) -> None:
        first_worker = self._authority(failure_limit=1)
        second_worker = self._authority(failure_limit=1)
        wrong_code = "wrong-operator-code-with-at-least-32-chars"

        rejected = await first_worker.exchange(wrong_code, _CLIENT_ADDRESS)
        limited = await second_worker.exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)

        self.assertIs(rejected.status, BootstrapAuthorizationStatus.RATE_LIMITED)
        self.assertIs(limited.status, BootstrapAuthorizationStatus.RATE_LIMITED)
        self.assertGreater(limited.retry_after_ms or 0, 0)
        persisted = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn(wrong_code, persisted)
        self.assertNotIn(_OPERATOR_CODE, persisted)

    async def test_non_ascii_operator_input_is_rejected_without_encoding_failure(
        self,
    ) -> None:
        result = await self._authority().exchange("\ud800" * 32, _CLIENT_ADDRESS)

        self.assertIs(result.status, BootstrapAuthorizationStatus.REJECTED)

    async def test_one_time_grant_is_hashed_and_survives_worker_restart(self) -> None:
        first_worker = self._authority()

        decision = await first_worker.exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)

        self.assertIs(decision.status, BootstrapAuthorizationStatus.GRANTED)
        assert decision.grant is not None
        session = decision.grant.opaque_session
        persisted = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn(session, persisted)
        self.assertTrue(await self._authority().is_current_operator(session))
        rejected_reuse = await self._authority().exchange(
            _OPERATOR_CODE, _CLIENT_ADDRESS
        )
        self.assertIs(rejected_reuse.status, BootstrapAuthorizationStatus.REJECTED)

    async def test_code_free_local_grant_requires_loopback_and_open_setup(self) -> None:
        authority = self._authority(allow_loopback_without_code=True)

        granted = await authority.authorize_local("127.0.0.1")
        remote = await authority.authorize_local("192.0.2.42")

        self.assertIs(granted.status, BootstrapAuthorizationStatus.GRANTED)
        self.assertIs(remote.status, BootstrapAuthorizationStatus.REJECTED)
        assert granted.grant is not None
        self.assertTrue(
            await self._authority(allow_loopback_without_code=True).is_current_operator(
                granted.grant.opaque_session
            )
        )
        await self.setup_window.close_setup_window_if_open()
        closed = await authority.authorize_local("::1")
        self.assertIs(closed.status, BootstrapAuthorizationStatus.SETUP_CLOSED)

    async def test_local_authorize_http_adapter_issues_grant_without_code(self) -> None:
        authority = self._authority(allow_loopback_without_code=True)
        app = Starlette(
            routes=[
                bootstrap_local_authorize_route(
                    authority, frozenset({"https://console.example.test"})
                )
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app, client=("127.0.0.1", 8000)),
            base_url="https://console.example.test",
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            response = await client.post(
                "/api/v1/system/bootstrap/authorize-local",
                json={},
                headers={
                    "origin": "https://console.example.test",
                    "x-request-id": "bootstrap-local-authority-1",
                    "x-sentinel-csrf": "c" * 43,
                },
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("authorizeLocalBootstrap", response)
        self.assertEqual(response.json(), {"authorized": True})

    async def test_local_authorize_http_adapter_rejects_remote_peer(self) -> None:
        authority = self._authority(allow_loopback_without_code=True)
        app = Starlette(
            routes=[
                bootstrap_local_authorize_route(
                    authority, frozenset({"https://console.example.test"})
                )
            ]
        )
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("192.0.2.42", 8000)),
            base_url="https://console.example.test",
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            response = await client.post(
                "/api/v1/system/bootstrap/authorize-local",
                json={},
                headers={
                    "origin": "https://console.example.test",
                    "x-request-id": "bootstrap-local-remote-denied",
                    "x-sentinel-csrf": "c" * 43,
                },
            )

        self.assertEqual(response.status_code, 403)

    async def test_two_workers_cannot_consume_the_same_code(self) -> None:
        first_worker = self._authority()
        second_worker = self._authority()

        first, second = await asyncio.gather(
            first_worker.exchange(_OPERATOR_CODE, "192.0.2.41"),
            second_worker.exchange(_OPERATOR_CODE, "192.0.2.42"),
        )

        self.assertEqual(
            sum(
                decision.status is BootstrapAuthorizationStatus.GRANTED
                for decision in (first, second)
            ),
            1,
        )
        self.assertEqual(
            sum(
                decision.status is BootstrapAuthorizationStatus.REJECTED
                for decision in (first, second)
            ),
            1,
        )

    async def test_expiry_and_closed_window_preserve_receipt_recovery(self) -> None:
        authority = self._authority(grant_ttl_seconds=30)
        decision = await authority.exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)
        assert decision.grant is not None
        session = decision.grant.opaque_session

        await self.setup_window.close_setup_window_if_open()
        self.assertTrue(await self._authority().is_current_operator(session))
        closed = await authority.exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)
        self.assertIs(closed.status, BootstrapAuthorizationStatus.SETUP_CLOSED)

        self.clock.current += timedelta(seconds=30)
        self.assertFalse(await authority.is_current_operator(session))

    async def test_code_rotation_invalidates_grants_and_allows_new_code(self) -> None:
        previous = self._authority()
        issued = await previous.exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)
        assert issued.grant is not None
        replacement_code = "replacement-code-with-at-least-32-chars"
        rotated = self._authority(operator_code=replacement_code)

        self.assertFalse(await rotated.is_current_operator(issued.grant.opaque_session))
        new_grant = await rotated.exchange(replacement_code, _CLIENT_ADDRESS)
        self.assertIs(new_grant.status, BootstrapAuthorizationStatus.GRANTED)

    async def test_file_authority_runs_through_authorize_http_adapter(self) -> None:
        authority = self._authority()
        app = Starlette(
            routes=[
                bootstrap_authorize_route(
                    authority, frozenset({"https://console.example.test"})
                )
            ]
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.example.test",
        ) as client:
            client.cookies.set("__Host-sentinel_csrf", "c" * 43)
            response = await client.post(
                "/api/v1/system/bootstrap/authorize",
                json={"operatorCode": _OPERATOR_CODE},
                headers={
                    "origin": "https://console.example.test",
                    "x-request-id": "bootstrap-file-authority-1",
                    "x-sentinel-csrf": "c" * 43,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authorized": True})
        self.assertNotIn(_OPERATOR_CODE, response.text)
        cookie_headers = response.headers.get_list("set-cookie")
        grant_cookie = SimpleCookie()
        for header in cookie_headers:
            grant_cookie.load(header)
        grant = grant_cookie["sentinel_bootstrap"].value
        self.assertTrue(await self._authority().is_current_operator(grant))
        self.assertNotIn(grant, self.state_path.read_text(encoding="utf-8"))

    async def test_corrupt_state_fails_closed_without_details(self) -> None:
        self.state_path.write_bytes(b"{broken")
        os.chmod(self.state_path, 0o600)

        with self.assertRaises(BootstrapAuthorityUnavailable) as error:
            await self._authority().exchange(_OPERATOR_CODE, _CLIENT_ADDRESS)

        self.assertNotIn("JSON", str(error.exception))
        self.assertNotIn("broken", str(error.exception))

    def test_environment_configuration_is_required_and_hides_secrets(self) -> None:
        values = {
            "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(self.state_path),
            "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE": _OPERATOR_CODE,
            "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": base64.b64encode(
                _FINGERPRINT_KEY
            ).decode("ascii"),
        }

        config = auth_file.BootstrapAuthorizationConfiguration.from_environment(values)

        self.assertNotIn(_OPERATOR_CODE, repr(config))
        self.assertNotIn(base64.b64encode(_FINGERPRINT_KEY).decode(), repr(config))

    def test_environment_allows_missing_code_only_with_loopback_policy(self) -> None:
        values = {
            "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(self.state_path),
            "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": base64.b64encode(
                _FINGERPRINT_KEY
            ).decode("ascii"),
        }

        with self.assertRaises(auth_file.BootstrapAuthorizationConfigurationError):
            auth_file.BootstrapAuthorizationConfiguration.from_environment(values)
        local = auth_file.BootstrapAuthorizationConfiguration.from_environment(
            values, allow_loopback_without_code=True
        )
        self.assertTrue(local.allow_loopback_without_code)
        self.assertNotIn(local.operator_code, repr(local))
        self.assertTrue(
            auth_file.loopback_bootstrap_without_code_allowed(
                {
                    "SENTINEL_CONSOLE_BIND_HOST": "127.0.0.1",
                    "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "http://127.0.0.1:8000,http://localhost:8000",
                }
            )
        )
        self.assertFalse(
            auth_file.loopback_bootstrap_without_code_allowed(
                {
                    "SENTINEL_CONSOLE_BIND_HOST": "127.0.0.1",
                    "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "https://console.example.test",
                }
            )
        )
        self.assertFalse(
            auth_file.loopback_bootstrap_without_code_allowed(
                {
                    "SENTINEL_CONSOLE_BIND_HOST": "127.0.0.1",
                    "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "http://localhost:8000",
                    "SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS": "127.0.0.1/32",
                }
            )
        )
        with self.assertRaises(auth_file.BootstrapAuthorizationConfigurationError):
            auth_file.BootstrapAuthorizationConfiguration.from_environment({})


if __name__ == "__main__":
    import unittest

    unittest.main()
