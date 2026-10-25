"""SQLAlchemy Adapter for Metrics V2 reporter enrollment and revocation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.metrics_ingest_ports import MetricsReporterBinding
from ...application.metrics_reporter_admin_ports import (
    MetricsReporterAdminError,
    MetricsReporterAdminErrorCode,
    MetricsReporterAdministration,
)
from .models import MetricsReporterBindingRecord


class SqlAlchemyMetricsReporterAdminAdapter(MetricsReporterAdministration):
    """Own reporter identity writes, separate from snapshot history persistence."""

    def __init__(self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]) -> None:
        self._engine_resolver = engine_resolver

    async def enroll_reporter(
        self, binding: MetricsReporterBinding
    ) -> MetricsReporterBinding:
        """Insert an active binding, allowing only exact active retries."""
        try:
            sessions = await self._session_factory()
            async with sessions.begin() as session:
                existing = await session.scalar(
                    select(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.certificate_principal
                        == binding.certificate_principal
                    )
                    .with_for_update()
                )
                if existing is not None:
                    return self._resolve_existing(existing, binding)
                worker_owner = await session.scalar(
                    select(MetricsReporterBindingRecord).where(
                        MetricsReporterBindingRecord.environment_id
                        == binding.environment_id,
                        MetricsReporterBindingRecord.app_id == binding.app_id,
                        MetricsReporterBindingRecord.instance_id == binding.instance_id,
                    )
                )
                if worker_owner is not None:
                    raise MetricsReporterAdminError(
                        MetricsReporterAdminErrorCode.IDENTITY_CONFLICT
                    )
                session.add(
                    MetricsReporterBindingRecord(
                        certificate_principal=binding.certificate_principal,
                        certificate_sha256=binding.certificate_sha256,
                        reporter_id=binding.reporter_id,
                        environment_id=binding.environment_id,
                        app_id=binding.app_id,
                        instance_id=binding.instance_id,
                        process_id=binding.process_id,
                        last_sequence=0,
                    )
                )
            return binding
        except MetricsReporterAdminError:
            raise
        except IntegrityError:
            duplicate = await self._read_principal(binding.certificate_principal)
            if duplicate is not None:
                return self._resolve_existing(duplicate, binding)
            raise MetricsReporterAdminError(
                MetricsReporterAdminErrorCode.IDENTITY_CONFLICT
            ) from None
        except SQLAlchemyError:
            raise MetricsReporterAdminError(
                MetricsReporterAdminErrorCode.STORAGE_UNAVAILABLE
            ) from None

    async def revoke_reporter(
        self, certificate_principal: str, revoked_at: datetime
    ) -> bool:
        """Serialize revocation with ingestion by updating the binding row."""
        if revoked_at.tzinfo is None or revoked_at.utcoffset() != UTC.utcoffset(
            revoked_at
        ):
            raise ValueError("revocation time must be aware UTC")
        try:
            sessions = await self._session_factory()
            async with sessions.begin() as session:
                # Acquire the same write lock as ingestion. PostgreSQL/MySQL
                # also honor the row lock below; SQLite does not implement
                # SELECT ... FOR UPDATE, so the no-op UPDATE is the shared
                # serialization point across all supported dialects.
                await session.execute(
                    update(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.certificate_principal
                        == certificate_principal
                    )
                    .values(last_sequence=MetricsReporterBindingRecord.last_sequence)
                )
                existing = await session.scalar(
                    select(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.certificate_principal
                        == certificate_principal
                    )
                    .with_for_update()
                )
                if existing is None:
                    return False
                if existing.revoked_at is None:
                    existing.revoked_at = revoked_at.astimezone(UTC)
            return True
        except SQLAlchemyError:
            raise MetricsReporterAdminError(
                MetricsReporterAdminErrorCode.STORAGE_UNAVAILABLE
            ) from None

    async def _session_factory(self) -> async_sessionmaker[AsyncSession]:
        engine = await self._engine_resolver()
        return async_sessionmaker(engine, expire_on_commit=False)

    async def _read_principal(
        self, certificate_principal: str
    ) -> MetricsReporterBindingRecord | None:
        try:
            sessions = await self._session_factory()
            async with sessions() as session:
                return await session.scalar(
                    select(MetricsReporterBindingRecord).where(
                        MetricsReporterBindingRecord.certificate_principal
                        == certificate_principal
                    )
                )
        except SQLAlchemyError:
            raise MetricsReporterAdminError(
                MetricsReporterAdminErrorCode.STORAGE_UNAVAILABLE
            ) from None

    @staticmethod
    def _resolve_existing(
        record: MetricsReporterBindingRecord, requested: MetricsReporterBinding
    ) -> MetricsReporterBinding:
        if record.revoked_at is None:
            existing = MetricsReporterBinding(
                certificate_principal=record.certificate_principal,
                certificate_sha256=record.certificate_sha256,
                reporter_id=record.reporter_id,
                environment_id=record.environment_id,
                app_id=record.app_id,
                instance_id=record.instance_id,
                process_id=record.process_id,
            )
            if existing == requested:
                return existing
        raise MetricsReporterAdminError(MetricsReporterAdminErrorCode.IDENTITY_CONFLICT)


__all__ = ["SqlAlchemyMetricsReporterAdminAdapter"]
