"""Opt-in C06/C07 tests against a disposable real Prometheus and exporter."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.check_monitoring_source import (
    CheckMonitoringSource,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import AccountRecord
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_probe_receipt_store import (
    SQLAlchemyMonitoringProbeReceiptStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_source_store import (
    SQLAlchemyMonitoringSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

from atlas_richie.sentinel_console.application.monitoring_probe import (
    MonitoringProbeConnection,
    MonitoringProbeFailure,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_probe_composition import (
    compose_prometheus_http_adapter,
    compose_prometheus_host_metrics_adapter,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_target_policy import (
    MonitoringTargetRule,
)


def _source(endpoint: str, job: str) -> MonitoringSource:
    return MonitoringSource(
        source_id=f"t053-{job}",
        revision="1",
        display_name="Disposable Prometheus acceptance",
        environment_id="t053-acceptance",
        endpoint=endpoint,
        provider=MonitoringProvider.PROMETHEUS_COMPATIBLE,
        profile=MonitoringProfile.NODE_EXPORTER_V1,
        authentication_mode=MonitoringAuthenticationMode.NONE,
        credential_configured=False,
        enabled=True,
        identity_labels=("host",),
        selector_labels=(MonitoringLabel("job", job),),
        scrape_interval_seconds=1,
        stale_after_seconds=10,
    )


class PrometheusLiveIdentityAcceptance(unittest.TestCase):
    """Exercise actual PromQL evaluation and identity aggregation semantics."""

    @unittest.skipUnless(
        os.environ.get("SENTINEL_T053_PROMETHEUS_ENDPOINT"),
        "run via tools/with_disposable_prometheus_acceptance.sh",
    )
    def test_real_prometheus_distinguishes_valid_missing_and_conflicting_hosts(
        self,
    ) -> None:
        endpoint = os.environ.get("SENTINEL_T053_PROMETHEUS_ENDPOINT")
        parsed = urlsplit(endpoint or "")
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed.port)
        assert parsed.port is not None

        rule = MonitoringTargetRule.create(
            "127.0.0.1",
            ("127.0.0.0/8",),
            frozenset({parsed.port}),
            allow_loopback_http=True,
        )
        adapter = compose_prometheus_http_adapter((rule,))

        async def probe_all():
            latest = None
            for _attempt in range(30):
                latest = await asyncio.gather(
                    adapter.probe(_source(endpoint or "", "t053-complete")),
                    adapter.probe(_source(endpoint or "", "t053-missing")),
                    adapter.probe(_source(endpoint or "", "t053-conflicting")),
                )
                if all(
                    result.profile is MonitoringProbeProfile.SUPPORTED
                    for result in latest
                ):
                    return latest
                await asyncio.sleep(0.5)
            self.fail(
                f"Prometheus did not ingest all synthetic profile metrics: {latest!r}"
            )

        complete, missing, conflicting = asyncio.run(probe_all())

        for result in (complete, missing, conflicting):
            self.assertEqual(result.connection, MonitoringProbeConnection.REACHABLE)
            self.assertEqual(result.query_api, MonitoringProbeQueryApi.AVAILABLE)
            self.assertEqual(result.profile, MonitoringProbeProfile.SUPPORTED)

        self.assertEqual(
            (
                complete.identity.observed,
                complete.identity.unique,
                complete.identity.missing,
                complete.identity.conflicting,
            ),
            (1, 1, 0, 0),
        )
        self.assertEqual(
            (
                missing.identity.observed,
                missing.identity.unique,
                missing.identity.missing,
                missing.identity.conflicting,
            ),
            (1, 0, 1, 0),
        )
        self.assertEqual(
            (
                conflicting.identity.observed,
                conflicting.identity.unique,
                conflicting.identity.missing,
                conflicting.identity.conflicting,
            ),
            (1, 0, 0, 1),
        )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_T053_PROMETHEUS_AUTH_ENDPOINT"),
        "run via tools/with_disposable_prometheus_acceptance.sh",
    )
    def test_real_prometheus_authentication_denial_is_classified_without_provider_details(
        self,
    ) -> None:
        endpoint = os.environ.get("SENTINEL_T053_PROMETHEUS_AUTH_ENDPOINT")
        parsed = urlsplit(endpoint or "")
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed.port)
        assert parsed.port is not None

        rule = MonitoringTargetRule.create(
            "127.0.0.1",
            ("127.0.0.0/8",),
            frozenset({parsed.port}),
            allow_loopback_http=True,
        )
        adapter = compose_prometheus_http_adapter((rule,))
        result = asyncio.run(adapter.probe(_source(endpoint or "", "t053-complete")))

        self.assertEqual(result.connection, MonitoringProbeConnection.REACHABLE)
        self.assertEqual(result.query_api, MonitoringProbeQueryApi.DENIED)
        self.assertEqual(result.profile, MonitoringProbeProfile.UNKNOWN)
        self.assertIs(result.failure, MonitoringProbeFailure.AUTHENTICATION)
        self.assertNotIn("password", repr(result).lower())

    @unittest.skipUnless(
        os.environ.get("SENTINEL_T053_PROMETHEUS_ENDPOINT"),
        "run via tools/with_disposable_prometheus_acceptance.sh",
    )
    def test_real_prometheus_check_receipt_is_accepted_by_console_sql_command(self) -> None:
        endpoint = os.environ.get("SENTINEL_T053_PROMETHEUS_ENDPOINT")
        parsed = urlsplit(endpoint or "")
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed.port)
        assert parsed.port is not None

        rule = MonitoringTargetRule.create(
            "127.0.0.1",
            ("127.0.0.0/8",),
            frozenset({parsed.port}),
            allow_loopback_http=True,
        )
        adapter = compose_prometheus_http_adapter((rule,))

        async def accept_through_console() -> None:
            temporary = tempfile.TemporaryDirectory(prefix="sentinel-t053-api-prom-")
            database = Path(temporary.name) / "console.sqlite3"
            engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
            try:
                await upgrade_database(engine)
                now = datetime.now(UTC)
                async with engine.begin() as connection:
                    await connection.execute(
                        insert(AccountRecord).values(
                            account_id="t053-live-admin",
                            username="t053-live-acceptance-admin",
                            username_key="b" * 64,
                            password_hash="argon2id$synthetic-acceptance-only",
                            role_id="admin",
                            status="active",
                            built_in=False,
                            last_login_at=None,
                            revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )

                async def resolve_engine():
                    return engine

                fingerprint_key = b"t053-live-fingerprint-key-000000000000"
                source_registry = SQLAlchemyMonitoringSourceStore(
                    resolve_engine,
                    AesGcmSecretCipher(
                        "monitoring-v1", {"monitoring-v1": b"t" * 32}
                    ),
                    fingerprint_key=fingerprint_key,
                )
                receipts = SQLAlchemyMonitoringProbeReceiptStore(resolve_engine)
                checker = CheckMonitoringSource(
                    adapter, receipts, fingerprint_key=fingerprint_key
                )
                host_metrics_adapter = compose_prometheus_host_metrics_adapter(
                    (rule,)
                )

                class SessionReader:
                    async def read_active_session(self, _digest):
                        return ActiveAccountSession(
                            "t053-live-admin", "operator", "admin", "epoch-1"
                        )

                class Noop:
                    async def is_initialized(self):
                        return True

                    async def is_setup_window_open(self):
                        return False

                    async def is_current_operator(self, _session):
                        return False

                    async def list_accounts(self, _query):
                        return ()

                    async def read_account(self, _account_id):
                        return None

                app = build_app(
                    bootstrap_initialization_reader=Noop(),
                    setup_window_reader=Noop(),
                    bootstrap_operator_verifier=Noop(),
                    current_session_reader=SessionReader(),
                    current_session_revoker=Noop(),
                    account_directory_reader=Noop(),
                    allowed_browser_origins=frozenset({"https://console.test"}),
                    monitoring_source_checker=checker,
                    monitoring_probe_receipt_reader=receipts,
                    monitoring_source_registry=source_registry,
                    monitoring_fingerprint_key=fingerprint_key,
                    monitoring_host_metrics_query_port=host_metrics_adapter,
                )
                source = _source(endpoint or "", "t053-complete")
                base_source = {
                    "sourceId": source.source_id,
                    "revision": source.revision,
                    "displayName": source.display_name,
                    "environmentId": source.environment_id,
                    "endpoint": source.endpoint,
                    "provider": source.provider.value,
                    "profile": source.profile.value,
                    "authenticationMode": source.authentication_mode.value,
                    "credentialConfigured": source.credential_configured,
                    "enabled": source.enabled,
                    "identityLabels": list(source.identity_labels),
                    "selectorLabels": [
                        {"name": label.name, "value": label.value}
                        for label in source.selector_labels
                    ],
                    "scrapeIntervalSeconds": source.scrape_interval_seconds,
                    "staleAfterSeconds": source.stale_after_seconds,
                }
                cookies = {
                    "sentinel_session": "synthetic-prometheus-live-session-0001",
                    "__Host-sentinel_csrf": "synthetic-prometheus-live-csrf-0001",
                }
                csrf = cookies["__Host-sentinel_csrf"]
                common_headers = {
                    "origin": "https://console.test",
                    "x-sentinel-csrf": csrf,
                }
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="https://console.test",
                    cookies=cookies,
                ) as client:
                    checked = None
                    for attempt in range(30):
                        checked = await client.post(
                            "/api/v2/monitoring/sources/check",
                            json={"source": base_source, "credentials": None},
                            headers={
                                **common_headers,
                                "x-request-id": f"t053-live-check-{attempt}",
                            },
                        )
                        self.assertEqual(checked.status_code, 200, checked.text)
                        if checked.json()["result"]["profile"] == "supported":
                            break
                        await asyncio.sleep(0.5)
                    else:
                        self.fail(f"real Prometheus probe did not become supported: {checked.text}")

                    check_result = checked.json()
                    self.assertEqual(check_result["result"]["identity"]["unique"], 1)
                    request_key = f"t053-live-save-{uuid4().hex}"
                    saved = await client.post(
                        "/api/v2/monitoring/sources/commands",
                        json={
                            "kind": "create",
                            "requestKey": request_key,
                            "source": base_source,
                            "credentials": None,
                            "credentialUpdate": "clear",
                            "checkId": check_result["checkId"],
                            "skipCheck": False,
                        },
                        headers={
                            **common_headers,
                            "idempotency-key": request_key,
                            "x-request-id": "t053-live-save",
                        },
                    )
                    self.assertEqual(saved.status_code, 202, saved.text)
                    self.assertEqual(saved.json()["status"], "completed")
                    self.assertTrue(saved.json()["verified"])

                    directory = await client.get(
                        "/api/v2/monitoring/sources",
                        headers={"x-request-id": "t053-live-directory"},
                    )
                    self.assertEqual(directory.status_code, 200, directory.text)
                    self.assertEqual(
                        directory.json()["items"][0]["revision"],
                        saved.json()["sourceRevision"],
                    )
                    self.assertNotIn(endpoint, directory.text)

                    # Prove the saved source drives the actual HOST read path:
                    # React's backend contract -> Console API -> SQL registry ->
                    # pinned Prometheus HTTP adapter -> scraped exporter samples.
                    snapshot = None
                    for attempt in range(30):
                        end_at = datetime.now(UTC).replace(microsecond=0) - timedelta(
                            seconds=2
                        )
                        start_at = end_at - timedelta(seconds=5)
                        snapshot = await client.get(
                            f"/api/v2/monitoring/sources/{source.source_id}/host-metrics",
                            params={
                                "from": start_at.isoformat(timespec="milliseconds").replace(
                                    "+00:00", "Z"
                                ),
                                "to": end_at.isoformat(timespec="milliseconds").replace(
                                    "+00:00", "Z"
                                ),
                                "stepMs": "1000",
                            },
                            headers={
                                "x-request-id": f"t054-live-host-metrics-{attempt}"
                            },
                        )
                        self.assertEqual(snapshot.status_code, 200, snapshot.text)
                        if snapshot.json()["quality"] == "available":
                            break
                        await asyncio.sleep(0.5)
                    else:
                        self.fail(
                            "real Prometheus HOST metrics did not become available: "
                            f"{snapshot.text}"
                        )

                    payload = snapshot.json()
                    self.assertEqual(payload["quality"], "available")
                    self.assertEqual(payload["sourceId"], source.source_id)
                    self.assertEqual(payload["environmentId"], source.environment_id)
                    self.assertEqual(len(payload["hosts"]), 1)
                    host = payload["hosts"][0]
                    self.assertEqual(
                        host["identity"], [{"name": "host", "value": "synthetic-node-a"}]
                    )
                    metrics = {item["metric"]: item for item in host["metrics"]}
                    self.assertEqual(
                        set(metrics),
                        {
                            "host_cpu_busy_ratio",
                            "host_memory_used_bytes",
                            "host_memory_used_ratio",
                            "host_load_1m",
                        },
                    )
                    self.assertTrue(
                        all(metrics[name]["samples"] for name in metrics), metrics
                    )
                    self.assertEqual(metrics["host_memory_used_bytes"]["unit"], "bytes")
                    self.assertEqual(metrics["host_cpu_busy_ratio"]["unit"], "ratio")

            finally:
                await engine.dispose()
                temporary.cleanup()

        asyncio.run(accept_through_console())


class RealExporterHostMetricsAcceptance(unittest.TestCase):
    """Read a real node-exporter profile through the authenticated Console API."""

    @unittest.skipUnless(
        os.environ.get("SENTINEL_T054_PROMETHEUS_ENDPOINT"),
        "set SENTINEL_T054_PROMETHEUS_ENDPOINT to an authorized local Prometheus",
    )
    def test_real_node_exporter_samples_reach_console_host_metrics_api(self) -> None:
        from atlas_richie.sentinel_console.domain.host_metrics import HostMetricKind
        from atlas_richie.sentinel_console.infrastructure.monitoring_probe_composition import (
            compose_prometheus_host_metrics_adapter,
        )

        endpoint = os.environ["SENTINEL_T054_PROMETHEUS_ENDPOINT"]
        parsed = urlsplit(endpoint)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed.port)
        assert parsed.port is not None
        rule = MonitoringTargetRule.create(
            "127.0.0.1",
            ("127.0.0.0/8",),
            frozenset({parsed.port}),
            allow_loopback_http=True,
        )
        source = MonitoringSource(
            source_id="t054-real-node-exporter",
            revision="live-acceptance-1",
            display_name="Authorized local Linux node exporter",
            environment_id="sentinel-e2e",
            endpoint=endpoint,
            provider=MonitoringProvider.PROMETHEUS_COMPATIBLE,
            profile=MonitoringProfile.NODE_EXPORTER_V1,
            authentication_mode=MonitoringAuthenticationMode.NONE,
            credential_configured=False,
            enabled=True,
            identity_labels=("host_id",),
            selector_labels=(
                MonitoringLabel("job", "sentinel-e2e-node-exporter"),
                MonitoringLabel("environment", "sentinel-e2e"),
            ),
            scrape_interval_seconds=15,
            stale_after_seconds=90,
        )
        end_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=2)
        query_start = end_at - timedelta(minutes=1)

        class Initialized:
            async def is_initialized(self):
                return True

        class ClosedSetup:
            async def is_setup_window_open(self):
                return False

        class Verifier:
            async def is_current_operator(self, _opaque_session):
                return False

        class SessionReader:
            async def read_active_session(self, _session_digest):
                return ActiveAccountSession("t054-viewer", "viewer", "view", "epoch-1")

        class Registry:
            async def read_monitoring_source(self, source_id):
                if source_id != source.source_id:
                    raise AssertionError("acceptance requested an unexpected source")
                return source

        class UnusedAccountDirectory:
            async def list_accounts(self, _query):
                raise AssertionError("HOST metrics read must not access accounts")

            async def read_account(self, _account_id):
                raise AssertionError("HOST metrics read must not access accounts")

        app = build_app(
            bootstrap_initialization_reader=Initialized(),
            setup_window_reader=ClosedSetup(),
            bootstrap_operator_verifier=Verifier(),
            current_session_reader=SessionReader(),
            current_session_revoker=UnusedAccountDirectory(),
            account_directory_reader=UnusedAccountDirectory(),
            allowed_browser_origins=frozenset({"http://testserver"}),
            monitoring_source_registry=Registry(),
            monitoring_host_metrics_query_port=compose_prometheus_host_metrics_adapter(
                (rule,)
            ),
        )

        async def read() -> dict[str, object]:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                cookies={"sentinel_session": "synthetic-t054-live-view-session"},
            ) as client:
                response = await client.get(
                    f"/api/v2/monitoring/sources/{source.source_id}/host-metrics",
                    params={
                        "from": query_start.isoformat(timespec="milliseconds").replace(
                            "+00:00", "Z"
                        ),
                        "to": end_at.isoformat(timespec="milliseconds").replace(
                            "+00:00", "Z"
                        ),
                        "stepMs": "15000",
                    },
                    headers={"x-request-id": "t054-real-exporter-host-metrics"},
                )
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        payload = asyncio.run(read())
        self.assertEqual(payload["sourceId"], source.source_id)
        self.assertEqual(payload["environmentId"], source.environment_id)
        hosts = payload["hosts"]
        self.assertEqual(len(hosts), 1)
        host = hosts[0]
        self.assertEqual(
            host["identity"],
            [{"name": "host_id", "value": "docker-desktop-linux-vm"}],
        )
        metrics = {item["metric"]: item for item in host["metrics"]}
        for kind in HostMetricKind:
            self.assertIn(kind.value, metrics)
            self.assertTrue(metrics[kind.value]["samples"], metrics[kind.value])
