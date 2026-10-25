"""Authenticated HTTP tests for safe monitoring-source candidate checks."""

from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.check_monitoring_source import (
    CheckMonitoringSource,
)
from atlas_richie.sentinel_console.application.monitoring_probe import (
    MonitoringIdentityPreview,
    MonitoringProbeConnection,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
    MonitoringProbeResult,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_SESSION = "monitoring-source-session-token-000000000000001"
_CSRF = "monitoring-source-csrf-token-00000000000000001"


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, _session_digest: str):
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectory:
    async def list_accounts(self, _query):
        return ()

    async def read_account(self, _account_id: str):
        return None


class _Probe:
    def __init__(self) -> None:
        self.calls = []

    async def probe(self, source, credentials=None):
        self.calls.append((source, credentials))
        return MonitoringProbeResult(
            MonitoringProbeConnection.REACHABLE,
            MonitoringProbeQueryApi.AVAILABLE,
            MonitoringProbeProfile.SUPPORTED,
            MonitoringIdentityPreview(3, 3, 0, 0),
        )


class _ReceiptStore:
    def __init__(self) -> None:
        self.items = {}

    async def record_monitoring_probe_receipt(self, receipt) -> None:
        self.items[receipt.check_id] = receipt

    async def read_monitoring_probe_receipt(
        self, check_id, *, actor_id, session_digest, now
    ):
        receipt = self.items.get(check_id)
        if receipt is None or receipt.actor_id != actor_id:
            return None
        if receipt.session_digest != session_digest or receipt.expires_at <= now:
            return None
        return receipt


def _body():
    return {
        "source": {
            "sourceId": "prom-primary",
            "revision": "candidate-1",
            "displayName": "Prometheus",
            "environmentId": "production",
            "endpoint": "https://prometheus.internal:9090",
            "provider": "prometheus-compatible",
            "profile": "node-exporter-v1",
            "authenticationMode": "direct-bearer",
            "credentialConfigured": True,
            "enabled": True,
            "identityLabels": ["instance"],
            "selectorLabels": [],
            "scrapeIntervalSeconds": 15,
            "staleAfterSeconds": 90,
        },
        "credentials": {"bearerToken": "super-secret-token-value"},
    }


def _app(role: str | None, probe=None, store=None):
    store = store or _ReceiptStore()
    checker = (
        CheckMonitoringSource(
            probe,
            store,
            fingerprint_key=b"monitoring-source-test-key-0000000000000000",
        )
        if probe is not None
        else None
    )
    return build_app(
        bootstrap_initialization_reader=object(),
        setup_window_reader=object(),
        bootstrap_operator_verifier=object(),
        current_session_reader=_SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectory(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        monitoring_source_checker=checker,
        monitoring_probe_receipt_reader=store,
    )


class MonitoringSourceChecksApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_admin_probe_returns_safe_facts_and_persists_exact_candidate(self):
        probe = _Probe()
        app = _app("admin", probe)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={
                "sentinel_session": _SESSION,
                "__Host-sentinel_csrf": _CSRF,
            },
        ) as client:
            response = await client.post(
                "/api/v2/monitoring/sources/check",
                json=_body(),
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "monitor-check-1",
                    "x-sentinel-csrf": _CSRF,
                },
            )
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("checkMonitoringSource", response)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-request-id"], "monitor-check-1")
        response_body = response.json()
        self.assertEqual(response_body["sourceId"], "prom-primary")
        self.assertEqual(response_body["result"]["profile"], "supported")
        self.assertEqual(response_body["result"]["identity"]["unique"], 3)
        self.assertNotIn("super-secret-token-value", response.text)
        self.assertNotIn("password", response.text.lower())
        source, credentials = probe.calls[0]
        self.assertEqual(source.endpoint, "https://prometheus.internal:9090")
        self.assertEqual(credentials.bearer_token, "super-secret-token-value")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={
                "sentinel_session": _SESSION,
                "__Host-sentinel_csrf": _CSRF,
            },
        ) as client:
            read_response = await client.get(
                f"/api/v2/monitoring/sources/checks/{response_body['checkId']}",
                headers={"x-request-id": "monitor-check-read-1"},
            )
        self.assertEqual(read_response.status_code, 200)
        assert_openapi_response("readMonitoringSourceCheck", read_response)
        self.assertEqual(read_response.json(), response_body)

    async def test_viewer_cannot_probe_or_disclose_supplied_credentials(self):
        probe = _Probe()
        app = _app("view", probe)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _SESSION, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.post(
                "/api/v2/monitoring/sources/check",
                json=_body(),
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "monitor-check-view-1",
                    "x-sentinel-csrf": _CSRF,
                },
            )
        self.assertEqual(response.status_code, 403)
        assert_openapi_response("checkMonitoringSource", response)
        self.assertEqual(probe.calls, [])
        self.assertNotIn("super-secret-token-value", response.text)

    async def test_invalid_candidate_fails_before_probe(self):
        probe = _Probe()
        app = _app("admin", probe)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _SESSION, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            body = _body()
            body["source"]["identityLabels"] = ["__name__"]
            response = await client.post(
                "/api/v2/monitoring/sources/check",
                json=body,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "monitor-check-invalid-1",
                    "x-sentinel-csrf": _CSRF,
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(probe.calls, [])


if __name__ == "__main__":
    unittest.main()
