from __future__ import annotations

import unittest
import hashlib
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.monitoring_source_registry import (
    MonitoringSourceCommandForbidden,
    MonitoringSourceNotFound,
    MonitoringSourceOperation,
    MonitoringSourceOperationReason,
    MonitoringSourceOperationStatus,
    MonitoringSourceRegistryUnavailable,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
    MonitoringSourcesSnapshot,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
_COOKIE = "synthetic-session-token-for-monitoring-source-0001"


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


class _Registry:
    def __init__(self) -> None:
        self.source = _source()
        self.operation = None
        self.mutations = []

    async def read_monitoring_sources(self):
        return MonitoringSourcesSnapshot(_NOW, (self.source,))

    async def read_monitoring_source(self, source_id: str):
        if source_id != self.source.source_id:
            raise MonitoringSourceNotFound
        return self.source

    async def create_monitoring_source(self, source, *, secret, now):
        raise AssertionError("read path must not write")

    async def update_monitoring_source(self, source, **kwargs):
        raise AssertionError("read path must not write")

    async def delete_monitoring_source(self, source_id, **kwargs):
        raise AssertionError("read path must not write")

    async def resolve_monitoring_source_secret(self, source_id, **kwargs):
        raise AssertionError("safe read path must not resolve secrets")

    async def execute_monitoring_source_mutation(self, command):
        self.mutations.append(command)
        self.operation = MonitoringSourceOperation(
            command.request_key,
            MonitoringSourceOperationStatus.COMPLETED,
            source_id="prom-primary",
            source_revision="persisted-revision-2",
            enabled=command.enabled if command.kind == "set-enabled" else True,
            verified=False if command.kind in {"create", "update"} else None,
        )
        return self.operation

    async def read_monitoring_source_operation(
        self, request_key, *, actor_id, session_digest
    ):
        if request_key != "monitor-op-1" or self.operation is None:
            return None
        expected_session = hashlib.sha256(_COOKIE.encode()).hexdigest()
        if actor_id != "account-1" or session_digest != expected_session:
            raise MonitoringSourceCommandForbidden
        return self.operation


class _UnavailableRegistry(_Registry):
    async def read_monitoring_sources(self):
        raise MonitoringSourceRegistryUnavailable("private sql details")


class _InUseRegistry(_Registry):
    async def execute_monitoring_source_mutation(self, command):
        self.mutations.append(command)
        self.operation = MonitoringSourceOperation(
            command.request_key,
            MonitoringSourceOperationStatus.REJECTED,
            reason=MonitoringSourceOperationReason.SOURCE_IN_USE,
        )
        return self.operation


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("monitoring source read must not access accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("monitoring source read must not access accounts")


def _source() -> MonitoringSource:
    return MonitoringSource(
        source_id="monitoring-primary",
        revision="revision-1",
        display_name="Primary metrics",
        environment_id="production",
        endpoint="https://prometheus.example.test/api/v1/secret-like-path",
        provider=MonitoringProvider.PROMETHEUS_COMPATIBLE,
        profile=MonitoringProfile.NODE_EXPORTER_V1,
        authentication_mode=MonitoringAuthenticationMode.DIRECT_BEARER,
        credential_configured=True,
        enabled=True,
        identity_labels=("host",),
        selector_labels=(MonitoringLabel("job", "node-exporter"),),
        scrape_interval_seconds=15,
        stale_after_seconds=90,
    )


def _app(role: str | None, registry=None, session_reader=None):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=_UnusedAccountDirectoryReader(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.example.test"}),
        monitoring_source_registry=registry,
        monitoring_fingerprint_key=b"monitoring-source-test-key-0000000000000000",
    )


def _command_body():
    source = _source()
    return {
        "kind": "create",
        "requestKey": "monitor-op-1",
        "source": {
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
        },
        "credentials": {"bearerToken": "super-secret-token-value"},
        "credentialUpdate": "replace",
        "checkId": None,
        "skipCheck": True,
    }


class MonitoringSourcesApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_source_in_use_rejection_is_stable_and_readable(self):
        registry = _InUseRegistry()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", registry)),
            base_url="https://console.example.test",
            cookies={
                "sentinel_session": _COOKIE,
                "__Host-sentinel_csrf": "monitoring-source-csrf-token-00000001",
            },
        ) as client:
            response = await client.post(
                "/api/v2/monitoring/sources/commands",
                json={
                    "kind": "delete",
                    "requestKey": "monitor-op-1",
                    "sourceId": "prom-primary",
                    "expectedRevision": "revision-1",
                },
                headers={
                    "origin": "https://console.example.test",
                    "x-request-id": "monitor-delete-in-use",
                    "x-sentinel-csrf": "monitoring-source-csrf-token-00000001",
                    "idempotency-key": "monitor-op-1",
                },
            )
            readback = await client.get(
                "/api/v2/monitoring/sources/operations/monitor-op-1",
                headers={"x-request-id": "monitor-delete-in-use-readback"},
            )

        expected = {
            "status": "rejected",
            "requestKey": "monitor-op-1",
            "reason": "source_in_use",
        }
        self.assertEqual(response.status_code, 202)
        assert_openapi_response("mutateMonitoringSource", response)
        self.assertEqual(response.json(), expected)
        self.assertEqual(readback.status_code, 200)
        assert_openapi_response("readMonitoringSourceOperation", readback)
        self.assertEqual(readback.json(), expected)

    async def test_admin_command_is_idempotent_safe_and_readback_is_session_bound(self):
        registry = _Registry()
        app = _app("admin", registry)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.example.test",
            cookies={
                "sentinel_session": _COOKIE,
                "__Host-sentinel_csrf": "monitoring-source-csrf-token-00000001",
            },
        ) as client:
            response = await client.post(
                "/api/v2/monitoring/sources/commands",
                json=_command_body(),
                headers={
                    "origin": "https://console.example.test",
                    "x-request-id": "monitor-command-1",
                    "x-sentinel-csrf": "monitoring-source-csrf-token-00000001",
                    "idempotency-key": "monitor-op-1",
                },
            )
            readback = await client.get(
                "/api/v2/monitoring/sources/operations/monitor-op-1",
                headers={"x-request-id": "monitor-operation-1"},
            )

        self.assertEqual(response.status_code, 202)
        assert_openapi_response("mutateMonitoringSource", response)
        self.assertEqual(
            response.json(),
            {
                "status": "completed",
                "requestKey": "monitor-op-1",
                "sourceId": "prom-primary",
                "sourceRevision": "persisted-revision-2",
                "enabled": True,
                "verified": False,
            },
        )
        self.assertEqual(len(registry.mutations), 1)
        self.assertEqual(registry.mutations[0].actor_id, "account-1")
        self.assertEqual(registry.mutations[0].request_id, "monitor-command-1")
        self.assertNotIn("super-secret-token-value", response.text)
        self.assertNotIn("secret-like-path", response.text)
        self.assertEqual(readback.status_code, 200)
        assert_openapi_response("readMonitoringSourceOperation", readback)
        self.assertEqual(readback.json(), response.json())

    async def test_source_management_command_requires_admin_and_csrf(self):
        for role, headers, status in (
            ("view", {"origin": "https://console.example.test", "x-sentinel-csrf": "monitoring-source-csrf-token-00000001"}, 403),
            ("admin", {"origin": "https://console.example.test"}, 403),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, _Registry())),
                base_url="https://console.example.test",
                cookies={
                    "sentinel_session": _COOKIE,
                    "__Host-sentinel_csrf": "monitoring-source-csrf-token-00000001",
                },
            ) as client:
                response = await client.post(
                    "/api/v2/monitoring/sources/commands",
                    json=_command_body(),
                    headers={
                        **headers,
                        "x-request-id": "monitor-command-denied",
                        "idempotency-key": "monitor-op-1",
                    },
                )
            self.assertEqual(response.status_code, status)
            assert_openapi_response("mutateMonitoringSource", response)

    async def test_enable_toggle_uses_minimal_safe_compare_and_swap_command(self):
        registry = _Registry()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", registry)),
            base_url="https://console.example.test",
            cookies={
                "sentinel_session": _COOKIE,
                "__Host-sentinel_csrf": "monitoring-source-csrf-token-00000001",
            },
        ) as client:
            response = await client.post(
                "/api/v2/monitoring/sources/commands",
                json={
                    "kind": "set-enabled",
                    "requestKey": "monitor-op-1",
                    "sourceId": "prom-primary",
                    "expectedRevision": "revision-1",
                    "enabled": False,
                },
                headers={
                    "origin": "https://console.example.test",
                    "x-request-id": "monitor-toggle-1",
                    "x-sentinel-csrf": "monitoring-source-csrf-token-00000001",
                    "idempotency-key": "monitor-op-1",
                },
            )
        assert response.status_code == 202
        assert_openapi_response("mutateMonitoringSource", response)
        assert response.json()["enabled"] is False
        assert registry.mutations[0].kind == "set-enabled"
        assert registry.mutations[0].source is None
        assert registry.mutations[0].secret is None

    async def test_admin_and_view_receive_safe_directory(self):
        expected = {
            "asOf": "2026-10-17T10:00:00.000Z",
            "items": [
                {
                    "id": "monitoring-primary",
                    "revision": "revision-1",
                    "displayName": "Primary metrics",
                    "environmentId": "production",
                    "provider": "prometheus-compatible",
                    "profile": "node-exporter-v1",
                    "enabled": True,
                    "authenticationMode": "direct-bearer",
                    "credentialConfigured": True,
                }
            ],
        }
        for role in ("admin", "view"):
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, _Registry())),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _COOKIE)
                response = await client.get(
                    "/api/v2/monitoring/sources", headers={"x-request-id": "mon-source-1"}
                )

            assert response.status_code == 200
            assert_openapi_response("readMonitoringSources", response)
            assert response.json() == expected
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["vary"] == "Cookie"
            assert "prometheus.example.test" not in response.text
            assert "secret" not in response.text

    async def test_detail_is_admin_only_and_redacts_endpoint_path(self):
        for role, status in (("admin", 200), ("view", 403)):
            async with AsyncClient(
                transport=ASGITransport(app=_app(role, _Registry())),
                base_url="http://test",
            ) as client:
                client.cookies.set("sentinel_session", _COOKIE)
                response = await client.get(
                    "/api/v2/monitoring/sources/monitoring-primary",
                    headers={"x-request-id": "mon-source-2"},
                )

            assert response.status_code == status
            assert_openapi_response("readMonitoringSource", response)
            if status == 200:
                assert response.json()["endpointOrigin"] == "https://prometheus.example.test"
                assert "api/v1" not in response.text
                assert "secret" not in response.text
                assert "credentialReference" not in response.text
                assert "bearerToken" not in response.text
                assert "password" not in response.text.lower()

    async def test_absent_service_and_source_return_sanitized_errors(self):
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin")), base_url="http://test"
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            unavailable = await client.get(
                "/api/v2/monitoring/sources", headers={"x-request-id": "mon-source-3"}
            )
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", _Registry())),
            base_url="http://test",
        ) as client:
            client.cookies.set("sentinel_session", _COOKIE)
            missing = await client.get(
                "/api/v2/monitoring/sources/missing",
                headers={"x-request-id": "mon-source-4"},
            )

        assert unavailable.status_code == 503
        assert missing.status_code == 404
        assert_openapi_response("readMonitoringSources", unavailable)
        assert_openapi_response("readMonitoringSource", missing)
        assert "private" not in unavailable.text


if __name__ == "__main__":
    unittest.main()
