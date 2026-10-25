from __future__ import annotations

import unittest
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.domain.host_associations import (
    HostAssociationNotFound,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.infrastructure.persistence.host_association_store import (
    SQLAlchemyHostAssociationStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    HostInstanceAssociationRecord,
    MetricsReporterBindingRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_source_store import (
    SQLAlchemyMonitoringSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class HostAssociationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)

        async def engine_resolver():
            return self.engine

        source_store = SQLAlchemyMonitoringSourceStore(
            engine_resolver,
            AesGcmSecretCipher("test", {"test": b"h" * 32}),
        )
        self.source_store = source_store
        self.store = SQLAlchemyHostAssociationStore(engine_resolver)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-1",
                    username="admin",
                    username_key="admin",
                    password_hash="not-a-real-password-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
        self.source = MonitoringSource(
            source_id="prom-prod",
            revision="draft",
            display_name="Production hosts",
            environment_id="prod",
            endpoint="http://prometheus.example.test",
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
        await source_store.create_monitoring_source(self.source, secret=None, now=_NOW)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(MetricsReporterBindingRecord).values(
                    certificate_principal="spiffe://test/orders/worker-1",
                    certificate_sha256="a" * 64,
                    reporter_id="reporter-1",
                    environment_id="prod",
                    app_id="orders",
                    instance_id="worker-1",
                    process_id="pid-123",
                    revoked_at=None,
                    current_epoch=None,
                    last_sequence=0,
                    last_elapsed_ns=None,
                    last_received_at=None,
                )
            )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _put(self, *, request_key="association-create-0001", **values):
        return await self.store.put_host_association(
            source_id=values.pop("source_id", "prom-prod"),
            environment_id=values.pop("environment_id", "prod"),
            host_id=values.pop("host_id", "node-01"),
            app_id=values.pop("app_id", "orders"),
            instance_id=values.pop("instance_id", "worker-1"),
            expected_revision=values.pop("expected_revision", None),
            request_key=request_key,
            actor_id="account-1",
            session_digest="a" * 64,
            request_id=f"request-{request_key}",
            now=values.pop("now", _NOW),
        )

    async def test_association_is_persisted_and_projected_from_enrollment(self) -> None:
        result = await self._put()
        listed = await self.store.list_host_associations("prod")
        self.assertEqual((listed.page, listed.page_size, listed.total), (1, 100, 1))
        self.assertEqual(listed.associated_host_ids, ("node-01",))
        self.assertTrue(listed.host_ids_complete)
        self.assertEqual(result["hostId"], listed.items[0].host_id)
        self.assertEqual(listed.items[0].process_id, "pid-123")
        self.assertTrue(listed.items[0].reporter_active)

    async def test_unenrolled_worker_fails_closed(self) -> None:
        with self.assertRaises(HostAssociationNotFound):
            await self._put(instance_id="unknown-worker")

    async def test_worker_has_one_mapping_and_can_be_explicitly_reassigned(
        self,
    ) -> None:
        first = await self._put()
        second = await self._put(
            request_key="association-reassign-0001",
            host_id="node-02",
            expected_revision=first["revision"],
        )
        self.assertNotEqual(first["hostId"], second["hostId"])
        self.assertEqual((await self.store.list_host_associations("prod")).total, 1)

    async def test_stale_revision_fails_closed(self):
        await self._put()
        from atlas_richie.sentinel_console.domain.host_associations import (
            HostAssociationConflict,
        )

        with self.assertRaises(HostAssociationConflict):
            await self._put(
                request_key="association-stale-0001",
                host_id="node-02",
                expected_revision="00000000-0000-0000-0000-000000000000",
            )

    async def test_host_summary_is_bounded_and_marks_incomplete_scope(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(HostInstanceAssociationRecord),
                [
                    {
                        "environment_id": "prod",
                        "app_id": "inventory",
                        "instance_id": f"worker-{index:03d}",
                        "source_id": "prom-prod",
                        "host_id": f"node-{index:03d}",
                        "revision": f"00000000-0000-4000-8000-{index:012d}",
                        "created_at": _NOW,
                        "updated_at": _NOW,
                    }
                    for index in range(201)
                ],
            )
        directory = await self.store.list_host_associations(
            "prod", source_id="prom-prod", app_id="inventory", page_size=1
        )
        self.assertEqual(directory.total, 201)
        self.assertEqual(len(directory.items), 1)
        self.assertEqual(len(directory.associated_host_ids), 200)
        self.assertFalse(directory.host_ids_complete)

    async def test_delete_is_idempotently_reported_by_boolean(self) -> None:
        await self._put()
        revision = (await self.store.list_host_associations("prod")).items[0].revision
        self.assertEqual(
            await self.store.delete_host_association(
                environment_id="prod",
                app_id="orders",
                instance_id="worker-1",
                expected_revision=revision,
                request_key="association-delete-0001",
                actor_id="account-1",
                session_digest="a" * 64,
                request_id="request-association-delete-0001",
                now=_NOW,
            ),
            {"removed": True},
        )
        self.assertIsNone(
            await self.store.delete_host_association(
                environment_id="prod",
                app_id="orders",
                instance_id="worker-1",
                expected_revision=revision,
                request_key="association-delete-0002",
                actor_id="account-1",
                session_digest="a" * 64,
                request_id="request-association-delete-0002",
                now=_NOW,
            )
        )

    async def test_idempotency_replay_and_audit_are_atomic_and_safe(self):
        first = await self._put()
        replay = await self._put()
        self.assertEqual(replay, first)
        operation = await self.store.read_host_association_operation(
            "association-create-0001", actor_id="account-1", session_digest="a" * 64
        )
        self.assertEqual(operation, first)
        from sqlalchemy import select

        from atlas_richie.sentinel_console.infrastructure.persistence.models import (
            AuditEventRecord,
        )

        async with self.engine.connect() as connection:
            audits = (
                await connection.execute(
                    select(AuditEventRecord.action, AuditEventRecord.target_id)
                )
            ).all()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].action, "monitoring.host-association.create")
        self.assertIsNone(audits[0].target_id)

    async def test_reusing_request_key_for_other_payload_or_session_fails_closed(self):
        from atlas_richie.sentinel_console.domain.host_associations import (
            HostAssociationIdempotencyConflict,
        )

        await self._put()
        with self.assertRaises(HostAssociationIdempotencyConflict):
            await self._put(host_id="node-02")
        with self.assertRaises(HostAssociationIdempotencyConflict):
            await self.store.read_host_association_operation(
                "association-create-0001",
                actor_id="account-1",
                session_digest="b" * 64,
            )


if __name__ == "__main__":
    unittest.main()
