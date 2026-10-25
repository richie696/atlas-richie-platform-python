"""Authenticated system-protocol read tests against isolated authorities."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.system_protocols_ports import (
    SystemProtocolsAuthorityUnavailable,
)
from atlas_richie.sentinel_console.domain.protocol_negotiations import (
    INCIDENT_EVENTS_V1,
    NegotiatedCompatibility,
    ProtocolNegotiation,
    ProtocolNegotiationPage,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.domain.system_protocols import (
    ProtocolBoundary,
    ProtocolCompatibility,
    ProtocolObservation,
    SystemProtocolsSnapshot,
)

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


class _AgentReportingReader:
    async def read_agent_reporting_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        return ProtocolNegotiationPage(
            as_of=as_of,
            page=page,
            page_size=page_size,
            total=1,
            items=(
                ProtocolNegotiation(
                    certificate_principal="private-principal-not-returned",
                    reporter_id="reporter-a",
                    environment_id="prod",
                    app_id="orders",
                    instance_id="orders-worker-0",
                    process_id="pid-0",
                    runtime_version=None,
                    collector_supported=("atlas-richie.reporting/v1",),
                    compatibility=NegotiatedCompatibility.UNKNOWN,
                    observed_at=None,
                ),
            ),
        )


class _IncidentEventReader:
    async def read_incident_event_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        return ProtocolNegotiationPage(
            as_of=as_of,
            page=page,
            page_size=page_size,
            total=1,
            items=(
                ProtocolNegotiation(
                    certificate_principal="private-principal-not-returned",
                    reporter_id="reporter-a",
                    environment_id="prod",
                    app_id="orders",
                    instance_id="orders-worker-0",
                    process_id="pid-0",
                    runtime_version=INCIDENT_EVENTS_V1,
                    collector_supported=(INCIDENT_EVENTS_V1,),
                    compatibility=NegotiatedCompatibility.COMPATIBLE,
                    observed_at=as_of,
                ),
            ),
        )


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
    agent_reporting_negotiation_reader=None,
    incident_event_negotiation_reader=None,
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
        agent_reporting_negotiation_reader=agent_reporting_negotiation_reader,
        incident_event_negotiation_reader=incident_event_negotiation_reader,
    )


class SystemProtocolsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_versioned_read_preserves_per_worker_unknown_without_leaking_principal(
        self,
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app(
                    "view",
                    agent_reporting_negotiation_reader=_AgentReportingReader(),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v2/system/protocol-observations/agent-reporting?page=1&pageSize=10",
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "protocol-read-1")
        self.assertEqual(response.headers["cache-control"], "no-store")
        assert_openapi_response("readAgentReportingProtocolObservations", response)
        body = response.json()
        self.assertEqual(
            {key: value for key, value in body.items() if key != "asOf"},
            {
                "page": 1,
                "pageSize": 10,
                "total": 1,
                "items": [
                    {
                        "environmentId": "prod",
                        "appId": "orders",
                        "instanceId": "orders-worker-0",
                        "processId": "pid-0",
                        "reporterId": "reporter-a",
                        "boundary": "agent-reporting",
                        "collectorSupported": ["atlas-richie.reporting/v1"],
                        "runtimeVersion": None,
                        "compatibility": "unknown",
                        "observedAt": None,
                    }
                ],
            },
        )
        self.assertTrue(body["asOf"].endswith("Z"))
        self.assertNotIn("private-principal", response.text)

    async def test_incident_event_protocol_read_is_separate_from_agent_reporting(self):
        async with AsyncClient(
            transport=ASGITransport(
                app=_app(
                    "view",
                    agent_reporting_negotiation_reader=_AgentReportingReader(),
                    incident_event_negotiation_reader=_IncidentEventReader(),
                )
            ),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v2/system/protocol-observations/incident-events?page=1&pageSize=10",
                headers=_REQUEST_HEADERS,
            )

        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readIncidentEventProtocolObservations", response)
        self.assertEqual(response.json()["items"][0]["boundary"], "incident-events")
        self.assertEqual(
            response.json()["items"][0]["runtimeVersion"], INCIDENT_EVENTS_V1
        )
        self.assertEqual(response.json()["items"][0]["compatibility"], "compatible")
        self.assertNotIn("private-principal", response.text)

    async def test_versioned_read_rejects_bad_paging_and_anonymous_access(self) -> None:
        for role, query, expected_status in (
            ("view", "?page=0", 400),
            ("view", "?page=1&page=2", 400),
            ("view", "?unknown=value", 400),
            (None, "", 401),
        ):
            async with AsyncClient(
                transport=ASGITransport(
                    app=_app(
                        role,
                        agent_reporting_negotiation_reader=_AgentReportingReader(),
                    )
                ),
                base_url="http://test",
            ) as client:
                if role is not None:
                    client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    f"/api/v2/system/protocol-observations/agent-reporting{query}",
                    headers=_REQUEST_HEADERS,
                )
            self.assertEqual(response.status_code, expected_status)

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
            assert_openapi_response("readSystemProtocols", response)
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
        assert_openapi_response("readSystemProtocols", response)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")
        self.assertEqual(reader.calls, 0)

    async def test_invalid_request_id_is_rejected_before_session_lookup(self) -> None:
        session_reader = _SessionReader("admin")
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", session_reader=session_reader)),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
            response = await client.get(
                "/api/v1/system/protocols",
                headers={"x-request-id": "invalid\nrequest"},
            )

        self.assertEqual(response.status_code, 400)
        assert_openapi_response("readSystemProtocols", response)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    async def test_missing_or_unavailable_authorities_fail_closed(self) -> None:
        cases = (
            (None, 503),
            (_UnavailableProtocolReader(), 503),
        )
        for reader, expected_status in cases:
            async with AsyncClient(
                transport=ASGITransport(app=_app("view", protocol_reader=reader)),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _OPAQUE_COOKIE)
                response = await client.get(
                    "/api/v1/system/protocols", headers=_REQUEST_HEADERS
                )
            self.assertEqual(response.status_code, expected_status)
            assert_openapi_response("readSystemProtocols", response)
            self.assertEqual(response.json()["error"]["code"], "service_unavailable")
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
        assert_openapi_response("readSystemProtocols", response)
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
        assert_openapi_response("readSystemProtocols", response)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private session-store detail", response.text)

    async def test_protocol_domain_rejects_inconsistent_or_future_facts(self) -> None:
        for invalid_identifier in ("\x1c", "\x85", "\ufeff", "\u3000", "\ud800"):
            with (
                self.subTest(identifier=repr(invalid_identifier)),
                self.assertRaises(ValueError),
            ):
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
