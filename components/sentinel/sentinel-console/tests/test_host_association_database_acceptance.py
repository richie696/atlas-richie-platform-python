"""Cross-dialect acceptance for durable host-to-worker associations."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

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
    AuditEventRecord,
    ConsoleBase,
    HostInstanceAssociationRecord,
    MetricsReporterBindingRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_source_store import (
    SQLAlchemyMonitoringSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

_URL = os.environ.get("SENTINEL_CONSOLE_HOST_ASSOCIATION_TEST_URL")
_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _validated_url(value: str | None) -> str | None:
    if value is None:
        return None
    url = make_url(value)
    if (
        url.drivername not in {"mysql+asyncmy", "postgresql+psycopg"}
        or not url.database
        or not url.database.startswith("sentinel_console_test_")
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "SENTINEL_CONSOLE_HOST_ASSOCIATION_TEST_URL must target an isolated "
            "loopback sentinel_console_test_* database"
        )
    return value


_URL = _validated_url(_URL)


@unittest.skipUnless(
    _URL, "set SENTINEL_CONSOLE_HOST_ASSOCIATION_TEST_URL for SQL dialect acceptance"
)
class HostAssociationDatabaseAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """Exercise migrations, shared-host pagination, replay, restart and revocation."""

    async def asyncSetUp(self) -> None:
        assert _URL is not None
        self.engine = create_async_engine(_URL, pool_size=3)
        async with self.engine.begin() as connection:
            await connection.run_sync(ConsoleBase.metadata.drop_all)
            await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        await upgrade_database(self.engine)

        async def resolve_engine():
            return self.engine

        self.resolve_engine = resolve_engine
        self.store = SQLAlchemyHostAssociationStore(resolve_engine)
        source_store = SQLAlchemyMonitoringSourceStore(
            resolve_engine,
            AesGcmSecretCipher("test", {"test": b"h" * 32}),
        )
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
            revision="r1",
            display_name="Production hosts",
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
        await source_store.create_monitoring_source(self.source, secret=None, now=_NOW)
        async with self.engine.begin() as connection:
            for app_id, worker in (
                ("orders", "worker-1"),
                ("orders", "worker-2"),
                ("payments", "worker-1"),
            ):
                await connection.execute(
                    insert(MetricsReporterBindingRecord).values(
                        certificate_principal=f"spiffe://test/{app_id}/{worker}",
                        certificate_sha256=sha256(
                            f"{app_id}/{worker}".encode()
                        ).hexdigest(),
                        reporter_id=f"reporter-{app_id}-{worker}",
                        environment_id="prod",
                        app_id=app_id,
                        instance_id=worker,
                        process_id=f"pid-{worker}",
                        revoked_at=None,
                        current_epoch=None,
                        last_sequence=0,
                        last_elapsed_ns=None,
                        last_received_at=None,
                    )
                )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_shared_host_mapping_is_durable_auditable_and_replayable(self):
        first = await self._put("worker-1", "host-association-create-0001")
        replay = await self._put("worker-1", "host-association-create-0001")
        self.assertEqual(first, replay)

        second = await self._put("worker-2", "host-association-create-0002")
        await self._put("worker-1", "host-association-create-0003", app_id="payments")
        page_one = await self.store.list_host_associations(
            "prod", source_id="prom-prod", app_id="orders", page=1, page_size=1
        )
        page_two = await self.store.list_host_associations(
            "prod", source_id="prom-prod", app_id="orders", page=2, page_size=1
        )
        self.assertEqual((page_one.total, page_two.total), (2, 2))
        self.assertEqual(page_one.associated_host_ids, ("node-shared",))
        self.assertEqual(page_one.items[0].host_id, "node-shared")
        self.assertEqual(page_two.items[0].host_id, "node-shared")
        all_apps = await self.store.list_host_associations(
            "prod", source_id="prom-prod"
        )
        self.assertEqual(all_apps.total, 3)
        self.assertEqual(all_apps.associated_host_ids, ("node-shared",))
        exact_worker = await self.store.list_host_associations(
            "prod",
            source_id="prom-prod",
            app_id="orders",
            instance_id="worker-2",
            page_size=1,
        )
        self.assertEqual(exact_worker.total, 1)
        self.assertEqual(exact_worker.items[0].instance_id, "worker-2")

        await self.engine.dispose()
        self.engine = create_async_engine(_URL, pool_size=3)
        after_restart = await self.store.list_host_associations("prod")
        self.assertEqual(after_restart.total, 3)

        async with self.engine.begin() as connection:
            await connection.execute(
                update(MetricsReporterBindingRecord)
                .where(MetricsReporterBindingRecord.instance_id == "worker-1")
                .values(revoked_at=_NOW)
            )
        revoked = await self.store.list_host_associations(
            "prod", app_id="orders", page=1, page_size=1
        )
        self.assertFalse(revoked.items[0].reporter_active)

        removed = await self.store.delete_host_association(
            environment_id="prod",
            app_id="orders",
            instance_id="worker-2",
            expected_revision=second["revision"],
            request_key="host-association-delete-0002",
            actor_id="account-1",
            session_digest="a" * 64,
            request_id="request-delete-worker-2",
            now=_NOW,
        )
        self.assertEqual(removed, {"removed": True})
        receipt = await self.store.read_host_association_operation(
            "host-association-delete-0002",
            actor_id="account-1",
            session_digest="a" * 64,
        )
        self.assertEqual(receipt, {"removed": True})
        remaining = await self.store.list_host_associations("prod")
        self.assertEqual(remaining.total, 2)

        async with self.engine.connect() as connection:
            action_result = await connection.scalars(
                select(AuditEventRecord.action).order_by(AuditEventRecord.action)
            )
            actions = tuple(action_result.all())
            stored_associations = await connection.scalar(
                select(HostInstanceAssociationRecord.instance_id).where(
                    HostInstanceAssociationRecord.app_id == "orders",
                    HostInstanceAssociationRecord.instance_id == "worker-1",
                )
            )
        self.assertIn("monitoring.host-association.create", actions)
        self.assertIn("monitoring.host-association.delete", actions)
        self.assertEqual(stored_associations, "worker-1")

    async def _put(
        self, instance_id: str, request_key: str, *, app_id: str = "orders"
    ) -> dict[str, object]:
        return await self.store.put_host_association(
            source_id="prom-prod",
            environment_id="prod",
            host_id="node-shared",
            app_id=app_id,
            instance_id=instance_id,
            expected_revision=None,
            request_key=request_key,
            actor_id="account-1",
            session_digest="a" * 64,
            request_id=f"request-{request_key}",
            now=_NOW,
        )
