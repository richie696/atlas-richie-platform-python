"""Authenticated system-protocol read tests against isolated authorities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.system_protocols_ports import (
    SystemProtocolsAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.domain.system_protocols import (
    ProtocolBoundary,
    ProtocolCompatibility,
    ProtocolObservation,
    SystemProtocolsSnapshot,
)
from session_test_doubles import UnusedSessionRevoker

_REQUEST_HEADERS = {"x-request-id": "protocol-read-1"}
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


class _ProtocolReader:
    def __init__(self, snapshot: SystemProtocolsSnapshot | None = None) -> None:
        self.snapshot = snapshot or _snapshot()
        self.calls = 0

    async def read_system_protocols(self) -> SystemProtocolsSnapshot:
        self.calls += 1
        return self.snapshot


class _UnavailableProtocolReader:
    async def read_system_protocols(self) -> SystemProtocolsSnapshot:
        raise SystemProtocolsAuthorityUnavailable("private runtime detail")


class _InvalidProtocolReader:
    async def read_system_protocols(self):
        return None


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("protocol read must not touch the account directory")

    async def read_account(self, account_id: str):
        raise AssertionError("protocol read must not touch the account directory")


def _snapshot() -> SystemProtocolsSnapshot:
    observed_at = _AS_OF - timedelta(seconds=1)
    return SystemProtocolsSnapshot(
        as_of=_AS_OF,
        items=(
            ProtocolObservation(
                ProtocolBoundary.AGENT_REPORTING,
                ("v1",),
                "v1",
                ProtocolCompatibility.COMPATIBLE,
                observed_at,
            ),
            ProtocolObservation(
                ProtocolBoundary.RULE_CONFIG,
                (),
                None,
                ProtocolCompatibility.UNKNOWN,
                None,
            ),
        ),
    )


def _app(
    role: str | None,
    *,
    protocol_reader=None,
    session_reader=None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        system_protocols_reader=protocol_reader,
    )


class SystemProtocolsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_roles_receive_authoritative_snapshot(self) -> None:
        for role in ("admin", "view"):
            reader = _ProtocolReader()
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, protocol_reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/protocols", headers=_REQUEST_HEADERS
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["x-request-id"], "protocol-read-1")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["vary"], "Cookie")
            self.assertEqual(
                response.json(),
                {
                    "asOf": "2026-10-09T01:02:03.456Z",
                    "items": [
                        {
                            "kind": "agent-reporting",
                            "supported": ["v1"],
                            "active": "v1",
                            "compatibility": "compatible",
                            "observedAt": "2026-10-09T01:02:02.456Z",
                        },
                        {
                            "kind": "rule-config",
                            "supported": [],
                            "active": None,
                            "compatibility": "unknown",
                            "observedAt": None,
                        },
                    ],
                },
            )
            self.assertEqual(reader.calls, 1)

    async def test_anonymous_request_is_rejected_before_authority_read(self) -> None:
        reader = _ProtocolReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, protocol_reader=reader)),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/system/protocols", headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")
        self.assertEqual(reader.calls, 0)

    async def test_invalid_request_id_is_rejected_before_session_lookup(self) -> None:
        session_reader = _SessionReader("admin")
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("admin", session_reader=session_reader)
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/protocols",
                headers={"x-request-id": "invalid\nrequest"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    async def test_missing_or_unavailable_authorities_fail_closed(self) -> None:
        cases = (
            (None, 503),
            (_UnavailableProtocolReader(), 503),
        )
        for reader, expected_status in cases:
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app("view", protocol_reader=reader)
                ),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/protocols", headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, expected_status)
            self.assertEqual(
                response.json()["error"]["code"], "service_unavailable"
            )
            self.assertNotIn("private runtime detail", response.text)

    async def test_invalid_authority_snapshot_maps_to_service_unavailable(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("view", protocol_reader=_InvalidProtocolReader())
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/protocols", headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_session_authority_failure_is_not_anonymous_or_empty(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("unavailable", protocol_reader=_ProtocolReader())
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/protocols", headers=_REQUEST_HEADERS
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private session-store detail", response.text)

    async def test_protocol_domain_rejects_inconsistent_or_future_facts(self) -> None:
        for invalid_identifier in ("\x1c", "\x85", "\ufeff", "\u3000", "\ud800"):
            with self.subTest(identifier=repr(invalid_identifier)), self.assertRaises(ValueError):
                ProtocolObservation(
                    ProtocolBoundary.CLUSTER_TOKEN,
                    (invalid_identifier,),
                    None,
                    ProtocolCompatibility.UNKNOWN,
                    _AS_OF,
                )
        with self.assertRaises(ValueError):
            ProtocolObservation(
                ProtocolBoundary.CLUSTER_TOKEN,
                ("v1",),
                "v2",
                ProtocolCompatibility.COMPATIBLE,
                _AS_OF,
            )
        with self.assertRaises(ValueError):
            SystemProtocolsSnapshot(
                _AS_OF,
                (
                    ProtocolObservation(
                        ProtocolBoundary.CLUSTER_TOKEN,
                        (),
                        "v2",
                        ProtocolCompatibility.UNKNOWN,
                        _AS_OF + timedelta(seconds=1),
                    ),
                ),
            )
