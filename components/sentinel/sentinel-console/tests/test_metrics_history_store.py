"""SQLite integration contract for the Metrics V2 durable SQL Adapter."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.util.exc import CommandError
from atlas_richie.contracts.reporting.v2 import (
    CounterName,
    CounterReading,
    MetricsSnapshot,
    encode_metrics_snapshot,
)
from metrics_history_process_support import (
    revoke_then_ingest_race,
    terminate_after_uncommitted_snapshot_insert,
)
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from atlas_richie.sentinel_console.application.ingest_metrics import IngestMetrics
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsIngestError,
    MetricsIngestErrorCode,
    MetricsReporterBinding,
    VerifiedMetricsPeer,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_store import (
    SQLAlchemyMetricsHistoryAdapter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    MetricsMinuteRollupRecord,
    MetricsReporterBindingRecord,
    MetricsReporterEpochRecord,
    MetricsSnapshotRecord,
)

_CERTIFICATE = "a" * 64
_PRINCIPAL = "spiffe://sentinel.test/reporter/orders-1"
_BINDING = MetricsReporterBinding(
    certificate_principal=_PRINCIPAL,
    certificate_sha256=_CERTIFICATE,
    reporter_id="reporter-orders-1",
    environment_id="test",
    app_id="orders",
    instance_id="orders-1",
    process_id="orders-1-worker-0",
)


class _EngineProvider:
    """Stand-in for the Console runtime provider in adapter contract tests."""

    def __init__(self, engine):
        self.engine = engine
        self.resolutions = 0

    async def require_engine(self):
        self.resolutions += 1
        return self.engine


class MetricsHistoryStoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-metrics-sqlite-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = f"{self.temporary_directory.name}/history.sqlite3"
        self.database_url = f"sqlite+aiosqlite:///{self.database_path}"
        self.engine = create_async_engine(self.database_url)
        self.addAsyncCleanup(self.engine.dispose)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=_PRINCIPAL,
                    certificate_sha256=_CERTIFICATE,
                    reporter_id=_BINDING.reporter_id,
                    environment_id=_BINDING.environment_id,
                    app_id=_BINDING.app_id,
                    instance_id=_BINDING.instance_id,
                    process_id=_BINDING.process_id,
                    last_sequence=0,
                )
            )
        self.engine_provider = _EngineProvider(self.engine)
        self.store = SQLAlchemyMetricsHistoryAdapter(
            self.engine_provider.require_engine
        )

    async def test_committed_receipt_survives_new_engine_and_exact_replay(self):
        snapshot = _snapshot(sequence=1, elapsed_ns=10_000_000)
        body = encode_metrics_snapshot(snapshot)
        first = await self.store.accept_snapshot(
            binding=_BINDING,
            snapshot=snapshot,
            body=body,
            body_sha256=_digest(body),
            received_at=_instant(0),
        )

        reopened_engine = create_async_engine(self.database_url)
        try:
            reopened_provider = _EngineProvider(reopened_engine)
            reopened = SQLAlchemyMetricsHistoryAdapter(reopened_provider.require_engine)
            binding = await reopened.resolve_certificate(_CERTIFICATE)
            assert binding == _BINDING
            replay = await reopened.accept_snapshot(
                binding=_BINDING,
                snapshot=snapshot,
                body=body,
                body_sha256=_digest(body),
                received_at=_instant(20),
            )
            assert replay == first
            async with async_sessionmaker(reopened_engine)() as session:
                rows = (await session.scalars(select(MetricsSnapshotRecord))).all()
            assert len(rows) == 1
            assert rows[0].body == body
            assert reopened_provider.resolutions == 2
        finally:
            await reopened_engine.dispose()

    async def test_database_engine_is_resolved_lazily_from_runtime_provider(self):
        assert self.engine_provider.resolutions == 0

        assert await self.store.resolve_certificate(_CERTIFICATE) == _BINDING

        assert self.engine_provider.resolutions == 1

    async def test_same_key_with_different_exact_body_is_rejected(self):
        snapshot = _snapshot(sequence=1, elapsed_ns=10_000_000)
        body = encode_metrics_snapshot(snapshot)
        await self._accept(snapshot, body, 0)
        changed_body = body + b" "

        with pytest.raises(MetricsIngestError) as error:
            await self._accept(snapshot, changed_body, 1)

        assert error.value.code is MetricsIngestErrorCode.IDEMPOTENCY_CONFLICT

    async def test_unreceipted_old_sequence_and_elapsed_regression_are_rejected(self):
        epoch = uuid4()
        await self._accept(_snapshot(1, 10_000_000, epoch=epoch), None, 0)
        await self._accept(_snapshot(3, 30_000_000, epoch=epoch), None, 1)

        with pytest.raises(MetricsIngestError) as stale:
            await self._accept(_snapshot(2, 20_000_000, epoch=epoch), None, 2)
        assert stale.value.code is MetricsIngestErrorCode.STALE_SEQUENCE

        with pytest.raises(MetricsIngestError) as regression:
            await self._accept(_snapshot(4, 25_000_000, epoch=epoch), None, 3)
        assert regression.value.code is MetricsIngestErrorCode.ELAPSED_TIME_REGRESSION

    async def test_new_epoch_must_start_at_one_and_old_epoch_cannot_return(self):
        initial_epoch = _snapshot(1, 10_000_000)
        await self._accept(initial_epoch, None, 0)
        next_epoch = _snapshot(1, 0, epoch=uuid4())
        await self._accept(next_epoch, None, 1)

        replay = await self._accept(initial_epoch, None, 2)
        assert replay.startup_epoch == initial_epoch.startup_epoch
        assert replay.sequence == initial_epoch.sequence

        invalid_start = _snapshot(4, 5, epoch=uuid4())
        with pytest.raises(MetricsIngestError) as invalid:
            await self._accept(invalid_start, None, 3)
        assert invalid.value.code is MetricsIngestErrorCode.INVALID_EPOCH

    async def test_revoked_certificate_is_not_resolved_or_accepted(self):
        async with self.sessions.begin() as session:
            record = await session.get(MetricsReporterBindingRecord, _PRINCIPAL)
            record.revoked_at = _instant(0)

        assert await self.store.resolve_certificate(_CERTIFICATE) is None
        with pytest.raises(MetricsIngestError) as error:
            await self._accept(_snapshot(1, 1), None, 1)
        assert error.value.code is MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED

    async def test_retention_deletes_only_expired_raw_and_rollup_rows(self):
        snapshot = _snapshot(1, 10_000_000)
        await self._accept(snapshot, None, 0)
        async with self.sessions.begin() as session:
            session.add(
                MetricsMinuteRollupRecord(
                    rollup_id="r" * 64,
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-1",
                    metric_name="http_qps",
                    bucket_started_at=_instant(0) - timedelta(days=31),
                    payload={"value": 1},
                    expires_at=_instant(0) - timedelta(days=1),
                )
            )

        raw_deleted, rollups_deleted = await self.store.expire_history(
            _instant(0) + timedelta(days=32)
        )
        assert (raw_deleted, rollups_deleted) == (1, 1)
        raw_deleted_again, rollups_deleted_again = await self.store.expire_history(
            _instant(0) + timedelta(days=32)
        )
        assert (raw_deleted_again, rollups_deleted_again) == (0, 0)

    async def test_commit_failure_returns_no_ack_and_rolls_back_all_rows(self):
        def fail_commit(session):
            raise OperationalError(
                "commit", {}, RuntimeError("synthetic commit failure")
            )

        snapshot = _snapshot(1, 10_000_000)
        body = encode_metrics_snapshot(snapshot)
        event.listen(Session, "before_commit", fail_commit)
        try:
            with pytest.raises(MetricsIngestError) as error:
                await self._accept(snapshot, body, 0)
        finally:
            event.remove(Session, "before_commit", fail_commit)

        assert error.value.code is MetricsIngestErrorCode.STORAGE_UNAVAILABLE
        async with self.sessions() as session:
            receipts = (await session.scalars(select(MetricsSnapshotRecord))).all()
            binding = await session.get(MetricsReporterBindingRecord, _PRINCIPAL)
        assert receipts == []
        assert binding.last_sequence == 0
        assert binding.current_epoch is None

    async def test_process_death_before_commit_rolls_back_all_metrics_writes(self):
        snapshot = _snapshot(1, 10_000_000)
        body = encode_metrics_snapshot(snapshot)
        terminate_after_uncommitted_snapshot_insert(
            database_url=self.database_url,
            binding=_BINDING,
            body=body,
            received_at=_instant(0),
        )

        async with self.sessions() as session:
            binding = await session.get(MetricsReporterBindingRecord, _PRINCIPAL)
            epochs = await session.scalar(
                select(func.count())
                .select_from(MetricsReporterEpochRecord)
                .where(MetricsReporterEpochRecord.certificate_principal == _PRINCIPAL)
            )
            snapshots = await session.scalar(
                select(func.count()).select_from(MetricsSnapshotRecord)
            )
        assert binding.last_sequence == 0
        assert binding.current_epoch is None
        assert binding.last_elapsed_ns is None
        assert epochs == 0
        assert snapshots == 0

        receipt = await self._accept(snapshot, body, 0)
        assert receipt.sequence == 1
        async with self.sessions() as session:
            snapshots = await session.scalar(
                select(func.count()).select_from(MetricsSnapshotRecord)
            )
        assert snapshots == 1

    async def test_revocation_write_lock_prevents_concurrent_ingest_ack(self):
        snapshot = _snapshot(1, 10_000_000)
        body = encode_metrics_snapshot(snapshot)
        revoke_result, ingest_result = await asyncio.to_thread(
            revoke_then_ingest_race,
            database_url=self.database_url,
            binding=_BINDING,
            body=body,
            received_at=_instant(0),
        )

        assert revoke_result == ("revoke_result", True)
        assert ingest_result == ("worker_error", "MetricsIngestError")
        async with self.sessions() as session:
            binding = await session.get(MetricsReporterBindingRecord, _PRINCIPAL)
            snapshots = await session.scalar(
                select(func.count()).select_from(MetricsSnapshotRecord)
            )
        assert binding.revoked_at is not None
        assert binding.last_sequence == 0
        assert snapshots == 0

    async def test_ingest_facade_decodes_payload_and_hashes_exact_wire_bytes(self):
        snapshot = _snapshot(1, 10_000_000)
        body = encode_metrics_snapshot(snapshot)
        received_at = _instant(10)
        facade = IngestMetrics(
            self.store,
            self.store,
            clock=lambda: received_at,
        )

        receipt = await facade.execute(VerifiedMetricsPeer(_CERTIFICATE), body)

        assert receipt.reporter_id == _BINDING.reporter_id
        assert receipt.body_sha256 == _digest(body)
        assert receipt.received_at == received_at

    async def test_ingest_facade_rejects_missing_or_mismatched_identity(self):
        body = encode_metrics_snapshot(_snapshot(1, 10_000_000))
        facade = IngestMetrics(self.store, self.store, clock=lambda: _instant(1))
        with pytest.raises(MetricsIngestError) as missing:
            await facade.execute(None, body)
        assert missing.value.code is MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED

        other_peer = VerifiedMetricsPeer("b" * 64)
        with pytest.raises(MetricsIngestError) as unknown:
            await facade.execute(other_peer, body)
        assert unknown.value.code is MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED

    async def test_unknown_migration_revision_is_rejected_without_overwriting_it(self):
        async with self.sessions() as session:
            current_revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert isinstance(current_revision, str)
        async with self.sessions.begin() as session:
            await session.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": "future_schema_revision"},
            )

        try:
            with pytest.raises(CommandError):
                await upgrade_database(self.engine)
        finally:
            async with self.sessions.begin() as session:
                await session.execute(
                    text("UPDATE alembic_version SET version_num = :revision"),
                    {"revision": current_revision},
                )

        async with self.sessions() as session:
            restored_revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert restored_revision == current_revision

    async def _accept(self, snapshot, body, offset_seconds):
        request_body = body or encode_metrics_snapshot(snapshot)
        return await self.store.accept_snapshot(
            binding=_BINDING,
            snapshot=snapshot,
            body=request_body,
            body_sha256=_digest(request_body),
            received_at=_instant(offset_seconds),
        )


def _snapshot(sequence: int, elapsed_ns: int, *, epoch=None) -> MetricsSnapshot:
    return MetricsSnapshot(
        reporter_id=_BINDING.reporter_id,
        startup_epoch=epoch or uuid4(),
        sequence=sequence,
        captured_at=datetime(2026, 10, 14, 1, 2, sequence, tzinfo=UTC),
        capture_elapsed_ns=elapsed_ns,
        counters=(CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, sequence),),
    )


def _instant(offset_seconds: int) -> datetime:
    return datetime(2026, 10, 14, tzinfo=UTC) + timedelta(seconds=offset_seconds)


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()
