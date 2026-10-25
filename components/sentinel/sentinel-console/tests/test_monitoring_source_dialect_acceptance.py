"""Monitoring-source migrations and atomic commands on disposable SQL dialects."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from urllib.parse import unquote
from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.monitoring_source_registry import (
    ManageMonitoringSource,
    MonitoringCredentialUpdateMode,
    MonitoringSourceMutation,
    MonitoringSourceOperationReason,
    MonitoringSourceOperationStatus,
    MonitoringSourceSecret,
)
from atlas_richie.sentinel_console.domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    HostInstanceAssociationRecord,
    MonitoringSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_source_store import (
    SQLAlchemyMonitoringSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)


def _disposable_database_url() -> str:
    choices = (
        ("SENTINEL_CONSOLE_TEST_POSTGRES_URL", "POSTGRES", "postgresql+psycopg"),
        ("SENTINEL_CONSOLE_TEST_MYSQL_URL", "MYSQL", "mysql+asyncmy"),
    )
    configured = [
        (name, provider, scheme, os.environ[name])
        for name, provider, scheme in choices
        if os.environ.get(name)
    ]
    if len(configured) != 1:
        raise unittest.SkipTest("run through one disposable SQL acceptance wrapper")
    name, provider, scheme, value = configured[0]
    parsed = make_url(value)
    database = unquote(parsed.database or "")
    if (
        parsed.drivername != scheme
        or parsed.host != "127.0.0.1"
        or parsed.port is None
        or parsed.username != "sentinel_e2e"
        or not database.startswith("sentinel_console_test_")
        or os.environ.get(f"SENTINEL_E2E_{provider}_HOST") != "127.0.0.1"
        or os.environ.get(f"SENTINEL_E2E_{provider}_PORT") != str(parsed.port)
        or os.environ.get(f"SENTINEL_E2E_{provider}_DATABASE") != database
        or os.environ.get(f"SENTINEL_E2E_{provider}_USER") != parsed.username
    ):
        raise unittest.SkipTest(f"refusing {name} URL not issued by disposable wrapper")
    return value


class MonitoringSourceDialectAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_atomic_commands_and_safe_readback(self) -> None:
        engine = create_async_engine(_disposable_database_url(), pool_size=3)
        self.addAsyncCleanup(engine.dispose)
        await upgrade_database(engine)
        now = datetime.now(UTC)
        account_id = str(uuid4())
        source_id = f"monitoring-{uuid4()}"
        request_key = f"monitor-create-{uuid4()}"
        secret_key = b"m" * 32
        fingerprint_key = b"f" * 32

        async with engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=f"admin-{uuid4().hex[:12]}",
                    username_key=uuid4().hex * 2,
                    password_hash="argon2id$acceptance-test",
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

        store = SQLAlchemyMonitoringSourceStore(
            resolve_engine,
            AesGcmSecretCipher("monitoring-v1", {"monitoring-v1": secret_key}),
            fingerprint_key=fingerprint_key,
        )
        source = MonitoringSource(
            source_id=source_id,
            revision="draft-revision",
            display_name="Disposable Prometheus",
            environment_id="dialect-acceptance",
            endpoint="http://127.0.0.1:9090",
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
        session_digest = "s" * 64
        create_command = MonitoringSourceMutation(
            request_key=request_key,
            kind="create",
            actor_id=account_id,
            session_digest=session_digest,
            request_id=str(uuid4()),
            source=source,
            credential_update=MonitoringCredentialUpdateMode.REPLACE,
            secret=MonitoringSourceSecret(bearer_token="acceptance-only-secret"),
            skip_check=True,
            now=now,
        )
        manager = ManageMonitoringSource(store, fingerprint_key)
        created = await manager.execute(create_command)
        replayed = await manager.execute(create_command)
        self.assertEqual(created.status, MonitoringSourceOperationStatus.COMPLETED)
        self.assertEqual(created, replayed)
        self.assertFalse(created.verified)
        self.assertIsNotNone(created.source_revision)

        listed = await store.read_monitoring_sources()
        self.assertEqual([item.source_id for item in listed.items], [source_id])
        current = await store.read_monitoring_source(source_id)
        self.assertEqual(current.revision, created.source_revision)

        async with engine.begin() as connection:
            await connection.execute(
                insert(HostInstanceAssociationRecord).values(
                    environment_id=source.environment_id,
                    app_id="orders",
                    instance_id="orders-1",
                    source_id=source_id,
                    host_id="host-1",
                    revision="association-revision-1",
                    created_at=now,
                    updated_at=now,
                )
            )
        rejected_delete = await store.execute_monitoring_source_mutation(
            MonitoringSourceMutation(
                request_key=f"monitor-in-use-{uuid4()}",
                kind="delete",
                actor_id=account_id,
                session_digest=session_digest,
                request_id=str(uuid4()),
                source_id=source_id,
                expected_revision=current.revision,
                now=now,
            )
        )
        self.assertEqual(rejected_delete.status, MonitoringSourceOperationStatus.REJECTED)
        self.assertEqual(rejected_delete.reason, MonitoringSourceOperationReason.SOURCE_IN_USE)
        self.assertEqual(await store.read_monitoring_source(source_id), current)

        disabled = await store.execute_monitoring_source_mutation(
            MonitoringSourceMutation(
                request_key=f"monitor-disable-{uuid4()}",
                kind="set-enabled",
                actor_id=account_id,
                session_digest=session_digest,
                request_id=str(uuid4()),
                source_id=source_id,
                expected_revision=current.revision,
                enabled=False,
                now=now,
            )
        )
        self.assertEqual(disabled.status, MonitoringSourceOperationStatus.COMPLETED)
        self.assertFalse(disabled.enabled)
        updated = await store.read_monitoring_source(source_id)
        self.assertFalse(updated.enabled)
        self.assertNotEqual(updated.revision, current.revision)
        self.assertEqual(
            await store.resolve_monitoring_source_secret(
                source_id, expected_revision=updated.revision
            ),
            MonitoringSourceSecret(bearer_token="acceptance-only-secret"),
        )

        receipt = await store.read_monitoring_source_operation(
            request_key, actor_id=account_id, session_digest=session_digest
        )
        self.assertEqual(receipt, created)
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    MonitoringSourceRecord.__table__.select().where(
                        MonitoringSourceRecord.source_id == source_id
                    )
                )
            ).mappings().one()
        self.assertNotIn(b"acceptance-only-secret", row["credential_payload"])


if __name__ == "__main__":
    unittest.main()
