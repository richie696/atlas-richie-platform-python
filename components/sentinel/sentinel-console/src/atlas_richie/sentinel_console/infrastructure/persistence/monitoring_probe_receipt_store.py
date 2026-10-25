"""SQL Adapter for short-lived, session-owned monitoring check receipts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from secrets import compare_digest

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.check_monitoring_source import (
    MonitoringProbeReceiptAuthorityUnavailable,
    MonitoringProbeReceiptReader,
    MonitoringProbeReceiptRecorder,
    MonitoringSourceCheckReceipt,
)
from ...application.monitoring_probe import (
    MonitoringIdentityPreview,
    MonitoringProbeConnection,
    MonitoringProbeFailure,
    MonitoringProbeProfile,
    MonitoringProbeQueryApi,
    MonitoringProbeResult,
)
from .models import MonitoringProbeReceiptRecord


class SQLAlchemyMonitoringProbeReceiptStore(
    MonitoringProbeReceiptRecorder, MonitoringProbeReceiptReader
):
    """Persist only finite probe facts and enforce account/session ownership."""

    def __init__(self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]) -> None:
        self._engine_resolver = engine_resolver

    async def record_monitoring_probe_receipt(
        self, receipt: MonitoringSourceCheckReceipt
    ) -> None:
        """Commit one receipt without endpoint, PromQL, credential or labels."""
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                await session.execute(
                    delete(MonitoringProbeReceiptRecord).where(
                        MonitoringProbeReceiptRecord.expires_at <= receipt.checked_at
                    )
                )
                session.add(
                    MonitoringProbeReceiptRecord(
                        check_id=receipt.check_id,
                        source_id=receipt.source_id,
                        source_revision=receipt.source_revision,
                        actor_account_id=receipt.actor_id,
                        session_hash=receipt.session_digest,
                        candidate_fingerprint=receipt.candidate_fingerprint,
                        checked_at=_utc(receipt.checked_at),
                        expires_at=_utc(receipt.expires_at),
                        connection=receipt.result.connection.value,
                        query_api=receipt.result.query_api.value,
                        profile=receipt.result.profile.value,
                        failure=(
                            receipt.result.failure.value
                            if receipt.result.failure is not None
                            else None
                        ),
                        observed_count=receipt.result.identity.observed,
                        unique_count=receipt.result.identity.unique,
                        missing_count=receipt.result.identity.missing,
                        conflicting_count=receipt.result.identity.conflicting,
                    )
                )
        except SQLAlchemyError:
            raise MonitoringProbeReceiptAuthorityUnavailable from None

    async def read_monitoring_probe_receipt(
        self,
        check_id: str,
        *,
        actor_id: str,
        session_digest: str,
        now: datetime,
    ) -> MonitoringSourceCheckReceipt | None:
        """Return a live receipt only to its originating account and session."""
        if not check_id or not actor_id or len(session_digest) != 64:
            return None
        instant = _utc(now)
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                record = await session.scalar(
                    select(MonitoringProbeReceiptRecord)
                    .where(
                        MonitoringProbeReceiptRecord.check_id == check_id,
                        MonitoringProbeReceiptRecord.actor_account_id == actor_id,
                    )
                    .with_for_update()
                )
                if record is None:
                    return None
                if not compare_digest(record.session_hash, session_digest):
                    return None
                expires_at = _utc(record.expires_at)
                if expires_at <= instant:
                    await session.execute(
                        delete(MonitoringProbeReceiptRecord).where(
                            MonitoringProbeReceiptRecord.check_id == check_id
                        )
                    )
                    return None
                return _receipt(record)
        except SQLAlchemyError:
            raise MonitoringProbeReceiptAuthorityUnavailable from None

    async def _session_factory(self) -> async_sessionmaker[AsyncSession]:
        engine = await self._engine_resolver()
        return async_sessionmaker(engine, expire_on_commit=False)


def _receipt(record: MonitoringProbeReceiptRecord) -> MonitoringSourceCheckReceipt:
    try:
        result = MonitoringProbeResult(
            connection=MonitoringProbeConnection(record.connection),
            query_api=MonitoringProbeQueryApi(record.query_api),
            profile=MonitoringProbeProfile(record.profile),
            identity=MonitoringIdentityPreview(
                observed=record.observed_count,
                unique=record.unique_count,
                missing=record.missing_count,
                conflicting=record.conflicting_count,
            ),
            failure=(
                MonitoringProbeFailure(record.failure)
                if record.failure is not None
                else None
            ),
        )
        return MonitoringSourceCheckReceipt(
            check_id=record.check_id,
            source_id=record.source_id,
            source_revision=record.source_revision,
            actor_id=record.actor_account_id,
            session_digest=record.session_hash,
            candidate_fingerprint=record.candidate_fingerprint,
            checked_at=_utc(record.checked_at),
            expires_at=_utc(record.expires_at),
            result=result,
        )
    except (TypeError, ValueError):
        raise MonitoringProbeReceiptAuthorityUnavailable from None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["SQLAlchemyMonitoringProbeReceiptStore"]
