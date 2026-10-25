"""SQL authority for explicit HOST-to-worker associations."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from secrets import compare_digest
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ...application.host_associations import HostAssociationStore
from ...domain.host_associations import (
    HostAssociationConflict,
    HostAssociationIdempotencyConflict,
    HostAssociationNotFound,
    HostAssociationPage,
    HostAssociationUnavailable,
    HostInstanceAssociation,
)
from .models import (
    AuditEventRecord,
    HostAssociationOperationRecord,
    HostInstanceAssociationRecord,
    MetricsReporterBindingRecord,
    MonitoringSourceRecord,
)


class SQLAlchemyHostAssociationStore(HostAssociationStore):
    """Persist associations and validate them against current SQL authorities."""

    def __init__(self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]) -> None:
        self._engine_resolver = engine_resolver

    async def list_host_associations(
        self,
        environment_id: str,
        *,
        source_id: str | None = None,
        app_id: str | None = None,
        instance_id: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> HostAssociationPage:
        if (
            type(page) is not int
            or page < 1
            or page > 10_000
            or type(page_size) is not int
            or page_size < 1
            or page_size > 100
        ):
            raise HostAssociationUnavailable
        try:
            factory = await self._session_factory()
            async with factory() as session:
                filters = [
                    HostInstanceAssociationRecord.environment_id == environment_id
                ]
                if source_id is not None:
                    filters.append(HostInstanceAssociationRecord.source_id == source_id)
                if app_id is not None:
                    filters.append(HostInstanceAssociationRecord.app_id == app_id)
                if instance_id is not None:
                    filters.append(
                        HostInstanceAssociationRecord.instance_id == instance_id
                    )
                total = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(HostInstanceAssociationRecord)
                        .where(*filters)
                    )
                    or 0
                )
                host_rows = (
                    await session.scalars(
                        select(HostInstanceAssociationRecord.host_id)
                        .where(*filters)
                        .distinct()
                        .order_by(HostInstanceAssociationRecord.host_id)
                        .limit(201)
                    )
                ).all()
                host_ids_complete = len(host_rows) <= 200
                associated_host_ids = tuple(host_rows[:200])
                statement = (
                    select(HostInstanceAssociationRecord, MetricsReporterBindingRecord)
                    .outerjoin(
                        MetricsReporterBindingRecord,
                        (
                            MetricsReporterBindingRecord.environment_id
                            == HostInstanceAssociationRecord.environment_id
                        )
                        & (
                            MetricsReporterBindingRecord.app_id
                            == HostInstanceAssociationRecord.app_id
                        )
                        & (
                            MetricsReporterBindingRecord.instance_id
                            == HostInstanceAssociationRecord.instance_id
                        ),
                    )
                    .where(*filters)
                )
                rows = (
                    await session.execute(
                        statement.order_by(
                            HostInstanceAssociationRecord.host_id,
                            HostInstanceAssociationRecord.app_id,
                            HostInstanceAssociationRecord.instance_id,
                        )
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                ).all()
            return HostAssociationPage(
                items=tuple(_to_domain(record, binding) for record, binding in rows),
                page=page,
                page_size=page_size,
                total=total,
                associated_host_ids=associated_host_ids,
                host_ids_complete=host_ids_complete,
            )
        except HostAssociationUnavailable:
            raise
        except (SQLAlchemyError, TypeError, ValueError):
            raise HostAssociationUnavailable from None

    async def put_host_association(
        self,
        *,
        source_id: str,
        environment_id: str,
        host_id: str,
        app_id: str,
        instance_id: str,
        expected_revision: str | None,
        request_key: str,
        actor_id: str,
        session_digest: str,
        request_id: str,
        now: datetime,
    ) -> dict[str, object]:
        instant = _aware_utc(now)
        fingerprint = _fingerprint(
            "put",
            {
                "sourceId": source_id,
                "environmentId": environment_id,
                "hostId": host_id,
                "appId": app_id,
                "instanceId": instance_id,
                "expectedRevision": expected_revision,
            },
        )
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                previous = await session.scalar(
                    select(HostAssociationOperationRecord)
                    .where(HostAssociationOperationRecord.request_key == request_key)
                    .with_for_update()
                )
                if previous is not None:
                    return _replay_operation(
                        previous, actor_id, session_digest, fingerprint
                    )
                source = await session.scalar(
                    select(MonitoringSourceRecord)
                    .where(MonitoringSourceRecord.source_id == source_id)
                    .with_for_update()
                )
                if (
                    source is None
                    or source.environment_id != environment_id
                    or not source.enabled
                ):
                    raise HostAssociationNotFound
                binding = await session.scalar(
                    select(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.environment_id == environment_id,
                        MetricsReporterBindingRecord.app_id == app_id,
                        MetricsReporterBindingRecord.instance_id == instance_id,
                        MetricsReporterBindingRecord.revoked_at.is_(None),
                    )
                    .with_for_update()
                )
                if binding is None:
                    raise HostAssociationNotFound
                existing = await session.get(
                    HostInstanceAssociationRecord,
                    (environment_id, app_id, instance_id),
                )
                if existing is None and expected_revision is not None:
                    raise HostAssociationConflict
                if existing is not None and (
                    expected_revision is None
                    or not compare_digest(existing.revision, expected_revision)
                ):
                    raise HostAssociationConflict
                revision = str(uuid4())
                if existing is None:
                    row = HostInstanceAssociationRecord(
                        environment_id=environment_id,
                        app_id=app_id,
                        instance_id=instance_id,
                        source_id=source_id,
                        host_id=host_id,
                        revision=revision,
                        created_at=instant,
                        updated_at=instant,
                    )
                    session.add(row)
                else:
                    existing.source_id = source_id
                    existing.host_id = host_id
                    existing.revision = revision
                    existing.updated_at = instant
                    row = existing
                await session.flush()
                result = _association_body(_to_domain(row, binding))
                self._persist_operation(
                    session,
                    request_key=request_key,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    fingerprint=fingerprint,
                    result=result,
                    instant=instant,
                )
                session.add(
                    AuditEventRecord(
                        event_id=str(uuid4()),
                        request_id=request_id,
                        actor_account_id=actor_id,
                        action="monitoring.host-association.create",
                        outcome="completed",
                        target_kind="host-association",
                        target_id=None,
                        created_at=instant,
                    )
                )
                return result
        except (
            HostAssociationConflict,
            HostAssociationNotFound,
            HostAssociationIdempotencyConflict,
        ):
            raise
        except IntegrityError:
            raise HostAssociationConflict from None
        except (SQLAlchemyError, TypeError, ValueError):
            raise HostAssociationUnavailable from None

    async def delete_host_association(
        self,
        *,
        environment_id: str,
        app_id: str,
        instance_id: str,
        expected_revision: str,
        request_key: str,
        actor_id: str,
        session_digest: str,
        request_id: str,
        now: datetime,
    ) -> dict[str, object] | None:
        instant = _aware_utc(now)
        fingerprint = _fingerprint(
            "delete",
            {
                "environmentId": environment_id,
                "appId": app_id,
                "instanceId": instance_id,
                "expectedRevision": expected_revision,
            },
        )
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                previous = await session.scalar(
                    select(HostAssociationOperationRecord)
                    .where(HostAssociationOperationRecord.request_key == request_key)
                    .with_for_update()
                )
                if previous is not None:
                    return _replay_operation(
                        previous, actor_id, session_digest, fingerprint
                    )
                row = await session.scalar(
                    select(HostInstanceAssociationRecord)
                    .where(
                        HostInstanceAssociationRecord.environment_id == environment_id,
                        HostInstanceAssociationRecord.app_id == app_id,
                        HostInstanceAssociationRecord.instance_id == instance_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    return None
                if not compare_digest(row.revision, expected_revision):
                    raise HostAssociationConflict
                await session.delete(row)
                result: dict[str, object] = {"removed": True}
                self._persist_operation(
                    session,
                    request_key=request_key,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    fingerprint=fingerprint,
                    result=result,
                    instant=instant,
                )
                session.add(
                    AuditEventRecord(
                        event_id=str(uuid4()),
                        request_id=request_id,
                        actor_account_id=actor_id,
                        action="monitoring.host-association.delete",
                        outcome="completed",
                        target_kind="host-association",
                        target_id=None,
                        created_at=instant,
                    )
                )
                return result
        except (
            HostAssociationConflict,
            HostAssociationIdempotencyConflict,
        ):
            raise
        except SQLAlchemyError:
            raise HostAssociationUnavailable from None

    async def read_host_association_operation(
        self, request_key: str, *, actor_id: str, session_digest: str
    ) -> dict[str, object] | None:
        try:
            factory = await self._session_factory()
            async with factory() as session:
                row = await session.get(HostAssociationOperationRecord, request_key)
            if row is None:
                return None
            if row.actor_account_id != actor_id or not compare_digest(
                row.session_hash, session_digest
            ):
                raise HostAssociationIdempotencyConflict
            return dict(row.result)
        except HostAssociationIdempotencyConflict:
            raise
        except SQLAlchemyError:
            raise HostAssociationUnavailable from None

    async def resolve_host_association_replay(
        self,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
        kind: str,
        command: dict[str, object],
    ) -> dict[str, object] | None:
        fingerprint = _fingerprint(kind, command)
        try:
            factory = await self._session_factory()
            async with factory() as session:
                row = await session.get(HostAssociationOperationRecord, request_key)
            if row is None:
                return None
            return _replay_operation(row, actor_id, session_digest, fingerprint)
        except HostAssociationIdempotencyConflict:
            raise
        except SQLAlchemyError:
            raise HostAssociationUnavailable from None

    @staticmethod
    def _persist_operation(
        session,
        *,
        request_key: str,
        actor_id: str,
        session_digest: str,
        fingerprint: str,
        result: dict[str, object],
        instant: datetime,
    ) -> None:
        session.add(
            HostAssociationOperationRecord(
                request_key=request_key,
                operation_id=str(uuid4()),
                actor_account_id=actor_id,
                session_hash=session_digest,
                fingerprint_digest=fingerprint,
                status="completed",
                result=result,
                created_at=instant,
            )
        )

    async def _session_factory(self) -> async_sessionmaker:
        engine = await self._engine_resolver()
        return async_sessionmaker(engine, expire_on_commit=False)


def _to_domain(
    record: HostInstanceAssociationRecord,
    binding: MetricsReporterBindingRecord | None,
) -> HostInstanceAssociation:
    return HostInstanceAssociation(
        source_id=record.source_id,
        environment_id=record.environment_id,
        host_id=record.host_id,
        app_id=record.app_id,
        instance_id=record.instance_id,
        process_id=binding.process_id if binding is not None else "",
        revision=record.revision,
        current_epoch=binding.current_epoch if binding is not None else None,
        last_received_at=(
            _aware_utc(binding.last_received_at)
            if binding is not None and binding.last_received_at is not None
            else None
        ),
        created_at=_aware_utc(record.created_at),
        reporter_active=binding is not None and binding.revoked_at is None,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _fingerprint(kind: str, payload: dict[str, object]) -> str:
    material = json.dumps(
        {"kind": kind, **payload},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return sha256(material).hexdigest()


def _replay_operation(
    row: HostAssociationOperationRecord,
    actor_id: str,
    session_digest: str,
    fingerprint: str,
) -> dict[str, object]:
    if (
        row.actor_account_id != actor_id
        or not compare_digest(row.session_hash, session_digest)
        or not compare_digest(row.fingerprint_digest, fingerprint)
    ):
        raise HostAssociationIdempotencyConflict
    return dict(row.result)


def _association_body(item: HostInstanceAssociation) -> dict[str, object]:
    return {
        "sourceId": item.source_id,
        "environmentId": item.environment_id,
        "hostId": item.host_id,
        "appId": item.app_id,
        "instanceId": item.instance_id,
        "processId": item.process_id,
        "revision": item.revision,
        "provenance": "operator_confirmed",
        "currentEpoch": item.current_epoch,
        "lastReceivedAt": item.last_received_at.isoformat().replace("+00:00", "Z")
        if item.last_received_at
        else None,
        "reporterActive": item.reporter_active,
        "createdAt": item.created_at.isoformat().replace("+00:00", "Z"),
    }


__all__ = ["SQLAlchemyHostAssociationStore"]
