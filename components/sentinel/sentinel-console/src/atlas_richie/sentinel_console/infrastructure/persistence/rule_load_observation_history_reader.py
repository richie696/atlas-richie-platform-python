"""SQL adapter for immutable rule-load events from older process epochs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_load_observation_history_ports import (
    RuleLoadObservationHistoryReader,
)
from ...domain.rule_catalog import RuleCatalogCoverage
from ...domain.rule_load_observation_history import (
    HistoricalProcessEpochStatus,
    RuleLoadObservationHistoryItem,
    RuleLoadObservationHistoryPage,
    RuleLoadObservationHistoryQuery,
)
from ...domain.utc_time import current_utc_millisecond_instant
from .models import (
    MetricsReporterBindingRecord,
    RuleBindingRecord,
    RuleLoadObservationInboxRecord,
)
from .rule_load_observation_reader import _item_from_row, _utc


class SqlAlchemyRuleLoadObservationHistoryReader(RuleLoadObservationHistoryReader):
    """Read only durable old-epoch events; never merge them into current counts."""

    def __init__(self, engine: AsyncEngine, *, clock=current_utc_millisecond_instant) -> None:
        self._engine = engine
        self._clock = clock

    async def read_rule_load_observation_history(
        self, query: RuleLoadObservationHistoryQuery
    ) -> RuleLoadObservationHistoryPage:
        if not isinstance(query, RuleLoadObservationHistoryQuery):
            raise TypeError("rule-load history query is invalid")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("query clock must return an aware instant")
        binding = RuleBindingRecord.__table__
        reporter = MetricsReporterBindingRecord.__table__
        inbox = RuleLoadObservationInboxRecord.__table__
        binding_scope = and_(
            binding.c.binding_id == query.binding_id,
            binding.c.environment_id == query.environment_id,
            binding.c.app_id == query.app_id,
        )
        old_epoch = or_(
            reporter.c.revoked_at.is_not(None),
            reporter.c.current_epoch.is_(None),
            inbox.c.process_epoch != reporter.c.current_epoch,
        )
        source = (
            binding.join(inbox, inbox.c.binding_id == binding.c.binding_id)
            .join(
                reporter,
                and_(
                    reporter.c.certificate_principal == inbox.c.certificate_principal,
                    reporter.c.environment_id == inbox.c.environment_id,
                    reporter.c.app_id == inbox.c.app_id,
                ),
            )
        )
        scope = [binding_scope, old_epoch]
        if query.instance_id is not None:
            scope.append(inbox.c.instance_id == query.instance_id)
        try:
            async with self._engine.connect() as connection:
                binding_exists = bool(
                    await connection.scalar(
                        select(func.count()).select_from(binding).where(binding_scope)
                    )
                )
                if not binding_exists:
                    return RuleLoadObservationHistoryPage(
                        query=query,
                        as_of=_utc(now),
                        coverage=RuleCatalogCoverage.PARTIAL,
                        total=None,
                        has_more=False,
                        items=(),
                    )
                total = int(
                    await connection.scalar(
                        select(func.count()).select_from(source).where(*scope)
                    )
                    or 0
                )
                rows = (
                    await connection.execute(
                        select(
                            inbox.c.observation_id,
                            inbox.c.instance_id,
                            inbox.c.process_id,
                            inbox.c.process_epoch,
                            inbox.c.profile_id,
                            inbox.c.event_kind,
                            inbox.c.active_snapshot,
                            inbox.c.attempt,
                            inbox.c.observed_at,
                            inbox.c.received_at,
                            inbox.c.binding_id,
                            reporter.c.current_epoch,
                            reporter.c.revoked_at,
                        )
                        .select_from(source)
                        .where(*scope)
                        .order_by(inbox.c.received_at.desc(), inbox.c.observation_id.desc())
                        .offset((query.page - 1) * query.page_size)
                        .limit(query.page_size + 1)
                    )
                ).mappings().all()
        except SQLAlchemyError:
            raise RuntimeError("rule-load history query is unavailable") from None

        has_more = len(rows) > query.page_size
        items = tuple(
            _history_item(row)
            for row in rows[: query.page_size]
        )
        return RuleLoadObservationHistoryPage(
            query=query,
            as_of=_utc(now),
            coverage=RuleCatalogCoverage.COMPLETE,
            total=total,
            has_more=has_more,
            items=items,
        )


def _history_item(row: Mapping[str, object]) -> RuleLoadObservationHistoryItem:
    if row["revoked_at"] is not None:
        epoch_status = HistoricalProcessEpochStatus.REVOKED
    elif row["current_epoch"] is None:
        epoch_status = HistoricalProcessEpochStatus.NO_CURRENT_EPOCH
    else:
        epoch_status = HistoricalProcessEpochStatus.SUPERSEDED
    observation = _item_from_row(
        row,
        # Historical rows are retained facts, not freshness claims. This cutoff
        # only satisfies the shared safe DTO mapper; the history UI labels epoch
        # status separately and does not reuse current target totals.
        cutoff=datetime.min.replace(tzinfo=UTC),
    )
    return RuleLoadObservationHistoryItem(
        observation_id=row["observation_id"],
        epoch_status=epoch_status,
        observation=observation,
    )


__all__ = ["SqlAlchemyRuleLoadObservationHistoryReader"]
