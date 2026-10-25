"""HTTP contract checks for authenticated HOST metrics reads."""

from __future__ import annotations

import asyncio
import hashlib
import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.domain.host_metrics import (
    HostMetricQuality,
    HostMetricReason,
    HostMetricsSnapshot,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from openapi_contract_support import assert_openapi_response

_COOKIE = "host-metrics-session-token-00000000000000000001"
_FROM = "2026-10-17T00:00:00.000Z"
_TO = "2026-10-17T00:01:00.000Z"


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetup:
    async def is_setup_window_open(self) -> bool:
        return False


class _Verifier:
    async def is_current_operator(self, _opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    async def read_active_session(self, session_digest: str):
        if session_digest != hashlib.sha256(_COOKIE.encode()).hexdigest():
            return None
        return ActiveAccountSession("account-1", "viewer", "view", "epoch-1")


class _AccountDirectory:
    async def list_accounts(self, _query):
        raise AssertionError("host metrics must not read account directory")

    async def read_account(self, _account_id):
        raise AssertionError("host metrics must not read account directory")


class _Registry:
    def __init__(self) -> None:
        self.source = MonitoringSource(
            source_id="node-exporter",
            revision="rev-1",
            display_name="Linux hosts",
            environment_id="e2e",
            endpoint="http://127.0.0.1:9090",
            provider=MonitoringProvider.PROMETHEUS_COMPATIBLE,
            profile=MonitoringProfile.NODE_EXPORTER_V1,
            authentication_mode=MonitoringAuthenticationMode.NONE,
            credential_configured=False,
            enabled=True,
            identity_labels=("host",),
            selector_labels=(MonitoringLabel("job", "node-exporter"),),
            scrape_interval_seconds=15,
            stale_after_seconds=90,
        )

    async def read_monitoring_source(self, source_id: str):
        if source_id != self.source.source_id:
            from atlas_richie.sentinel_console.application.monitoring_source_registry import (
                MonitoringSourceNotFound,
            )

            raise MonitoringSourceNotFound
        return self.source


class _QueryPort:
    def __init__(self) -> None:
        self.calls = []

    async def read_host_metrics(self, source, query, credentials):
        self.calls.append((source, query, credentials))
        return HostMetricsSnapshot(
            source.source_id,
            source.environment_id,
            query,
            datetime(2026, 10, 17, 0, 1, tzinfo=UTC),
            HostMetricQuality.NO_SAMPLES,
            HostMetricReason.MISSING_SAMPLES,
            (),
        )


def _app(query_port: _QueryPort):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_ClosedSetup(),
        bootstrap_operator_verifier=_Verifier(),
        current_session_reader=_SessionReader(),
        current_session_revoker=_AccountDirectory(),
        account_directory_reader=_AccountDirectory(),
        allowed_browser_origins=frozenset({"http://testserver"}),
        monitoring_source_registry=_Registry(),
        monitoring_host_metrics_query_port=query_port,
    )


class HostMetricsApiTests(unittest.TestCase):
    def test_viewer_can_read_bounded_no_sample_result(self) -> None:
        async def run() -> None:
            query_port = _QueryPort()
            async with AsyncClient(
                transport=ASGITransport(app=_app(query_port)),
                base_url="http://testserver",
                cookies={"sentinel_session": _COOKIE},
            ) as client:
                response = await client.get(
                    "/api/v2/monitoring/sources/node-exporter/host-metrics",
                    params={"from": _FROM, "to": _TO, "stepMs": "10000"},
                    headers={"x-request-id": "host-metrics-read-00000001"},
                )

            self.assertEqual(response.status_code, 200, response.text)
            assert_openapi_response("readHostMetrics", response)
            body = response.json()
            self.assertEqual(body["quality"], "no_samples")
            self.assertEqual(body["reason"], "missing_samples")
            self.assertEqual(body["hosts"], [])
            self.assertEqual(len(query_port.calls), 1)
            self.assertEqual(query_port.calls[0][2], None)
            self.assertEqual(query_port.calls[0][1].point_count, 6)

        asyncio.run(run())

    def test_invalid_interval_is_rejected_before_provider_query(self) -> None:
        async def run() -> None:
            query_port = _QueryPort()
            async with AsyncClient(
                transport=ASGITransport(app=_app(query_port)),
                base_url="http://testserver",
            ) as client:
                response = await client.get(
                    "/api/v2/monitoring/sources/node-exporter/host-metrics",
                    params={"from": _TO, "to": _FROM, "stepMs": "10000"},
                    headers={"x-request-id": "host-metrics-read-00000002"},
                    cookies={"sentinel_session": _COOKIE},
                )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(query_port.calls, [])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
