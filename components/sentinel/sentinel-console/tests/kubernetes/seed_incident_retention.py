"""Seed and verify disposable rows for the Kubernetes retention Job test."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    IncidentEventRecord,
    MetricsReporterBindingRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_DATABASE_PATH_ENV = "SENTINEL_CONSOLE_TEST_DATABASE_PATH"
_EXPIRED_BODY = b"synthetic:kubernetes-retention-expired"
_LIVE_BODY = b"synthetic:kubernetes-retention-live"


class IncidentRetentionKubernetesSeeder:
    """Prepare an encrypted locator and disposable incident rows on a PVC."""

    def __init__(self, database_path: Path) -> None:
        if not database_path.is_absolute():
            raise ValueError("acceptance database path must be absolute")
        self._database_path = database_path
        self._database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    async def seed(self) -> None:
        """Migrate the disposable SQLite DB, write its locator, and seed rows."""
        await self._write_locator()
        engine = create_async_engine(self._database_url)
        try:
            await upgrade_database(engine)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions.begin() as session:
                binding, events = self._records()
                session.add(binding)
                session.add_all(events)
        finally:
            await engine.dispose()
        print("retention-seed=ready expired=1 live=1")

    async def verify(self) -> None:
        """Require physical cleanup of expired data and retention of live data."""
        engine = create_async_engine(self._database_url)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                bodies = list(
                    (await session.scalars(select(IncidentEventRecord.body))).all()
                )
        finally:
            await engine.dispose()
        if bodies != [_LIVE_BODY]:
            raise RuntimeError("retention acceptance database state is unexpected")
        print("retention-verify=passed expired=0 live=1")

    async def _write_locator(self) -> None:
        configuration = RuntimeDatabaseLocatorConfiguration.from_environment()
        await configuration.create_store().write(
            self._database_url,
            expected_revision=None,
        )

    @staticmethod
    def _records() -> tuple[
        MetricsReporterBindingRecord, tuple[IncidentEventRecord, ...]
    ]:
        now = datetime.now(UTC).replace(microsecond=0)
        principal = "spiffe://sentinel.test/reporter/kubernetes-retention"
        process_epoch = str(uuid4())
        binding = MetricsReporterBindingRecord(
            certificate_principal=principal,
            certificate_sha256="a" * 64,
            reporter_id="kubernetes-retention-reporter",
            environment_id="acceptance",
            app_id="retention-test",
            instance_id="retention-worker-0",
            process_id="retention-process-0",
            current_epoch=process_epoch,
            last_sequence=0,
        )

        def event_record(body: bytes, expires_at: datetime) -> IncidentEventRecord:
            event_name = body.decode("ascii")
            return IncidentEventRecord(
                incident_id=hashlib.sha256(body).hexdigest(),
                certificate_principal=principal,
                event_id=str(uuid4()),
                process_epoch=process_epoch,
                environment_id="acceptance",
                app_id="retention-test",
                instance_id="retention-worker-0",
                process_id="retention-process-0",
                occurred_at=now,
                received_at=now,
                severity="warning",
                category="resource",
                fact_payload={"fixture": event_name},
                body_sha256=hashlib.sha256(body).hexdigest(),
                body=body,
                expires_at=expires_at,
            )

        events = (
            event_record(_EXPIRED_BODY, now - timedelta(microseconds=1)),
            event_record(_LIVE_BODY, now + timedelta(days=1)),
        )
        return binding, events


def main() -> int:
    """Run one explicit acceptance operation without logging secrets."""
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed", "verify"))
    arguments = parser.parse_args()
    database_path = Path(os.environ[_DATABASE_PATH_ENV])
    acceptance = IncidentRetentionKubernetesSeeder(database_path)
    operation = acceptance.seed if arguments.operation == "seed" else acceptance.verify
    asyncio.run(operation())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
