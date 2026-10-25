"""Real SQLite acceptance for the installed incident-retention CLI path."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.cli import main
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


def test_incident_retention_cli_deletes_only_expired_rows_from_selected_sqlite(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sentinel-console.sqlite3"
    locator_path = tmp_path / "runtime-locator.json"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    principal = "spiffe://sentinel.test/reporter/retention-worker"
    process_epoch = str(uuid4())
    now = datetime.now(UTC).replace(microsecond=0)
    binding = MetricsReporterBindingRecord(
        certificate_principal=principal,
        certificate_sha256="a" * 64,
        reporter_id="retention-reporter",
        environment_id="retention-test",
        app_id="orders",
        instance_id="orders-worker-0",
        process_id="orders-pid-0",
        current_epoch=process_epoch,
        last_sequence=0,
    )

    def event_record(name: str, expires_at: datetime) -> IncidentEventRecord:
        body = f"synthetic:{name}".encode()
        return IncidentEventRecord(
            incident_id=hashlib.sha256(name.encode()).hexdigest(),
            certificate_principal=principal,
            event_id=str(uuid4()),
            process_epoch=process_epoch,
            environment_id="retention-test",
            app_id="orders",
            instance_id="orders-worker-0",
            process_id="orders-pid-0",
            occurred_at=now,
            received_at=now,
            severity="critical",
            category="resource",
            fact_payload={"metric": "cpu_ratio", "value": 0.95, "threshold": 0.9},
            body_sha256=hashlib.sha256(body).hexdigest(),
            body=body,
            expires_at=expires_at,
        )

    async def seed_database() -> None:
        engine = create_async_engine(database_url)
        try:
            await upgrade_database(engine)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions.begin() as session:
                session.add(binding)
                session.add_all(
                    (
                        event_record("expired", now - timedelta(microseconds=1)),
                        event_record("live", now + timedelta(days=1)),
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(seed_database())

    key = bytes(range(32))
    configuration = RuntimeDatabaseLocatorConfiguration(
        path=locator_path,
        active_key_id="test-key",
        keys={"test-key": key},
    )
    asyncio.run(
        configuration.create_store().write(database_url, expected_revision=None)
    )
    environment = {
        "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": str(locator_path),
        "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": "test-key",
        "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
            "test-key=" + base64.b64encode(key).decode("ascii")
        ),
    }
    output = StringIO()
    with patch.dict("os.environ", environment, clear=True), redirect_stdout(output):
        status = main(["incident-events", "expire"])

    assert status == 0
    assert output.getvalue().strip() == "expired-incidents=1"

    async def read_rows() -> list[IncidentEventRecord]:
        engine = create_async_engine(database_url)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                return list((await session.scalars(select(IncidentEventRecord))).all())
        finally:
            await engine.dispose()

    rows = asyncio.run(read_rows())
    assert len(rows) == 1
    assert rows[0].body == b"synthetic:live"

    second_output = StringIO()
    with (
        patch.dict("os.environ", environment, clear=True),
        redirect_stdout(second_output),
    ):
        second_status = main(["incident-events", "expire"])
    assert second_status == 0
    assert second_output.getvalue().strip() == "expired-incidents=0"
