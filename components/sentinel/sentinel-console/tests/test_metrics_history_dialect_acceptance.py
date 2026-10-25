"""Opt-in durable Metrics V2 contract against disposable server SQL dialects.

Run only through the repository's disposable PostgreSQL/MySQL wrappers. The
guard rejects non-loopback or non-test databases before opening a connection.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import multiprocessing
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from alembic.util.exc import CommandError
from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    CounterName,
    CounterReading,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
    encode_metrics_snapshot,
)
from metrics_history_process_support import (
    accept_snapshot_in_process,
    revoke_then_ingest_race,
    terminate_after_uncommitted_snapshot_insert,
)
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from atlas_richie.sentinel_console.application.manage_metrics_reporters import (
    ManageMetricsReporters,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsIngestError,
    MetricsIngestErrorCode,
    MetricsReporterBinding,
)
from atlas_richie.sentinel_console.application.metrics_reporter_admin_ports import (
    MetricsReporterAdminError,
    MetricsReporterAdminErrorCode,
)
from atlas_richie.sentinel_console.cli import main
from atlas_richie.sentinel_console.domain.instance_catalog import (
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    MetricQuery,
    ObservationContext,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_reader import (
    SQLAlchemyMetricsHistoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_store import (
    SQLAlchemyMetricsHistoryAdapter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_reporter_admin_adapter import (
    SqlAlchemyMetricsReporterAdminAdapter,
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
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)

_DATABASE_URL_VARIABLES = (
    "SENTINEL_CONSOLE_TEST_POSTGRES_URL",
    "SENTINEL_CONSOLE_TEST_MYSQL_URL",
)


def _disposable_database_url() -> str:
    configured_urls = [
        (name, os.environ[name])
        for name in _DATABASE_URL_VARIABLES
        if os.environ.get(name)
    ]
    if len(configured_urls) != 1:
        raise unittest.SkipTest(
            "run this acceptance through exactly one disposable database wrapper"
        )

    variable, database_url = configured_urls[0]
    parsed = urlsplit(database_url)
    expected_scheme = (
        "postgresql+psycopg"
        if variable == "SENTINEL_CONSOLE_TEST_POSTGRES_URL"
        else "mysql+asyncmy"
    )
    provider = "POSTGRES" if variable.endswith("POSTGRES_URL") else "MYSQL"
    database_name = unquote(parsed.path.removeprefix("/"))
    wrapper_host = os.environ.get(f"SENTINEL_E2E_{provider}_HOST")
    wrapper_port = os.environ.get(f"SENTINEL_E2E_{provider}_PORT")
    wrapper_database = os.environ.get(f"SENTINEL_E2E_{provider}_DATABASE")
    wrapper_user = os.environ.get(f"SENTINEL_E2E_{provider}_USER")
    if (
        parsed.scheme != expected_scheme
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or wrapper_host != parsed.hostname
        or wrapper_port != str(parsed.port)
        or not database_name.startswith("sentinel_console_test_")
        or wrapper_database != database_name
        or parsed.username != "sentinel_e2e"
        or wrapper_user != parsed.username
    ):
        raise unittest.SkipTest(
            "refusing database URL not created by a disposable loopback wrapper"
        )
    return database_url


class MetricsHistoryDialectAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database_url = _disposable_database_url()
        self.engine = create_async_engine(self.database_url, pool_size=4)
        await upgrade_database(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.principal = f"spiffe://sentinel.test/reporter/{uuid4()}"
        self.binding = MetricsReporterBinding(
            certificate_principal=self.principal,
            certificate_sha256=hashlib.sha256(self.principal.encode()).hexdigest(),
            reporter_id=f"reporter-{uuid4()}",
            environment_id="acceptance",
            app_id=f"metrics-dialect-{uuid4()}",
            instance_id="instance-1",
            process_id="process-1",
        )
        async with self.sessions.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=self.binding.certificate_principal,
                    certificate_sha256=self.binding.certificate_sha256,
                    reporter_id=self.binding.reporter_id,
                    environment_id=self.binding.environment_id,
                    app_id=self.binding.app_id,
                    instance_id=self.binding.instance_id,
                    process_id=self.binding.process_id,
                    last_sequence=0,
                )
            )
        self.store = SQLAlchemyMetricsHistoryAdapter(self._resolve_engine)
        self.base_instant = datetime(2026, 10, 14, tzinfo=UTC)
        self.epoch = uuid4()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _resolve_engine(self):
        return self.engine

    async def _accept(self, sequence: int, elapsed_ns: int):
        snapshot = _snapshot(
            sequence,
            elapsed_ns,
            reporter_id=self.binding.reporter_id,
            epoch=self.epoch,
        )
        body = encode_metrics_snapshot(snapshot)
        return await self.store.accept_snapshot(
            binding=self.binding,
            snapshot=snapshot,
            body=body,
            body_sha256=hashlib.sha256(body).hexdigest(),
            received_at=self.base_instant + timedelta(seconds=sequence),
        )

    async def test_concurrent_exact_delivery_is_durable_across_reopen(self) -> None:
        snapshot = _snapshot(
            1,
            10_000_000,
            reporter_id=self.binding.reporter_id,
            epoch=self.epoch,
        )
        body = encode_metrics_snapshot(snapshot)
        arguments = {
            "binding": self.binding,
            "snapshot": snapshot,
            "body": body,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "received_at": self.base_instant,
        }
        receipts = await asyncio.gather(
            self.store.accept_snapshot(**arguments),
            self.store.accept_snapshot(**arguments),
        )
        self.assertEqual(receipts[0], receipts[1])
        async with self.sessions() as session:
            self.assertEqual(
                await session.scalar(
                    select(func.count())
                    .select_from(MetricsSnapshotRecord)
                    .where(
                        MetricsSnapshotRecord.certificate_principal
                        == self.binding.certificate_principal
                    )
                ),
                1,
            )

        await self.engine.dispose()
        self.engine = create_async_engine(self.database_url, pool_size=4)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        reopened_store = SQLAlchemyMetricsHistoryAdapter(self._resolve_engine)
        replay = await reopened_store.accept_snapshot(**arguments)
        self.assertEqual(replay, receipts[0])
        async with self.sessions() as session:
            stored = await session.scalar(
                select(MetricsSnapshotRecord).where(
                    MetricsSnapshotRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
        self.assertEqual(stored.body, body)
        self.assertEqual(stored.body_sha256, arguments["body_sha256"])

        with self.assertRaises(MetricsIngestError) as conflict:
            changed_body = body + b" "
            await reopened_store.accept_snapshot(
                **{
                    **arguments,
                    "body": changed_body,
                    "body_sha256": hashlib.sha256(changed_body).hexdigest(),
                }
            )
        self.assertEqual(
            conflict.exception.code,
            MetricsIngestErrorCode.IDEMPOTENCY_CONFLICT,
        )

    async def test_ack_loss_after_commit_recovers_from_a_new_process(self) -> None:
        snapshot = _snapshot(
            1,
            10_000_000,
            reporter_id=self.binding.reporter_id,
            epoch=self.epoch,
        )
        body = encode_metrics_snapshot(snapshot)
        received_at = self.base_instant
        context = multiprocessing.get_context("spawn")

        first_receipt = _process_receipt(
            context=context,
            database_url=self.database_url,
            binding=self.binding,
            body=body,
            received_at=received_at,
            pause_after_commit=True,
        )
        second_receipt = _process_receipt(
            context=context,
            database_url=self.database_url,
            binding=self.binding,
            body=body,
            received_at=received_at,
            pause_after_commit=False,
        )
        self.assertEqual(second_receipt, first_receipt)
        async with self.sessions() as session:
            row_count = await session.scalar(
                select(func.count())
                .select_from(MetricsSnapshotRecord)
                .where(
                    MetricsSnapshotRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
        self.assertEqual(row_count, 1)

    async def test_process_death_before_commit_rolls_back_receipt_and_sequence(
        self,
    ) -> None:
        snapshot = _snapshot(
            1,
            10_000_000,
            reporter_id=self.binding.reporter_id,
            epoch=self.epoch,
        )
        body = encode_metrics_snapshot(snapshot)
        terminate_after_uncommitted_snapshot_insert(
            database_url=self.database_url,
            binding=self.binding,
            body=body,
            received_at=self.base_instant,
        )

        async with self.sessions() as session:
            binding = await session.get(
                MetricsReporterBindingRecord,
                self.binding.certificate_principal,
            )
            epoch_count = await session.scalar(
                select(func.count())
                .select_from(MetricsReporterEpochRecord)
                .where(
                    MetricsReporterEpochRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
            snapshot_count = await session.scalar(
                select(func.count())
                .select_from(MetricsSnapshotRecord)
                .where(
                    MetricsSnapshotRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
        self.assertEqual(binding.last_sequence, 0)
        self.assertIsNone(binding.current_epoch)
        self.assertIsNone(binding.last_elapsed_ns)
        self.assertEqual(epoch_count, 0)
        self.assertEqual(snapshot_count, 0)

        receipt = await self._accept(1, 10_000_000)
        self.assertEqual(receipt.sequence, 1)
        async with self.sessions() as session:
            snapshot_count = await session.scalar(
                select(func.count())
                .select_from(MetricsSnapshotRecord)
                .where(
                    MetricsSnapshotRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
        self.assertEqual(snapshot_count, 1)

    async def test_enrollment_and_revocation_contract_on_server_dialect(self) -> None:
        binding = MetricsReporterBinding(
            certificate_principal=f"spiffe://sentinel.test/reporter/{uuid4()}",
            certificate_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
            reporter_id=f"reporter-{uuid4()}",
            environment_id="acceptance",
            app_id="metrics-dialect-acceptance",
            instance_id=f"instance-{uuid4()}",
            process_id=f"process-{uuid4()}",
        )
        adapter = SqlAlchemyMetricsReporterAdminAdapter(self._resolve_engine)
        management = ManageMetricsReporters(adapter, clock=lambda: self.base_instant)

        self.assertEqual(await management.enroll(binding), binding)
        self.assertEqual(await management.enroll(binding), binding)
        with self.assertRaises(MetricsReporterAdminError) as conflict:
            await management.enroll(
                replace(
                    binding,
                    certificate_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
                )
            )
        self.assertEqual(
            conflict.exception.code,
            MetricsReporterAdminErrorCode.IDENTITY_CONFLICT,
        )

        self.assertTrue(await management.revoke(binding.certificate_principal))
        self.assertTrue(await management.revoke(binding.certificate_principal))
        self.assertFalse(
            await management.revoke(f"spiffe://sentinel.test/reporter/{uuid4()}")
        )
        with self.assertRaises(MetricsReporterAdminError) as revoked_conflict:
            await management.enroll(binding)
        self.assertEqual(
            revoked_conflict.exception.code,
            MetricsReporterAdminErrorCode.IDENTITY_CONFLICT,
        )
        self.assertIsNone(
            await self.store.resolve_certificate(binding.certificate_sha256)
        )

    async def test_revocation_lock_serializes_with_concurrent_server_ingest(self):
        binding = MetricsReporterBinding(
            certificate_principal=f"spiffe://sentinel.test/reporter/{uuid4()}",
            certificate_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
            reporter_id=f"reporter-{uuid4()}",
            environment_id="acceptance",
            app_id="metrics-dialect-acceptance",
            instance_id=f"instance-{uuid4()}",
            process_id=f"process-{uuid4()}",
        )
        await SqlAlchemyMetricsReporterAdminAdapter(
            self._resolve_engine
        ).enroll_reporter(binding)
        snapshot = _snapshot(
            1,
            10_000_000,
            reporter_id=binding.reporter_id,
            epoch=uuid4(),
        )
        body = encode_metrics_snapshot(snapshot)
        revoke_result, ingest_result = await asyncio.to_thread(
            revoke_then_ingest_race,
            database_url=self.database_url,
            binding=binding,
            body=body,
            received_at=self.base_instant,
        )

        self.assertEqual(revoke_result, ("revoke_result", True))
        self.assertEqual(ingest_result, ("worker_error", "MetricsIngestError"))
        async with self.sessions() as session:
            record = await session.get(
                MetricsReporterBindingRecord,
                binding.certificate_principal,
            )
            snapshot_count = await session.scalar(
                select(func.count())
                .select_from(MetricsSnapshotRecord)
                .where(
                    MetricsSnapshotRecord.certificate_principal
                    == binding.certificate_principal
                )
            )
        self.assertIsNotNone(record.revoked_at)
        self.assertEqual(record.last_sequence, 0)
        self.assertEqual(snapshot_count, 0)

    async def test_operator_cli_enroll_and_revoke_use_selected_server_database(self):
        binding = MetricsReporterBinding(
            certificate_principal=f"spiffe://sentinel.test/reporter/{uuid4()}",
            certificate_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
            reporter_id=f"reporter-{uuid4()}",
            environment_id="acceptance",
            app_id="metrics-dialect-acceptance",
            instance_id=f"instance-{uuid4()}",
            process_id=f"process-{uuid4()}",
        )
        with tempfile.TemporaryDirectory(
            prefix="sentinel-metrics-cli-", dir="/private/tmp"
        ) as temporary:
            locator_path = Path(temporary) / "runtime-locator.json"
            key_id = "metrics-cli-test"
            encryption_key = b"m" * 32
            locator_configuration = RuntimeDatabaseLocatorConfiguration(
                locator_path,
                key_id,
                {key_id: encryption_key},
            )
            await locator_configuration.create_store().write(
                self.database_url,
                expected_revision=None,
            )
            environment = {
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": str(locator_path),
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": key_id,
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
                    f"{key_id}={base64.b64encode(encryption_key).decode('ascii')}"
                ),
            }
            with patch.dict(os.environ, environment):
                enroll_output = StringIO()
                with redirect_stdout(enroll_output):
                    enroll_status = await asyncio.to_thread(
                        main,
                        [
                            "metrics-reporter",
                            "enroll",
                            "--principal",
                            binding.certificate_principal,
                            "--certificate-sha256",
                            binding.certificate_sha256,
                            "--reporter-id",
                            binding.reporter_id,
                            "--environment-id",
                            binding.environment_id,
                            "--app-id",
                            binding.app_id,
                            "--instance-id",
                            binding.instance_id,
                            "--process-id",
                            binding.process_id,
                        ],
                    )
                self.assertEqual(enroll_status, 0)
                self.assertEqual(enroll_output.getvalue().strip(), "reporter-enrolled")
                self.assertNotIn(binding.certificate_sha256, enroll_output.getvalue())
                self.assertEqual(
                    await self.store.resolve_certificate(binding.certificate_sha256),
                    binding,
                )

                revoke_output = StringIO()
                with redirect_stdout(revoke_output):
                    revoke_status = await asyncio.to_thread(
                        main,
                        [
                            "metrics-reporter",
                            "revoke",
                            "--principal",
                            binding.certificate_principal,
                        ],
                    )
                self.assertEqual(revoke_status, 0)
                self.assertEqual(revoke_output.getvalue().strip(), "reporter-revoked")
                self.assertIsNone(
                    await self.store.resolve_certificate(binding.certificate_sha256)
                )

    async def test_concurrent_exact_delivery_from_distinct_processes(self) -> None:
        snapshot = _snapshot(
            1,
            10_000_000,
            reporter_id=self.binding.reporter_id,
            epoch=self.epoch,
        )
        body = encode_metrics_snapshot(snapshot)
        receipts = _concurrent_process_receipts(
            context=multiprocessing.get_context("spawn"),
            database_url=self.database_url,
            binding=self.binding,
            body=body,
            received_at=self.base_instant,
        )
        self.assertEqual(receipts[0], receipts[1])
        async with self.sessions() as session:
            row_count = await session.scalar(
                select(func.count())
                .select_from(MetricsSnapshotRecord)
                .where(
                    MetricsSnapshotRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
        self.assertEqual(row_count, 1)

    async def test_failed_commit_returns_no_receipt_and_preserves_sequence(
        self,
    ) -> None:
        await self._accept(1, 10_000_000)

        def fail_commit(session):
            raise OperationalError("commit", {}, RuntimeError("synthetic failure"))

        event.listen(Session, "before_commit", fail_commit)
        try:
            with self.assertRaises(MetricsIngestError) as failure:
                await self._accept(2, 20_000_000)
        finally:
            event.remove(Session, "before_commit", fail_commit)

        self.assertEqual(
            failure.exception.code, MetricsIngestErrorCode.STORAGE_UNAVAILABLE
        )
        async with self.sessions() as session:
            binding = await session.get(
                MetricsReporterBindingRecord, self.binding.certificate_principal
            )
            count = await session.scalar(
                select(func.count())
                .select_from(MetricsSnapshotRecord)
                .where(
                    MetricsSnapshotRecord.certificate_principal
                    == self.binding.certificate_principal
                )
            )
            rollup_count = await session.scalar(
                select(func.count())
                .select_from(MetricsMinuteRollupRecord)
                .where(
                    MetricsMinuteRollupRecord.reporter_id == self.binding.reporter_id
                )
            )
        self.assertEqual(binding.last_sequence, 1)
        self.assertEqual(count, 1)
        self.assertEqual(rollup_count, 0)
        receipt = await self._accept(2, 20_000_000)
        self.assertEqual(receipt.sequence, 2)
        async with self.sessions() as session:
            self.assertEqual(
                await session.scalar(
                    select(func.count())
                    .select_from(MetricsMinuteRollupRecord)
                    .where(
                        MetricsMinuteRollupRecord.reporter_id
                        == self.binding.reporter_id
                    )
                ),
                1,
            )

    async def test_retention_boundary_is_idempotent_and_preserves_live_rows(
        self,
    ) -> None:
        old = await self._accept(1, 10_000_000)
        async with self.sessions.begin() as session:
            snapshot = await session.get(
                MetricsSnapshotRecord,
                (self.binding.certificate_principal, str(old.startup_epoch), 1),
            )
            snapshot.received_at = self.base_instant - timedelta(hours=25)
            session.add(
                MetricsMinuteRollupRecord(
                    rollup_id=hashlib.sha256(b"expired-rollup").hexdigest(),
                    environment_id=self.binding.environment_id,
                    app_id=self.binding.app_id,
                    instance_id=self.binding.instance_id,
                    metric_name="http_qps",
                    bucket_started_at=self.base_instant - timedelta(days=31),
                    payload={"value": 1},
                    expires_at=self.base_instant - timedelta(seconds=1),
                )
            )
            session.add(
                MetricsMinuteRollupRecord(
                    rollup_id=hashlib.sha256(b"live-rollup").hexdigest(),
                    environment_id=self.binding.environment_id,
                    app_id=self.binding.app_id,
                    instance_id=self.binding.instance_id,
                    metric_name="http_qps",
                    bucket_started_at=self.base_instant,
                    payload={"value": 2},
                    expires_at=self.base_instant + timedelta(days=1),
                )
            )

        counts = await self.store.expire_history(self.base_instant)
        self.assertEqual(counts, (1, 1))
        self.assertEqual(await self.store.expire_history(self.base_instant), (0, 0))
        async with self.sessions() as session:
            raw_rows = (
                await session.scalars(
                    select(MetricsSnapshotRecord).where(
                        MetricsSnapshotRecord.certificate_principal
                        == self.binding.certificate_principal
                    )
                )
            ).all()
            rollups = (
                await session.scalars(
                    select(MetricsMinuteRollupRecord).where(
                        MetricsMinuteRollupRecord.rollup_id.in_(
                            [
                                hashlib.sha256(b"expired-rollup").hexdigest(),
                                hashlib.sha256(b"live-rollup").hexdigest(),
                            ]
                        )
                    )
                )
            ).all()
        self.assertEqual(raw_rows, [])
        self.assertEqual(len(rollups), 1)
        self.assertEqual(
            rollups[0].rollup_id, hashlib.sha256(b"live-rollup").hexdigest()
        )

    async def test_unknown_migration_revision_is_rejected_without_overwriting_it(
        self,
    ) -> None:
        async with self.sessions() as session:
            current_revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        self.assertIsInstance(current_revision, str)
        async with self.sessions.begin() as session:
            await session.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": "future_schema_revision"},
            )

        try:
            with self.assertRaises(CommandError):
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
        self.assertEqual(restored_revision, current_revision)

    async def test_rollup_query_aggregates_two_reporters_and_pools_histograms(
        self,
    ) -> None:
        """The same durable rollup/query contract must hold on each SQL dialect."""
        second_binding = MetricsReporterBinding(
            certificate_principal=f"spiffe://sentinel.test/reporter/{uuid4()}",
            certificate_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
            reporter_id=f"reporter-{uuid4()}",
            environment_id=self.binding.environment_id,
            app_id=self.binding.app_id,
            instance_id="instance-2",
            process_id="process-2",
        )
        async with self.sessions.begin() as session:
            session.add(
                MetricsReporterBindingRecord(
                    certificate_principal=second_binding.certificate_principal,
                    certificate_sha256=second_binding.certificate_sha256,
                    reporter_id=second_binding.reporter_id,
                    environment_id=second_binding.environment_id,
                    app_id=second_binding.app_id,
                    instance_id=second_binding.instance_id,
                    process_id=second_binding.process_id,
                    last_sequence=0,
                )
            )

        first_epoch = self.epoch
        second_epoch = uuid4()
        observations = (
            (self.binding, first_epoch, 100, 140, 1, 0, 1_000_000_000),
            (second_binding, second_epoch, 200, 260, 0, 1, 2_000_000_000),
        )
        for (
            binding,
            epoch,
            baseline,
            current,
            finite,
            overflow,
            interval_ns,
        ) in observations:
            for sequence, elapsed, http_count, finite_count, overflow_count in (
                (1, 1_000_000_000, baseline, 0, 0),
                (2, 1_000_000_000 + interval_ns, current, finite, overflow),
            ):
                snapshot = _rollup_snapshot(
                    sequence=sequence,
                    elapsed_ns=elapsed,
                    http_count=http_count,
                    histogram_finite=finite_count,
                    histogram_overflow=overflow_count,
                    reporter_id=binding.reporter_id,
                    epoch=epoch,
                )
                body = encode_metrics_snapshot(snapshot)
                await self.store.accept_snapshot(
                    binding=binding,
                    snapshot=snapshot,
                    body=body,
                    body_sha256=hashlib.sha256(body).hexdigest(),
                    received_at=self.base_instant
                    + timedelta(
                        seconds=sequence + (0 if binding is self.binding else 5)
                    ),
                )

        query = MetricQuery(
            context=ObservationContext(
                environment_id=self.binding.environment_id,
                app_id=self.binding.app_id,
                instance_id=None,
                resource=None,
                scope=ObservationScope.APPLICATION,
                window=ObservationWindow(
                    self.base_instant,
                    self.base_instant + timedelta(minutes=1),
                ),
            ),
            metrics=("http_qps", "rt_p95"),
            step_ms=60_000,
        )
        bundle = await SQLAlchemyMetricsHistoryReader(
            self._resolve_engine
        ).read_metrics(query)

        self.assertEqual(bundle.query, query)
        self.assertEqual(bundle.summary[0].value, 100 / 3)
        self.assertEqual(bundle.summary[0].coverage.reporting, 2)
        self.assertIsNone(bundle.summary[1].value)
        self.assertEqual(bundle.summary[1].quality.value, "partial")
        async with self.sessions() as session:
            rollups = (
                await session.scalars(
                    select(MetricsMinuteRollupRecord).where(
                        MetricsMinuteRollupRecord.app_id == self.binding.app_id
                    )
                )
            ).all()
        self.assertEqual(
            sum(row.metric_name == "http_qps" for row in rollups),
            2,
        )
        self.assertEqual(
            sum(row.metric_name == "rt_p95" for row in rollups),
            2,
        )


def _snapshot(
    sequence: int, elapsed_ns: int, *, reporter_id: str, epoch
) -> MetricsSnapshot:
    return MetricsSnapshot(
        reporter_id=reporter_id,
        startup_epoch=epoch,
        sequence=sequence,
        captured_at=datetime(2026, 10, 14, tzinfo=UTC),
        capture_elapsed_ns=elapsed_ns,
        counters=(CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, sequence),),
    )


def _rollup_snapshot(
    *,
    sequence: int,
    elapsed_ns: int,
    http_count: int,
    histogram_finite: int,
    histogram_overflow: int,
    reporter_id: str,
    epoch,
) -> MetricsSnapshot:
    """Create a cumulative HTTP counter/histogram reading for rollup acceptance."""
    counts = [0] * (len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1)
    counts[0] = histogram_finite
    counts[-1] = histogram_overflow
    sample_count = histogram_finite + histogram_overflow
    return MetricsSnapshot(
        reporter_id=reporter_id,
        startup_epoch=epoch,
        sequence=sequence,
        captured_at=datetime(2026, 10, 14, tzinfo=UTC),
        capture_elapsed_ns=elapsed_ns,
        counters=(CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, http_count),),
        histograms=(
            HistogramReading(
                HistogramName.HTTP_REQUEST_DURATION,
                HTTP_REQUEST_DURATION_BOUNDARIES_NS,
                tuple(counts),
                sample_count,
                histogram_finite * 1_000_000 + histogram_overflow * 20_000_000_000,
                1_000_000 if sample_count else None,
                20_000_000_000
                if histogram_overflow
                else 1_000_000
                if sample_count
                else None,
            ),
        ),
    )


def _process_receipt(
    *,
    context,
    database_url: str,
    binding: MetricsReporterBinding,
    body: bytes,
    received_at: datetime,
    pause_after_commit: bool,
) -> tuple[str, str, int, str, str]:
    receiver, sender = context.Pipe(duplex=False)
    pause_event = context.Event() if pause_after_commit else None
    process = context.Process(
        target=accept_snapshot_in_process,
        args=(database_url, binding, body, received_at, sender, pause_event, None),
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(30):
            process.terminate()
            process.join(timeout=10)
            raise AssertionError("child process did not return a durable receipt")
        receipt = receiver.recv()
    finally:
        receiver.close()

    if pause_after_commit:
        process.terminate()
    process.join(timeout=15)
    if process.is_alive():
        process.kill()
        process.join(timeout=10)
        raise AssertionError("child process did not stop after the ACK-loss scenario")
    if pause_after_commit:
        if process.exitcode == 0:
            raise AssertionError(
                "first process was expected to be terminated post-commit"
            )
    elif process.exitcode != 0:
        raise AssertionError(f"replay process failed with exit code {process.exitcode}")
    return receipt


def _concurrent_process_receipts(
    *,
    context,
    database_url: str,
    binding: MetricsReporterBinding,
    body: bytes,
    received_at: datetime,
) -> tuple[tuple[str, str, int, str, str], tuple[str, str, int, str, str]]:
    start_event = context.Event()
    children = []
    for _ in range(2):
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=accept_snapshot_in_process,
            args=(database_url, binding, body, received_at, sender, None, start_event),
        )
        process.start()
        sender.close()
        children.append((receiver, process))

    start_event.set()
    receipts = []
    try:
        for receiver, process in children:
            if not receiver.poll(30):
                raise AssertionError("concurrent child did not return a receipt")
            receipts.append(receiver.recv())
            process.join(timeout=15)
            if process.is_alive():
                raise AssertionError("concurrent child did not exit after receipt")
            if process.exitcode != 0:
                raise AssertionError(
                    f"concurrent child failed with exit code {process.exitcode}"
                )
    finally:
        for receiver, process in children:
            receiver.close()
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
            if process.is_alive():
                process.kill()
                process.join(timeout=10)
    if len(receipts) != 2:
        raise AssertionError("both concurrent process receipts are required")
    return receipts[0], receipts[1]
