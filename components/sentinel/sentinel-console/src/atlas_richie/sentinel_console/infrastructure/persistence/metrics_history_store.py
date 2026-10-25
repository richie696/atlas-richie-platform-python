"""SQLAlchemy Adapter for authenticated, idempotent Metrics V2 history writes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MetricsReceipt,
    MetricsSnapshot,
    MetricsV2ProtocolError,
    decode_metrics_snapshot,
)
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.metrics_ingest_ports import (
    MetricsHistoryPort,
    MetricsIngestError,
    MetricsIngestErrorCode,
    MetricsReporterBinding,
    MetricsReporterDirectory,
)
from ...domain.metrics_rollups import (
    MetricContributionQuality,
    MetricIntervalContribution,
    build_metric_interval_contributions,
)
from .models import (
    MetricsMinuteRollupRecord,
    MetricsReporterBindingRecord,
    MetricsReporterEpochRecord,
    MetricsSnapshotRecord,
)

_RAW_RETENTION = timedelta(hours=24)
_ROLLUP_RETENTION = timedelta(days=30)


class SQLAlchemyMetricsHistoryAdapter(MetricsReporterDirectory, MetricsHistoryPort):
    """Persist exact request bytes and receipt in one selected Console database."""

    def __init__(self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]) -> None:
        """Resolve the selected Console engine only when durable work is needed.

        A first-run Console may be serving setup before a runtime database is
        configured. Accepting the existing runtime provider's bound
        ``require_engine`` method keeps this Adapter on the selected database
        without capturing a setup-time or vendor-specific engine.
        """
        self._engine_resolver = engine_resolver

    async def _session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Create sessions against the currently selected runtime engine."""
        engine = await self._engine_resolver()
        return async_sessionmaker(engine, expire_on_commit=False)

    async def resolve_certificate(
        self, certificate_sha256: str
    ) -> MetricsReporterBinding | None:
        """Resolve a verified peer fingerprint without exposing revoked bindings."""
        try:
            sessions = await self._session_factory()
            async with sessions() as session:
                record = await session.scalar(
                    select(MetricsReporterBindingRecord).where(
                        MetricsReporterBindingRecord.certificate_sha256
                        == certificate_sha256,
                        MetricsReporterBindingRecord.revoked_at.is_(None),
                    )
                )
        except SQLAlchemyError:
            raise MetricsIngestError(
                MetricsIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None
        return _binding_from_record(record) if record is not None else None

    async def accept_snapshot(
        self,
        *,
        binding: MetricsReporterBinding,
        snapshot: MetricsSnapshot,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> MetricsReceipt:
        """Commit receipt, raw body, and sequence state before returning an ACK."""
        if hashlib.sha256(body).hexdigest() != body_sha256:
            raise ValueError("snapshot body digest does not match its bytes")
        if (
            snapshot.reporter_id != binding.reporter_id
            or received_at.tzinfo is None
            or received_at.utcoffset() != UTC.utcoffset(received_at)
        ):
            raise MetricsIngestError(MetricsIngestErrorCode.IDENTITY_MISMATCH)
        received_at = received_at.astimezone(UTC)
        try:
            sessions = await self._session_factory()
            async with sessions.begin() as session:
                # The no-op update obtains a write lock on SQLite too; server
                # databases additionally honor the following row-level lock.
                await session.execute(
                    update(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.certificate_principal
                        == binding.certificate_principal
                    )
                    .values(last_sequence=MetricsReporterBindingRecord.last_sequence)
                )
                record = await session.scalar(
                    select(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.certificate_principal
                        == binding.certificate_principal
                    )
                    .with_for_update()
                )
                if record is None or record.revoked_at is not None:
                    raise MetricsIngestError(
                        MetricsIngestErrorCode.IDENTITY_NOT_ENROLLED
                    )
                if not _matches_binding(record, binding):
                    raise MetricsIngestError(MetricsIngestErrorCode.IDENTITY_MISMATCH)

                prior_receipt = await session.scalar(
                    select(MetricsSnapshotRecord).where(
                        MetricsSnapshotRecord.certificate_principal
                        == binding.certificate_principal,
                        MetricsSnapshotRecord.startup_epoch
                        == str(snapshot.startup_epoch),
                        MetricsSnapshotRecord.sequence == snapshot.sequence,
                    )
                )
                if prior_receipt is not None:
                    if prior_receipt.body_sha256 != body_sha256:
                        raise MetricsIngestError(
                            MetricsIngestErrorCode.IDEMPOTENCY_CONFLICT
                        )
                    return _receipt_from_record(prior_receipt, binding.reporter_id)

                epoch = str(snapshot.startup_epoch)
                previous_snapshot_record = None
                if record.current_epoch == epoch:
                    if snapshot.sequence <= record.last_sequence:
                        raise MetricsIngestError(MetricsIngestErrorCode.STALE_SEQUENCE)
                    if (
                        record.last_elapsed_ns is not None
                        and snapshot.capture_elapsed_ns <= int(record.last_elapsed_ns)
                    ):
                        raise MetricsIngestError(
                            MetricsIngestErrorCode.ELAPSED_TIME_REGRESSION
                        )
                    epoch_record = await session.scalar(
                        select(MetricsReporterEpochRecord)
                        .where(
                            MetricsReporterEpochRecord.certificate_principal
                            == binding.certificate_principal,
                            MetricsReporterEpochRecord.startup_epoch == epoch,
                        )
                        .with_for_update()
                    )
                    if epoch_record is None:
                        raise MetricsIngestError(
                            MetricsIngestErrorCode.STORAGE_UNAVAILABLE
                        )
                    epoch_record.last_sequence = snapshot.sequence
                    epoch_record.last_elapsed_ns = str(snapshot.capture_elapsed_ns)
                    previous_snapshot_record = await session.scalar(
                        select(MetricsSnapshotRecord)
                        .where(
                            MetricsSnapshotRecord.certificate_principal
                            == binding.certificate_principal,
                            MetricsSnapshotRecord.startup_epoch == epoch,
                            MetricsSnapshotRecord.sequence < snapshot.sequence,
                        )
                        .order_by(MetricsSnapshotRecord.sequence.desc())
                        .limit(1)
                    )
                else:
                    used_epoch = await session.scalar(
                        select(MetricsReporterEpochRecord.startup_epoch).where(
                            MetricsReporterEpochRecord.certificate_principal
                            == binding.certificate_principal,
                            MetricsReporterEpochRecord.startup_epoch == epoch,
                        )
                    )
                    if used_epoch is not None or snapshot.sequence != 1:
                        raise MetricsIngestError(MetricsIngestErrorCode.INVALID_EPOCH)
                    session.add(
                        MetricsReporterEpochRecord(
                            certificate_principal=binding.certificate_principal,
                            startup_epoch=epoch,
                            first_sequence=snapshot.sequence,
                            first_elapsed_ns=str(snapshot.capture_elapsed_ns),
                            last_sequence=snapshot.sequence,
                            last_elapsed_ns=str(snapshot.capture_elapsed_ns),
                        )
                    )

                session.add(
                    MetricsSnapshotRecord(
                        certificate_principal=binding.certificate_principal,
                        startup_epoch=epoch,
                        sequence=snapshot.sequence,
                        body_sha256=body_sha256,
                        body=body,
                        received_at=received_at,
                    )
                )
                try:
                    previous_snapshot = (
                        decode_metrics_snapshot(previous_snapshot_record.body)
                        if previous_snapshot_record is not None
                        else None
                    )
                except MetricsV2ProtocolError:
                    raise MetricsIngestError(
                        MetricsIngestErrorCode.STORAGE_UNAVAILABLE
                    ) from None
                contributions = build_metric_interval_contributions(
                    environment_id=binding.environment_id,
                    app_id=binding.app_id,
                    instance_id=binding.instance_id,
                    previous=previous_snapshot,
                    previous_received_at=(
                        _normalize_utc(previous_snapshot_record.received_at)
                        if previous_snapshot_record is not None
                        else None
                    ),
                    current=snapshot,
                    received_at=received_at,
                )
                for contribution in contributions:
                    await _merge_rollup_contribution(session, contribution)
                record.current_epoch = epoch
                record.last_sequence = snapshot.sequence
                record.last_elapsed_ns = str(snapshot.capture_elapsed_ns)
                record.last_received_at = received_at
                receipt = MetricsReceipt(
                    reporter_id=binding.reporter_id,
                    startup_epoch=snapshot.startup_epoch,
                    sequence=snapshot.sequence,
                    body_sha256=body_sha256,
                    received_at=received_at,
                )
            # The context manager has committed successfully. Only now is the
            # durable receipt allowed to escape to the HTTP response adapter.
            return receipt
        except MetricsIngestError:
            raise
        except IntegrityError:
            duplicate = await self._read_duplicate(
                binding=binding,
                snapshot=snapshot,
                body_sha256=body_sha256,
            )
            if duplicate is not None:
                return duplicate
            raise MetricsIngestError(MetricsIngestErrorCode.STALE_SEQUENCE) from None
        except SQLAlchemyError:
            raise MetricsIngestError(
                MetricsIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None

    async def expire_history(self, now: datetime) -> tuple[int, int]:
        """Idempotently delete expired raw snapshots and minute rollups."""
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("history expiration time must be aware UTC")
        now = now.astimezone(UTC)
        raw_cutoff = now - _RAW_RETENTION
        rollup_cutoff = now - _ROLLUP_RETENTION
        try:
            sessions = await self._session_factory()
            async with sessions.begin() as session:
                raw_result = await session.execute(
                    delete(MetricsSnapshotRecord).where(
                        MetricsSnapshotRecord.received_at < raw_cutoff
                    )
                )
                rollup_result = await session.execute(
                    delete(MetricsMinuteRollupRecord).where(
                        MetricsMinuteRollupRecord.bucket_started_at < rollup_cutoff,
                        MetricsMinuteRollupRecord.expires_at <= now,
                    )
                )
            return raw_result.rowcount or 0, rollup_result.rowcount or 0
        except SQLAlchemyError:
            raise MetricsIngestError(
                MetricsIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None

    async def _read_duplicate(
        self,
        *,
        binding: MetricsReporterBinding,
        snapshot: MetricsSnapshot,
        body_sha256: str,
    ) -> MetricsReceipt | None:
        try:
            sessions = await self._session_factory()
            async with sessions() as session:
                record = await session.scalar(
                    select(MetricsSnapshotRecord).where(
                        MetricsSnapshotRecord.certificate_principal
                        == binding.certificate_principal,
                        MetricsSnapshotRecord.startup_epoch
                        == str(snapshot.startup_epoch),
                        MetricsSnapshotRecord.sequence == snapshot.sequence,
                    )
                )
        except SQLAlchemyError:
            raise MetricsIngestError(
                MetricsIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None
        if record is None:
            return None
        if record.body_sha256 != body_sha256:
            raise MetricsIngestError(MetricsIngestErrorCode.IDEMPOTENCY_CONFLICT)
        return _receipt_from_record(record, binding.reporter_id)


def _binding_from_record(
    record: MetricsReporterBindingRecord,
) -> MetricsReporterBinding:
    return MetricsReporterBinding(
        certificate_principal=record.certificate_principal,
        certificate_sha256=record.certificate_sha256,
        reporter_id=record.reporter_id,
        environment_id=record.environment_id,
        app_id=record.app_id,
        instance_id=record.instance_id,
        process_id=record.process_id,
    )


def _matches_binding(
    record: MetricsReporterBindingRecord, binding: MetricsReporterBinding
) -> bool:
    return (
        record.certificate_sha256 == binding.certificate_sha256
        and record.reporter_id == binding.reporter_id
        and record.environment_id == binding.environment_id
        and record.app_id == binding.app_id
        and record.instance_id == binding.instance_id
        and record.process_id == binding.process_id
    )


def _receipt_from_record(
    record: MetricsSnapshotRecord, reporter_id: str
) -> MetricsReceipt:
    received_at = record.received_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    return MetricsReceipt(
        reporter_id=reporter_id,
        startup_epoch=UUID(record.startup_epoch),
        sequence=record.sequence,
        body_sha256=record.body_sha256,
        received_at=received_at.astimezone(UTC),
    )


__all__ = ["SQLAlchemyMetricsHistoryAdapter"]


async def _merge_rollup_contribution(
    session: AsyncSession, contribution: MetricIntervalContribution
) -> None:
    """Merge a reporter's interval into its one-minute row in the ingest txn."""
    rollup_id = _rollup_id(contribution)
    row = await session.get(MetricsMinuteRollupRecord, rollup_id)
    payload = _merge_rollup_payload(
        row.payload if row is not None else None,
        contribution,
    )
    if row is None:
        session.add(
            MetricsMinuteRollupRecord(
                rollup_id=rollup_id,
                environment_id=contribution.environment_id,
                app_id=contribution.app_id,
                instance_id=contribution.instance_id,
                reporter_id=contribution.reporter_id,
                startup_epoch=contribution.startup_epoch,
                metric_name=contribution.metric,
                resource_id=contribution.resource,
                bucket_started_at=contribution.bucket_started_at,
                payload=payload,
                expires_at=contribution.bucket_started_at + _ROLLUP_RETENTION,
            )
        )
        return
    row.payload = payload
    row.expires_at = contribution.bucket_started_at + _ROLLUP_RETENTION


def _merge_rollup_payload(
    prior: dict[str, object] | None,
    contribution: MetricIntervalContribution,
) -> dict[str, object]:
    """Return a fresh JSON payload, summing interval facts or replacing gauges."""
    base = dict(prior or {})
    if prior is not None and not _is_valid_rollup_payload(prior, contribution.metric):
        raise MetricsIngestError(MetricsIngestErrorCode.STORAGE_UNAVAILABLE)

    if contribution.metric in {"http_qps", "resource_entry_rate", "tps"}:
        delta = contribution.delta or 0
        elapsed_ns = contribution.elapsed_ns or 0
        base["delta"] = str(int(base.get("delta", "0")) + delta)
        base["elapsed_ns"] = str(int(base.get("elapsed_ns", "0")) + elapsed_ns)
        base["quality"] = MetricContributionQuality.AVAILABLE.value
    elif contribution.metric == "blocked_ratio":
        numerator = contribution.numerator or 0
        denominator = contribution.denominator or 0
        base["numerator"] = int(base.get("numerator", 0)) + numerator
        base["denominator"] = int(base.get("denominator", 0)) + denominator
        base["quality"] = (
            MetricContributionQuality.AVAILABLE.value
            if int(base["denominator"]) > 0
            else MetricContributionQuality.UNAVAILABLE.value
        )
    elif contribution.metric == "rt_p95":
        counts = contribution.histogram_buckets or ()
        old_counts = base.get("histogram_buckets")
        if old_counts is not None and (
            not isinstance(old_counts, list) or len(old_counts) != len(counts)
        ):
            raise MetricsIngestError(MetricsIngestErrorCode.STORAGE_UNAVAILABLE)
        combined_counts = [
            int(old or 0) + current
            for old, current in zip(
                old_counts or [0] * len(counts), counts, strict=True
            )
        ]
        sample_count = int(base.get("histogram_sample_count", 0)) + (
            contribution.histogram_sample_count or 0
        )
        base["histogram_buckets"] = combined_counts
        base["histogram_sample_count"] = sample_count
        base["quality"] = _histogram_quality(combined_counts, sample_count).value
    else:
        base["gauge_value"] = contribution.gauge_value
        base["quality"] = contribution.quality.value
        base["received_at"] = contribution.received_at.isoformat()

    # Keep serialization deterministic and reject non-JSON numeric surprises.
    json.dumps(base, allow_nan=False, sort_keys=True)
    return base


def _histogram_quality(
    bucket_counts: list[int], sample_count: int
) -> MetricContributionQuality:
    if sample_count == 0:
        return MetricContributionQuality.NO_SAMPLES
    rank = (sample_count * 95 + 99) // 100
    cumulative = 0
    for count in bucket_counts[:-1]:
        cumulative += count
        if cumulative >= rank:
            return MetricContributionQuality.AVAILABLE
    return MetricContributionQuality.OVERFLOW


def _is_valid_rollup_payload(payload: dict[str, object], metric: str) -> bool:
    try:
        if metric in {"http_qps", "resource_entry_rate", "tps"}:
            return (
                int(payload.get("delta", "0")) >= 0
                and int(payload.get("elapsed_ns", "0")) > 0
            )
        if metric == "blocked_ratio":
            return (
                int(payload.get("numerator", 0)) >= 0
                and int(payload.get("denominator", 0)) >= 0
            )
        if metric == "rt_p95":
            buckets = payload.get("histogram_buckets")
            return (
                isinstance(buckets, list)
                and len(buckets) == len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1
                and all(type(item) is int and item >= 0 for item in buckets)
                and int(payload.get("histogram_sample_count", -1)) == sum(buckets)
            )
        if metric in {"cpu_ratio", "memory_bytes", "memory_ratio"}:
            received_at = payload.get("received_at")
            return isinstance(received_at, str) and (
                payload.get("quality")
                in {
                    MetricContributionQuality.AVAILABLE.value,
                    MetricContributionQuality.UNAVAILABLE.value,
                }
            )
    except (TypeError, ValueError, OverflowError):
        return False
    return False


def _rollup_id(contribution: MetricIntervalContribution) -> str:
    resource_key = contribution.resource or ""
    identity = json.dumps(
        [
            contribution.reporter_id,
            contribution.startup_epoch,
            contribution.metric,
            resource_key,
            contribution.bucket_started_at.isoformat(),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _normalize_utc(value: datetime) -> datetime:
    """Restore UTC on dialects such as SQLite that drop timezone metadata."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
