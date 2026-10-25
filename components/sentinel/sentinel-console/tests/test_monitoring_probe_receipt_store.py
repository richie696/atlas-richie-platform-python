import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.check_monitoring_source import (
    MonitoringSourceCheckReceipt,
)
from atlas_richie.sentinel_console.application.monitoring_probe import (
    MonitoringIdentityPreview,
    MonitoringProbeConnection,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
    MonitoringProbeResult,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    MonitoringProbeReceiptRecord,
    MonitoringSourceRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.monitoring_probe_receipt_store import (
    SQLAlchemyMonitoringProbeReceiptStore,
)

_NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


class MonitoringProbeReceiptStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id="account-admin",
                    username="admin",
                    username_key="a" * 64,
                    password_hash="argon2id$test-hash",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    last_login_at=None,
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )

        async def engine_resolver():
            return self.engine

        self.store = SQLAlchemyMonitoringProbeReceiptStore(engine_resolver)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_receipt_round_trips_and_requires_exact_account_and_session(self):
        receipt = _receipt()
        await self.store.record_monitoring_probe_receipt(receipt)

        actual = await self.store.read_monitoring_probe_receipt(
            receipt.check_id,
            actor_id=receipt.actor_id,
            session_digest=receipt.session_digest,
            now=_NOW + timedelta(minutes=1),
        )
        wrong_session = await self.store.read_monitoring_probe_receipt(
            receipt.check_id,
            actor_id=receipt.actor_id,
            session_digest="b" * 64,
            now=_NOW + timedelta(minutes=1),
        )
        wrong_account = await self.store.read_monitoring_probe_receipt(
            receipt.check_id,
            actor_id="another-account",
            session_digest=receipt.session_digest,
            now=_NOW + timedelta(minutes=1),
        )

        assert actual == receipt
        assert wrong_session is None
        assert wrong_account is None

    async def test_expired_receipt_is_not_returned_and_is_deleted(self):
        receipt = _receipt()
        await self.store.record_monitoring_probe_receipt(receipt)

        result = await self.store.read_monitoring_probe_receipt(
            receipt.check_id,
            actor_id=receipt.actor_id,
            session_digest=receipt.session_digest,
            now=receipt.expires_at,
        )
        async with self.engine.connect() as connection:
            row = await connection.scalar(
                select(MonitoringProbeReceiptRecord.check_id).where(
                    MonitoringProbeReceiptRecord.check_id == receipt.check_id
                )
            )

        assert result is None
        assert row is None

    async def test_receipt_schema_contains_no_endpoint_or_secret_fields(self):
        column_names = {
            column.name for column in MonitoringProbeReceiptRecord.__table__.columns
        }

        assert column_names.isdisjoint(
            {
                "endpoint",
                "authorization",
                "password",
                "token",
                "credential_reference",
                "promql",
                "labels",
                "raw_response",
            }
        )

    async def test_monitoring_source_migration_has_only_ciphertext_credential_storage(
        self,
    ):
        column_names = {
            column.name for column in MonitoringSourceRecord.__table__.columns
        }
        async with self.engine.connect() as connection:
            source_table_exists = await connection.run_sync(
                lambda sync_connection: sync_connection.dialect.has_table(
                    sync_connection, "console_monitoring_source"
                )
            )

        assert source_table_exists
        assert {
            "credential_cipher_format",
            "credential_key_id",
            "credential_payload",
        }.issubset(column_names)
        assert column_names.isdisjoint(
            {"username", "password", "bearer_token", "token", "credential_reference"}
        )


def _receipt() -> MonitoringSourceCheckReceipt:
    result = MonitoringProbeResult(
        connection=MonitoringProbeConnection.REACHABLE,
        query_api=MonitoringProbeQueryApi.AVAILABLE,
        profile=MonitoringProbeProfile.SUPPORTED,
        identity=MonitoringIdentityPreview(2, 1, 1, 0),
    )
    return MonitoringSourceCheckReceipt(
        check_id="9d42821b-501d-4f3c-af9a-36cbe42167f4",
        source_id="monitoring-candidate",
        source_revision="revision-1",
        actor_id="account-admin",
        session_digest="a" * 64,
        candidate_fingerprint="c" * 64,
        checked_at=_NOW,
        expires_at=_NOW + timedelta(minutes=10),
        result=result,
    )
