from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette

from atlas_richie.sentinel_console.api.host_associations import host_association_routes
from atlas_richie.sentinel_console.application.read_session import ReadSession
from atlas_richie.sentinel_console.domain.host_associations import (
    HostAssociationIdempotencyConflict,
    HostAssociationPage,
    HostInstanceAssociation,
)
from atlas_richie.sentinel_console.domain.host_metrics import (
    HostMetricIdentity,
    HostMetricKind,
    HostMetricQuality,
    HostMetricReason,
    HostMetricSeries,
    HostMetricsHost,
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

_COOKIE = "host-association-session-token-000000000001"
_CSRF = "host-association-csrf-token-000000000001"
_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_REVISION = "00000000-0000-4000-8000-000000000001"
_EPOCH = "00000000-0000-4000-8000-000000000002"


class _SessionReader:
    def __init__(self, role: str) -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if session_digest != hashlib.sha256(_COOKIE.encode()).hexdigest():
            return None
        return ActiveAccountSession("account-1", "admin", self.role, "epoch-1")


class _Store:
    def __init__(self) -> None:
        self.items: list[HostInstanceAssociation] = []
        self.operations: dict[
            str, tuple[dict[str, object], str, str, dict[str, object]]
        ] = {}

    async def list_host_associations(
        self,
        environment_id,
        *,
        source_id=None,
        app_id=None,
        instance_id=None,
        page=1,
        page_size=100,
    ):
        matches = tuple(
            item
            for item in self.items
            if item.environment_id == environment_id
            and (source_id is None or item.source_id == source_id)
            and (app_id is None or item.app_id == app_id)
            and (instance_id is None or item.instance_id == instance_id)
        )
        host_ids = tuple(sorted({item.host_id for item in matches}))
        start = (page - 1) * page_size
        return HostAssociationPage(
            items=matches[start : start + page_size],
            page=page,
            page_size=page_size,
            total=len(matches),
            associated_host_ids=host_ids[:200],
            host_ids_complete=len(host_ids) <= 200,
        )

    async def put_host_association(self, **values):
        item = HostInstanceAssociation(
            source_id=values["source_id"],
            environment_id=values["environment_id"],
            host_id=values["host_id"],
            app_id=values["app_id"],
            instance_id=values["instance_id"],
            process_id="pid-1",
            revision=_REVISION,
            current_epoch=_EPOCH,
            last_received_at=values["now"],
            created_at=values["now"],
            reporter_active=True,
        )
        self.items = [
            current
            for current in self.items
            if (current.environment_id, current.app_id, current.instance_id)
            != (item.environment_id, item.app_id, item.instance_id)
        ]
        self.items.append(item)
        result = {
            "sourceId": item.source_id,
            "environmentId": item.environment_id,
            "hostId": item.host_id,
            "appId": item.app_id,
            "instanceId": item.instance_id,
            "processId": item.process_id,
            "revision": item.revision,
            "provenance": "operator_confirmed",
            "currentEpoch": item.current_epoch,
            "lastReceivedAt": values["now"]
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "reporterActive": True,
            "createdAt": values["now"]
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }
        self.operations[values["request_key"]] = (
            {
                "sourceId": values["source_id"],
                "environmentId": values["environment_id"],
                "hostId": values["host_id"],
                "appId": values["app_id"],
                "instanceId": values["instance_id"],
                "expectedRevision": values["expected_revision"],
            },
            values["actor_id"],
            values["session_digest"],
            result,
        )
        return result

    async def delete_host_association(self, **values):
        previous = len(self.items)
        self.items = [
            item
            for item in self.items
            if (item.environment_id, item.app_id, item.instance_id)
            != (values["environment_id"], values["app_id"], values["instance_id"])
        ]
        return {"removed": True} if len(self.items) != previous else None

    async def resolve_host_association_replay(self, request_key, **values):
        previous = self.operations.get(request_key)
        if previous is None:
            return None
        command, actor_id, session_digest, result = previous
        if (
            command != values["command"]
            or actor_id != values["actor_id"]
            or session_digest != values["session_digest"]
        ):
            raise HostAssociationIdempotencyConflict
        return result

    async def read_host_association_operation(self, *args, **kwargs):
        return None


class _Registry:
    source = MonitoringSource(
        source_id="prom-prod",
        revision="r1",
        display_name="Prometheus",
        environment_id="prod",
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

    async def read_monitoring_source(self, source_id):
        if source_id != self.source.source_id:
            from atlas_richie.sentinel_console.application.monitoring_source_registry import (
                MonitoringSourceNotFound,
            )

            raise MonitoringSourceNotFound
        return self.source


class _Query:
    def __init__(self) -> None:
        self.calls = 0
        self.unavailable = False

    async def read_host_metrics(self, source, query, credentials):
        self.calls += 1
        if self.unavailable:
            return HostMetricsSnapshot(
                source.source_id,
                source.environment_id,
                query,
                query.end_at,
                HostMetricQuality.UNAVAILABLE,
                HostMetricReason.TRANSPORT,
                (),
            )
        metrics = tuple(
            HostMetricSeries(
                kind, HostMetricQuality.NO_SAMPLES, HostMetricReason.MISSING_SAMPLES, ()
            )
            for kind in HostMetricKind
        )
        host = HostMetricsHost(
            HostMetricIdentity("node-01", (("host", "node-01"),)), metrics
        )
        return HostMetricsSnapshot(
            source.source_id,
            source.environment_id,
            query,
            query.end_at,
            HostMetricQuality.NO_SAMPLES,
            HostMetricReason.MISSING_SAMPLES,
            (host,),
        )


def _app(role: str, store: _Store, query=None):
    registry = _Registry()
    return Starlette(
        routes=host_association_routes(
            ReadSession(_SessionReader(role)),
            store,
            {"https://console.test"},
            registry,
            query or _Query(),
            None,
        )
    )


class HostAssociationsApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_view_role_can_read_explicit_associations(self):
        store = _Store()
        await store.put_host_association(
            source_id="prom-prod",
            environment_id="prod",
            host_id="node-01",
            app_id="orders",
            instance_id="worker-1",
            expected_revision=None,
            request_key="seed-association",
            actor_id="account-1",
            session_digest=hashlib.sha256(_COOKIE.encode()).hexdigest(),
            request_id="host-association-seed-0001",
            now=_NOW,
        )
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", store)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            response = await client.get(
                "/api/v2/monitoring/host-associations?environmentId=prod",
                headers={"x-request-id": "host-association-read-00000001"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        assert_openapi_response("readHostAssociations", response)
        self.assertEqual(response.json()["items"][0]["hostId"], "node-01")
        self.assertEqual(response.json()["items"][0]["processId"], "pid-1")

    async def test_view_role_can_read_a_filtered_association_page(self):
        store = _Store()
        store.items = [
            HostInstanceAssociation(
                source_id="prom-prod",
                environment_id="prod",
                host_id=f"node-{index:02d}",
                app_id="orders",
                instance_id=f"worker-{index}",
                process_id=f"pid-{index}",
                revision=f"00000000-0000-4000-8000-{index:012d}",
                current_epoch=None,
                last_received_at=None,
                created_at=_NOW,
                reporter_active=False,
            )
            for index in range(1, 3)
        ]
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", store)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            response = await client.get(
                "/api/v2/monitoring/host-associations?environmentId=prod&sourceId=prom-prod&appId=orders&page=2&pageSize=1",
                headers={"x-request-id": "host-association-page-00000001"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        assert_openapi_response("readHostAssociations", response)
        self.assertEqual(response.json()["page"], 2)
        self.assertEqual(response.json()["pageSize"], 1)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["items"][0]["hostId"], "node-02")

    async def test_view_role_rejects_invalid_association_page_values(self):
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", _Store())),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            response = await client.get(
                "/api/v2/monitoring/host-associations?environmentId=prod&page=0",
                headers={"x-request-id": "host-association-page-00000002"},
            )
        self.assertEqual(response.status_code, 400, response.text)

    async def test_exact_instance_filter_requires_app_and_returns_only_that_worker(
        self,
    ):
        store = _Store()
        store.items = [
            HostInstanceAssociation(
                source_id="prom-prod",
                environment_id="prod",
                host_id=f"node-{index:02d}",
                app_id="orders",
                instance_id=f"worker-{index}",
                process_id=f"pid-{index}",
                revision=f"00000000-0000-4000-8000-{index:012d}",
                current_epoch=None,
                last_received_at=None,
                created_at=_NOW,
                reporter_active=True,
            )
            for index in range(1, 3)
        ]
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", store)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            response = await client.get(
                "/api/v2/monitoring/host-associations?environmentId=prod&appId=orders&instanceId=worker-2&pageSize=1",
                headers={"x-request-id": "host-association-exact-000001"},
            )
            invalid = await client.get(
                "/api/v2/monitoring/host-associations?environmentId=prod&instanceId=worker-2",
                headers={"x-request-id": "host-association-exact-000002"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        assert_openapi_response("readHostAssociations", response)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["instanceId"], "worker-2")
        self.assertEqual(invalid.status_code, 400, invalid.text)

    async def test_admin_write_requires_verified_host_and_csrf(self):
        store = _Store()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.put(
                "/api/v2/monitoring/host-associations",
                json={
                    "requestKey": "associate-node-0001",
                    "environmentId": "prod",
                    "sourceId": "prom-prod",
                    "hostId": "node-01",
                    "appId": "orders",
                    "instanceId": "worker-1",
                    "expectedRevision": None,
                },
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "host-association-write-0000001",
                    "x-sentinel-csrf": _CSRF,
                    "idempotency-key": "associate-node-0001",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        assert_openapi_response("putHostAssociation", response)
        self.assertEqual(response.json()["hostId"], "node-01")
        self.assertEqual(len(store.items), 1)

    async def test_non_admin_cannot_write_even_with_csrf(self):
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", _Store())),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.put(
                "/api/v2/monitoring/host-associations",
                json={
                    "requestKey": "associate-node-0002",
                    "environmentId": "prod",
                    "sourceId": "prom-prod",
                    "hostId": "node-01",
                    "appId": "orders",
                    "instanceId": "worker-1",
                    "expectedRevision": None,
                },
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "host-association-write-0000002",
                    "x-sentinel-csrf": _CSRF,
                    "idempotency-key": "associate-node-0002",
                },
            )
        self.assertEqual(response.status_code, 403)

    async def test_admin_cannot_associate_host_not_in_verified_snapshot(self):
        store = _Store()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.put(
                "/api/v2/monitoring/host-associations",
                json={
                    "requestKey": "associate-unobserved-001",
                    "environmentId": "prod",
                    "sourceId": "prom-prod",
                    "hostId": "unobserved-host",
                    "appId": "orders",
                    "instanceId": "worker-1",
                    "expectedRevision": None,
                },
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "host-association-unobserved-0001",
                    "x-sentinel-csrf": _CSRF,
                    "idempotency-key": "associate-unobserved-001",
                },
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(store.items, [])

    async def test_unavailable_prometheus_snapshot_is_not_misreported_as_missing_host(
        self,
    ):
        class UnavailableQuery:
            async def read_host_metrics(self, source, query, credentials):
                return HostMetricsSnapshot(
                    source.source_id,
                    source.environment_id,
                    query,
                    _NOW,
                    HostMetricQuality.UNAVAILABLE,
                    HostMetricReason.TRANSPORT,
                    (),
                )

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", _Store(), UnavailableQuery())),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.put(
                "/api/v2/monitoring/host-associations",
                json={
                    "requestKey": "associate-unavailable-001",
                    "environmentId": "prod",
                    "sourceId": "prom-prod",
                    "hostId": "node-01",
                    "appId": "orders",
                    "instanceId": "worker-1",
                    "expectedRevision": None,
                },
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "host-association-unavailable-0001",
                    "x-sentinel-csrf": _CSRF,
                    "idempotency-key": "associate-unavailable-001",
                },
            )
        self.assertEqual(response.status_code, 503)

    async def test_completed_command_replays_without_prometheus_read(self):
        store = _Store()
        query = _Query()
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store, query)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            body = {
                "requestKey": "associate-replay-001",
                "environmentId": "prod",
                "sourceId": "prom-prod",
                "hostId": "node-01",
                "appId": "orders",
                "instanceId": "worker-1",
                "expectedRevision": None,
            }
            headers = {
                "origin": "https://console.test",
                "x-request-id": "host-association-replay-0001",
                "x-sentinel-csrf": _CSRF,
                "idempotency-key": "associate-replay-001",
            }
            first = await client.put(
                "/api/v2/monitoring/host-associations", json=body, headers=headers
            )
            query.unavailable = True
            replay = await client.put(
                "/api/v2/monitoring/host-associations", json=body, headers=headers
            )
        self.assertEqual(first.status_code, 200)
        assert_openapi_response("putHostAssociation", first)
        self.assertEqual(replay.status_code, 200)
        assert_openapi_response("putHostAssociation", replay)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(query.calls, 1)

    async def test_admin_can_remove_association_and_read_operation_status(self):
        store = _Store()
        store.items = [
            HostInstanceAssociation(
                source_id="prom-prod",
                environment_id="prod",
                host_id="node-01",
                app_id="orders",
                instance_id="worker-1",
                process_id="pid-1",
                revision=_REVISION,
                current_epoch=_EPOCH,
                last_received_at=_NOW,
                created_at=_NOW,
                reporter_active=True,
            )
        ]
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", store)),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE, "__Host-sentinel_csrf": _CSRF},
        ) as client:
            response = await client.request(
                "DELETE",
                "/api/v2/monitoring/host-associations",
                json={
                    "requestKey": "remove-node-0001",
                    "environmentId": "prod",
                    "appId": "orders",
                    "instanceId": "worker-1",
                    "expectedRevision": _REVISION,
                },
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "host-association-delete-0001",
                    "x-sentinel-csrf": _CSRF,
                    "idempotency-key": "remove-node-0001",
                },
            )
            operation = await client.get(
                "/api/v2/monitoring/host-associations/operations/remove-node-0001",
                headers={"x-request-id": "host-association-operation-0001"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        assert_openapi_response("deleteHostAssociation", response)
        self.assertEqual(operation.status_code, 200, operation.text)
        assert_openapi_response("readHostAssociationOperation", operation)


if __name__ == "__main__":
    unittest.main()
