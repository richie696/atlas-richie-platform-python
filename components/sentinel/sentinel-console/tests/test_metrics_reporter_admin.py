"""Management tests for enrolled Metrics V2 reporter identities."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.manage_metrics_reporters import (
    ManageMetricsReporters,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsReporterBinding,
)
from atlas_richie.sentinel_console.application.metrics_reporter_admin_ports import (
    MetricsReporterAdminError,
    MetricsReporterAdminErrorCode,
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
    MetricsReporterBindingRecord,
)


class MetricsReporterAdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-reporter-admin-", dir="/private/tmp"
        )
        database_url = (
            f"sqlite+aiosqlite:///{Path(self.temporary_directory.name) / 'console.db'}"
        )
        self.engine = create_async_engine(database_url)
        await upgrade_database(self.engine)

        async def resolve_engine():
            return self.engine

        self.store = SqlAlchemyMetricsReporterAdminAdapter(resolve_engine)
        self.clock_value = datetime(2026, 10, 14, 1, 2, tzinfo=UTC)
        self.management = ManageMetricsReporters(
            self.store, clock=lambda: self.clock_value
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temporary_directory.cleanup()

    async def test_enrollment_is_idempotent_and_persists_only_public_binding(self):
        binding = _binding()

        first = await self.management.enroll(binding)
        retry = await self.management.enroll(binding)

        assert first == binding
        assert retry == binding
        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(select(MetricsReporterBindingRecord))
            ).all()
        assert len(rows) == 1
        assert not any(
            "private" in column.name
            for column in MetricsReporterBindingRecord.__table__.columns
        )

    async def test_duplicate_principal_fingerprint_or_reporter_is_rejected(self):
        await self.management.enroll(_binding())
        conflicting_bindings = (
            _binding(certificate_sha256="b" * 64),
            _binding(certificate_principal="spiffe://sentinel.test/reporter/other"),
            _binding(certificate_sha256="b" * 64, reporter_id="reporter-other"),
        )

        for conflicting in conflicting_bindings:
            with pytest.raises(MetricsReporterAdminError) as error:
                await self.management.enroll(conflicting)
            assert error.value.code is MetricsReporterAdminErrorCode.IDENTITY_CONFLICT

    async def test_one_worker_identity_cannot_be_enrolled_twice(self):
        await self.management.enroll(_binding())

        with pytest.raises(MetricsReporterAdminError) as error:
            await self.management.enroll(
                _binding(
                    certificate_principal="spiffe://sentinel.test/reporter/other",
                    certificate_sha256="b" * 64,
                    reporter_id="reporter-other",
                )
            )

        assert error.value.code is MetricsReporterAdminErrorCode.IDENTITY_CONFLICT

    async def test_revoke_is_idempotent_and_revoked_identity_cannot_be_reenrolled(self):
        binding = _binding()
        await self.management.enroll(binding)

        assert await self.management.revoke(binding.certificate_principal)
        revoked_at = await _revoked_at(self.engine, binding.certificate_principal)
        self.clock_value = datetime(2026, 10, 14, 2, 2, tzinfo=UTC)
        assert await self.management.revoke(binding.certificate_principal)
        assert (
            await _revoked_at(self.engine, binding.certificate_principal) == revoked_at
        )
        assert not await self.management.revoke(
            "spiffe://sentinel.test/reporter/missing"
        )

        with pytest.raises(MetricsReporterAdminError) as error:
            await self.management.enroll(binding)
        assert error.value.code is MetricsReporterAdminErrorCode.IDENTITY_CONFLICT

        async def resolve_engine():
            return self.engine

        history = SQLAlchemyMetricsHistoryAdapter(resolve_engine)
        assert await history.resolve_certificate(binding.certificate_sha256) is None

    async def test_invalid_fingerprint_and_untrimmed_scope_fail_before_storage(self):
        invalid_bindings = (
            _binding(certificate_sha256="A" * 64),
            _binding(environment_id=" test"),
            _binding(process_id="worker\n0"),
        )
        for binding in invalid_bindings:
            with pytest.raises(MetricsReporterAdminError) as error:
                await self.management.enroll(binding)
            assert error.value.code is MetricsReporterAdminErrorCode.INVALID_BINDING

        async with self.engine.connect() as connection:
            count = await connection.scalar(
                select(func.count()).select_from(MetricsReporterBindingRecord)
            )
        assert count == 0


def _binding(
    *,
    certificate_principal: str = "spiffe://sentinel.test/reporter/orders-1",
    certificate_sha256: str = "a" * 64,
    reporter_id: str = "reporter-orders-1",
    environment_id: str = "test",
    app_id: str = "orders",
    instance_id: str = "orders-1",
    process_id: str = "orders-worker-0",
) -> MetricsReporterBinding:
    return MetricsReporterBinding(
        certificate_principal=certificate_principal,
        certificate_sha256=certificate_sha256,
        reporter_id=reporter_id,
        environment_id=environment_id,
        app_id=app_id,
        instance_id=instance_id,
        process_id=process_id,
    )


async def _revoked_at(engine, principal: str) -> datetime:
    async with engine.connect() as connection:
        return await connection.scalar(
            select(MetricsReporterBindingRecord.revoked_at).where(
                MetricsReporterBindingRecord.certificate_principal == principal
            )
        )
