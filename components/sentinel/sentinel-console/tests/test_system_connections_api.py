"""Authenticated system connection observation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.system_connections_ports import (
    SystemConnectionsAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.domain.system_connections import (
    ConnectionCapability,
    ConnectionFailureReason,
    ConnectionKind,
    ConnectionObservation,
    ConnectionState,
    SystemConnectionsSnapshot,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "connection-read-1"}
_OPAQUE_COOKIE = "synthetic-session-token-for-console-read-0001"
_AS_OF = datetime(2026, 10, 9, 1, 2, 3, 456789, tzinfo=UTC)


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
            raise SessionAuthorityUnavailable("private session-store detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _ConnectionsReader:
    def __init__(self, snapshot: SystemConnectionsSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls = 0

    async def read_system_connections(self) -> SystemConnectionsSnapshot:
        self.calls += 1
        return self.snapshot


class _UnavailableConnectionsReader:
    async def read_system_connections(self) -> SystemConnectionsSnapshot:
        raise SystemConnectionsAuthorityUnavailable("private probe detail")


class _InvalidConnectionsReader:
    async def read_system_connections(self):
        return None


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("connection read must not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("connection read must not access accounts")


def _snapshot() -> SystemConnectionsSnapshot:
    checked_at = _AS_OF - timedelta(seconds=2)
    return SystemConnectionsSnapshot(
        as_of=_AS_OF,
        items=(
            ConnectionObservation(
                "source-1",
                ConnectionKind.CONFIG_CENTER,
                "source-1",
                ConfigurationSourceProvider.NACOS,
                ConnectionState.AVAILABLE,
                checked_at,
                _AS_OF + timedelta(seconds=30),
                4.5,
                (ConnectionCapability.READ, ConnectionCapability.WATCH),
                None,
            ),
            ConnectionObservation(
                "reporting-collector",
                ConnectionKind.REPORTING_COLLECTOR,
                None,
                None,
                ConnectionState.UNKNOWN,
                None,
                None,
                None,
                (),
                ConnectionFailureReason.NO_PROBE,
            ),
        ),
    )


def _app(role: str | None, *, reader=None, session_reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        system_connections_reader=reader,
    )


class SystemConnectionsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_connection_domain_rejects_blank_and_non_scalar_identifiers(self) -> None:
        for invalid_identifier in ("\x1c", "\x85", "\ufeff", "\u3000", "\ud800"):
            with self.subTest(identifier=repr(invalid_identifier)), self.assertRaises(ValueError):
                ConnectionObservation(
                    invalid_identifier,
                    ConnectionKind.METRICS_BACKEND,
                    None,
                    None,
                    ConnectionState.UNCONFIGURED,
                    None,
                    None,
                    None,
                    (),
                    None,
                )

    async def test_authenticated_roles_receive_safe_probe_facts(self) -> None:
        for role in ("admin", "view"):
            reader = _ConnectionsReader()
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/connections", headers=_REQUEST_HEADERS
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["x-request-id"], "connection-read-1")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            self.assertEqual(
                response.json(),
                {
                    "asOf": "2026-10-09T01:02:03.456Z",
                    "items": [
                        {
                            "id": "source-1",
                            "kind": "config-center",
                            "sourceId": "source-1",
                            "provider": "nacos",
                            "state": "available",
                            "checkedAt": "2026-10-09T01:02:01.456Z",
                            "expiresAt": "2026-10-09T01:02:33.456Z",
                            "latencyMs": 4.5,
                            "capabilities": ["read", "watch"],
                            "reason": None,
                        },
                        {
                            "id": "reporting-collector",
                            "kind": "reporting-collector",
                            "sourceId": None,
                            "provider": None,
                            "state": "unknown",
                            "checkedAt": None,
                            "expiresAt": None,
                            "latencyMs": None,
                            "capabilities": [],
                            "reason": "no-probe",
                        },
                    ],
                },
            )
            self.assertNotIn("endpoint", response.text)
            self.assertNotIn("credential", response.text)
            self.assertEqual(reader.calls, 1)

    async def test_anonymous_and_invalid_request_ids_are_rejected(self) -> None:
        for headers, status, code in (
            (_REQUEST_HEADERS, 401, "unauthenticated"),
            ({"x-request-id": "invalid\nrequest"}, 400, "invalid_request"),
        ):
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app(None, reader=_ConnectionsReader())
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/connections", headers=headers
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)

    async def test_missing_and_failed_authorities_return_bounded_503(self) -> None:
        for reader in (None, _UnavailableConnectionsReader()):
            async with AsyncClient(
                transport=ASGITransport(app=_app("view", reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/connections", headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
            self.assertNotIn("private probe detail", response.text)

        async with AsyncClient(
            transport=ASGITransport(
                app=_app("view", reader=_InvalidConnectionsReader())
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/connections", headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_invalid_session_or_probe_authority_fails_closed(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("unavailable", reader=_ConnectionsReader())
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/connections", headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private session-store detail", response.text)

    async def test_domain_rejects_fake_health_and_invalid_latency(self) -> None:
        with self.assertRaises(ValueError):
            ConnectionObservation(
                "metrics",
                ConnectionKind.METRICS_BACKEND,
                None,
                None,
                ConnectionState.AVAILABLE,
                None,
                None,
                None,
                (),
                None,
            )
        checked_at = _AS_OF + timedelta(seconds=1)
        with self.assertRaises(ValueError):
            SystemConnectionsSnapshot(
                _AS_OF,
                (
                    ConnectionObservation(
                        "metrics",
                        ConnectionKind.METRICS_BACKEND,
                        None,
                        None,
                        ConnectionState.AVAILABLE,
                        checked_at,
                        checked_at,
                        4.5,
                        (),
                        None,
                    ),
                ),
            )
        with self.assertRaises(ValueError):
            ConnectionObservation(
                "metrics",
                ConnectionKind.METRICS_BACKEND,
                None,
                None,
                ConnectionState.AVAILABLE,
                _AS_OF,
                _AS_OF + timedelta(seconds=1),
                float("inf"),
                (),
                None,
            )
