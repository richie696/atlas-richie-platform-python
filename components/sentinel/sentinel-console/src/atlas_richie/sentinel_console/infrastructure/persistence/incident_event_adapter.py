"""SQL Adapter for incident enrollment, durable ACKs, and timeline reads."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from atlas_richie.contracts.incidents.v1 import (
    IncidentEventReceiptV1,
    IncidentEventV1,
    ResourcePressureFact,
    ResponseTimeFact,
)
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.incident_ingest_ports import (
    IncidentEventHistoryPort,
    IncidentIngestError,
    IncidentIngestErrorCode,
    IncidentReporterBinding,
    IncidentReporterDirectory,
)
from ...application.incident_evidence_ports import (
    IncidentEvidenceAuthorityUnavailable,
    IncidentEvidenceNotFound,
    IncidentEvidenceReader,
)
from ...application.incident_timeline_ports import (
    IncidentTimelineInvalidCursor,
    IncidentTimelineReader,
)
from ...application.metrics_ingest_ports import VerifiedMetricsPeer
from ...domain.incidents import (
    IncidentCategory,
    IncidentDetailQuery,
    IncidentEvidence,
    IncidentEvidenceCompleteness,
    IncidentEvidenceFact,
    IncidentFact,
    IncidentFactCode,
    IncidentPage,
    IncidentQuery,
    IncidentSeverity,
    IncidentStatistics,
    IncidentSuggestedView,
    ObservedIncident,
)
from ...domain.instance_observation import ObservationContext
from .models import IncidentEventRecord, MetricsReporterBindingRecord

_INCIDENT_RETENTION = timedelta(days=30)
_INCIDENT_EVENT_EVIDENCE_SOURCE = "runtime-event"


class SQLAlchemyIncidentEventAdapter(
    IncidentReporterDirectory,
    IncidentEventHistoryPort,
    IncidentTimelineReader,
    IncidentEvidenceReader,
):
    """Keep authenticated incident facts and bounded SQL read projections."""

    def __init__(
        self,
        engine_resolver: Callable[[], Awaitable[AsyncEngine]],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine_resolver = engine_resolver
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _sessions(self) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(await self._engine_resolver(), expire_on_commit=False)

    async def resolve_incident_peer(
        self, peer: VerifiedMetricsPeer
    ) -> IncidentReporterBinding | None:
        """Resolve only active TLS enrollment with a current process epoch."""
        try:
            sessions = await self._sessions()
            async with sessions() as session:
                record = await session.scalar(
                    select(MetricsReporterBindingRecord).where(
                        MetricsReporterBindingRecord.certificate_sha256
                        == peer.certificate_sha256,
                        MetricsReporterBindingRecord.revoked_at.is_(None),
                        MetricsReporterBindingRecord.current_epoch.is_not(None),
                    )
                )
        except SQLAlchemyError:
            raise IncidentIngestError(
                IncidentIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None
        return _binding(record) if record is not None else None

    async def accept_incident_event(
        self,
        *,
        binding: IncidentReporterBinding,
        event: IncidentEventV1,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> IncidentEventReceiptV1:
        """Commit event bytes, scope, and receipt before returning the ACK."""
        if hashlib.sha256(body).hexdigest() != body_sha256:
            raise ValueError("incident digest does not match request bytes")
        if not _is_utc(received_at):
            raise ValueError("incident receipt time must be UTC-aware")
        received_at = received_at.astimezone(UTC)
        if str(event.process_epoch) != binding.current_epoch:
            raise IncidentIngestError(IncidentIngestErrorCode.IDENTITY_MISMATCH)

        try:
            sessions = await self._sessions()
            async with sessions.begin() as session:
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
                    raise IncidentIngestError(
                        IncidentIngestErrorCode.IDENTITY_NOT_ENROLLED
                    )
                if _binding(record) != binding:
                    raise IncidentIngestError(IncidentIngestErrorCode.IDENTITY_MISMATCH)

                await session.execute(
                    delete(IncidentEventRecord).where(
                        IncidentEventRecord.expires_at <= received_at
                    )
                )
                prior = await session.scalar(
                    select(IncidentEventRecord).where(
                        IncidentEventRecord.certificate_principal
                        == binding.certificate_principal,
                        IncidentEventRecord.event_id == str(event.event_id),
                    )
                )
                if prior is not None:
                    if prior.body_sha256 != body_sha256:
                        raise IncidentIngestError(
                            IncidentIngestErrorCode.IDEMPOTENCY_CONFLICT
                        )
                    receipt = _receipt(prior)
                else:
                    incident_id = hashlib.sha256(
                        f"{binding.certificate_principal}\0{event.event_id}".encode()
                    ).hexdigest()
                    fact_payload, category = _fact_payload(event)
                    row = IncidentEventRecord(
                        incident_id=incident_id,
                        certificate_principal=binding.certificate_principal,
                        event_id=str(event.event_id),
                        process_epoch=str(event.process_epoch),
                        environment_id=binding.environment_id,
                        app_id=binding.app_id,
                        instance_id=binding.instance_id,
                        process_id=binding.process_id,
                        occurred_at=event.occurred_at.astimezone(UTC),
                        received_at=received_at,
                        severity=event.severity.value,
                        category=category.value,
                        fact_payload=fact_payload,
                        body_sha256=body_sha256,
                        body=body,
                        expires_at=received_at + _INCIDENT_RETENTION,
                    )
                    session.add(row)
                    await session.flush()
                    receipt = IncidentEventReceiptV1(
                        event_id=event.event_id,
                        body_sha256=body_sha256,
                        received_at=received_at,
                    )
            return receipt
        except IncidentIngestError:
            raise
        except IntegrityError:
            return await self._resolve_duplicate(
                binding=binding, event=event, body_sha256=body_sha256
            )
        except SQLAlchemyError:
            raise IncidentIngestError(
                IncidentIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None

    async def _resolve_duplicate(
        self,
        *,
        binding: IncidentReporterBinding,
        event: IncidentEventV1,
        body_sha256: str,
    ) -> IncidentEventReceiptV1:
        """Resolve a concurrent same-key insert without leaking SQL diagnostics."""
        try:
            sessions = await self._sessions()
            async with sessions() as session:
                row = await session.scalar(
                    select(IncidentEventRecord).where(
                        IncidentEventRecord.certificate_principal
                        == binding.certificate_principal,
                        IncidentEventRecord.event_id == str(event.event_id),
                    )
                )
        except SQLAlchemyError:
            raise IncidentIngestError(
                IncidentIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None
        if row is None:
            raise IncidentIngestError(
                IncidentIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None
        if row.body_sha256 != body_sha256:
            raise IncidentIngestError(IncidentIngestErrorCode.IDEMPOTENCY_CONFLICT)
        return _receipt(row)

    async def expire_incident_history(self, now: datetime) -> int:
        """Delete physically expired incident rows for a maintenance runner.

        Timeline reads enforce logical expiry independently, so a delayed
        maintenance invocation cannot expose expired events. This method is
        safe to retry and returns only the committed deletion count.
        """
        if not _is_utc(now):
            raise ValueError("incident expiration time must be UTC-aware")
        try:
            sessions = await self._sessions()
            async with sessions.begin() as session:
                result = await session.execute(
                    delete(IncidentEventRecord).where(
                        IncidentEventRecord.expires_at <= now.astimezone(UTC)
                    )
                )
            return result.rowcount or 0
        except SQLAlchemyError:
            raise IncidentIngestError(
                IncidentIngestErrorCode.STORAGE_UNAVAILABLE
            ) from None

    async def read_incident_timeline(self, query: IncidentQuery) -> IncidentPage:
        """Read a durable bounded page with stable query-scoped cursors."""
        as_of = self._clock()
        if not _is_utc(as_of):
            raise RuntimeError("incident timeline clock must return UTC")
        as_of = as_of.astimezone(UTC)
        try:
            sessions = await self._sessions()
            async with sessions() as session:
                base = _scope_filters(query, as_of)
                total = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(IncidentEventRecord)
                        .where(*base)
                    )
                    or 0
                )
                critical, warning, info, affected = await _statistics(session, base)
                filters = list(base)
                if query.severity is not None:
                    filters.append(IncidentEventRecord.severity == query.severity.value)
                if query.category is not None:
                    filters.append(IncidentEventRecord.category == query.category.value)
                filtered_total = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(IncidentEventRecord)
                        .where(*filters)
                    )
                    or 0
                )
                if query.cursor is not None:
                    try:
                        cursor_at, cursor_id = _decode_cursor(query)
                    except ValueError:
                        raise IncidentTimelineInvalidCursor(
                            "incident cursor is invalid"
                        ) from None
                    filters.append(
                        or_(
                            IncidentEventRecord.occurred_at < cursor_at,
                            and_(
                                IncidentEventRecord.occurred_at == cursor_at,
                                IncidentEventRecord.incident_id < cursor_id,
                            ),
                        )
                    )
                rows = (
                    await session.scalars(
                        select(IncidentEventRecord)
                        .where(*filters)
                        .order_by(
                            IncidentEventRecord.occurred_at.desc(),
                            IncidentEventRecord.incident_id.desc(),
                        )
                        .limit(query.page_size + 1)
                    )
                ).all()
        except SQLAlchemyError:
            from ...application.incident_timeline_ports import (
                IncidentTimelineAuthorityUnavailable,
            )

            raise IncidentTimelineAuthorityUnavailable(
                "incident timeline authority unavailable"
            ) from None

        has_more = len(rows) > query.page_size
        page_rows = rows[: query.page_size]
        items = tuple(_observed(row) for row in page_rows)
        next_cursor = (
            _encode_cursor(query, page_rows[-1]) if has_more and page_rows else None
        )
        return IncidentPage(
            query=query,
            as_of=as_of,
            statistics=IncidentStatistics(
                total=total,
                critical=critical,
                warning=warning,
                info=info,
                rule_changes=0,
                affected_applications=affected,
            ),
            items=items,
            filtered_total=filtered_total,
            next_cursor=next_cursor,
        )

    async def read_incident_evidence(
        self, query: IncidentDetailQuery
    ) -> IncidentEvidence:
        """Return only the selected, persisted event fact for its exact query.

        The current event table has no independent related-fact or rule-link
        authority. The event's own structured fact is therefore returned as
        partial evidence, without deriving rule identity or causality.
        """
        as_of = self._clock()
        if not _is_utc(as_of):
            raise RuntimeError("incident evidence clock must return UTC")
        as_of = as_of.astimezone(UTC)
        try:
            sessions = await self._sessions()
            async with sessions() as session:
                record = await session.scalar(
                    select(IncidentEventRecord).where(
                        *_detail_scope_filters(query, as_of)
                    )
                )
        except SQLAlchemyError:
            raise IncidentEvidenceAuthorityUnavailable(
                "incident evidence authority unavailable"
            ) from None
        if record is None:
            raise IncidentEvidenceNotFound("incident evidence not found")

        event = _observed(record)
        suggested_views = (
            (IncidentSuggestedView.INSTANCE, IncidentSuggestedView.METRICS)
            if event.instance_id is not None
            else (IncidentSuggestedView.METRICS,)
        )
        return IncidentEvidence(
            query=query,
            as_of=as_of,
            event=event,
            facts=(
                IncidentEvidenceFact(
                    id=event.id,
                    source=_INCIDENT_EVENT_EVIDENCE_SOURCE,
                    at=event.occurred_at,
                    fact=event.caption,
                ),
            ),
            completeness=IncidentEvidenceCompleteness.PARTIAL,
            suggested_views=suggested_views,
            related_rule=None,
        )


def _binding(record: MetricsReporterBindingRecord) -> IncidentReporterBinding:
    return IncidentReporterBinding(
        certificate_principal=record.certificate_principal,
        reporter_id=record.reporter_id,
        environment_id=record.environment_id,
        app_id=record.app_id,
        instance_id=record.instance_id,
        process_id=record.process_id,
        current_epoch=record.current_epoch or "",
    )


def _receipt(record: IncidentEventRecord) -> IncidentEventReceiptV1:
    return IncidentEventReceiptV1(
        event_id=UUID(record.event_id),
        body_sha256=record.body_sha256,
        received_at=_as_utc(record.received_at),
    )


def _fact_payload(event: IncidentEventV1) -> tuple[dict[str, object], IncidentCategory]:
    if isinstance(event.fact, ResourcePressureFact):
        return (
            {
                "code": IncidentFactCode.RESOURCE_PRESSURE.value,
                "metric": event.fact.metric.value,
                "value": event.fact.value,
                "threshold": event.fact.threshold,
            },
            IncidentCategory.RESOURCE,
        )
    if isinstance(event.fact, ResponseTimeFact):
        return (
            {
                "code": IncidentFactCode.RESPONSE_TIME.value,
                "valueMs": event.fact.p95_ms,
                "thresholdMs": event.fact.threshold_ms,
            },
            IncidentCategory.RESPONSE_TIME,
        )
    raise TypeError("unsupported incident fact")


def _observed(record: IncidentEventRecord) -> ObservedIncident:
    payload = record.fact_payload
    code = IncidentFactCode(payload["code"])
    if code is IncidentFactCode.RESOURCE_PRESSURE:
        fact = IncidentFact(
            code=code,
            metric=str(payload["metric"]),
            value=float(payload["value"]),
            threshold=float(payload["threshold"]),
        )
    elif code is IncidentFactCode.RESPONSE_TIME:
        fact = IncidentFact(
            code=code,
            value_ms=float(payload["valueMs"]),
            threshold_ms=float(payload["thresholdMs"]),
        )
    else:
        raise ValueError("stored incident fact is unsupported")
    return ObservedIncident(
        id=record.incident_id,
        environment_id=record.environment_id,
        app_id=record.app_id,
        instance_id=record.instance_id,
        process_epoch=record.process_epoch,
        occurred_at=_as_utc(record.occurred_at),
        received_at=_as_utc(record.received_at),
        severity=IncidentSeverity(record.severity),
        category=IncidentCategory(record.category),
        source_event_id=record.event_id,
        publication_id=None,
        caption=fact,
    )


def _scope_filters(query: IncidentQuery, as_of: datetime) -> list[object]:
    return _event_scope_filters(query.context, as_of)


def _event_scope_filters(
    context: ObservationContext, as_of: datetime
) -> list[object]:
    """Return the shared environment, scope, window, and retention filters."""
    filters: list[object] = [
        IncidentEventRecord.environment_id == context.environment_id,
        IncidentEventRecord.occurred_at >= context.window.starts_at,
        IncidentEventRecord.occurred_at < context.window.ends_at,
        IncidentEventRecord.expires_at > as_of,
    ]
    if context.app_id is not None:
        filters.append(IncidentEventRecord.app_id == context.app_id)
    if context.instance_id is not None:
        filters.append(IncidentEventRecord.instance_id == context.instance_id)
    return filters


def _detail_scope_filters(
    query: IncidentDetailQuery, as_of: datetime
) -> list[object]:
    """Bind the selected ID to every active scope and visibility filter."""
    context = query.context
    filters = _event_scope_filters(context, as_of)
    filters.append(IncidentEventRecord.incident_id == query.event_id)
    if query.severity is not None:
        filters.append(IncidentEventRecord.severity == query.severity.value)
    if query.category is not None:
        filters.append(IncidentEventRecord.category == query.category.value)
    return filters


async def _statistics(
    session: AsyncSession, filters: list[object]
) -> tuple[int, int, int, int]:
    values = (
        await session.execute(
            select(
                func.sum(
                    case((IncidentEventRecord.severity == "critical", 1), else_=0)
                ),
                func.sum(case((IncidentEventRecord.severity == "warning", 1), else_=0)),
                func.sum(case((IncidentEventRecord.severity == "info", 1), else_=0)),
                func.count(func.distinct(IncidentEventRecord.app_id)),
            ).where(*filters)
        )
    ).one()
    return (
        int(values[0] or 0),
        int(values[1] or 0),
        int(values[2] or 0),
        int(values[3] or 0),
    )


def _query_digest(query: IncidentQuery) -> str:
    context = query.context
    canonical = json.dumps(
        {
            "environment": context.environment_id,
            "application": context.app_id,
            "instance": context.instance_id,
            "windowFrom": context.window.starts_at.astimezone(UTC).isoformat(),
            "windowTo": context.window.ends_at.astimezone(UTC).isoformat(),
            "severity": query.severity.value if query.severity else None,
            "category": query.category.value if query.category else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _encode_cursor(query: IncidentQuery, record: IncidentEventRecord) -> str:
    payload = json.dumps(
        {
            "query": _query_digest(query),
            "at": _as_utc(record.occurred_at).isoformat(timespec="microseconds"),
            "id": record.incident_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(query: IncidentQuery) -> tuple[datetime, str]:
    if query.cursor is None:
        raise ValueError("incident cursor is missing")
    try:
        encoded = query.cursor.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if (
            type(payload) is not dict
            or set(payload) != {"query", "at", "id"}
            or payload["query"] != _query_digest(query)
            or not isinstance(payload["id"], str)
        ):
            raise ValueError
        instant = datetime.fromisoformat(payload["at"])
        if not _is_utc(instant):
            raise ValueError
        return instant.astimezone(UTC), payload["id"]
    except (ValueError, TypeError, KeyError, UnicodeEncodeError, json.JSONDecodeError):
        raise ValueError("incident cursor is invalid") from None


def _is_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["SQLAlchemyIncidentEventAdapter"]
