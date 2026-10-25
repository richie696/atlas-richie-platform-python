"""SQL read adapter for the additive Console API 0.9 binding-state view."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_binding_state_ports import RuleBindingStateReader
from ...domain.rule_bindings import RuleKind
from ...domain.rule_catalog import (
    RuleBindingObservedState,
    RuleBindingObservedStateItem,
    RuleBindingStatesPage,
    RuleBindingStatesQuery,
    RuleCatalogCoverage,
    RuleCatalogFreshness,
)
from ...domain.utc_time import current_utc_millisecond_instant
from .models import (
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleCatalogSnapshotRecord,
    RulePublicationTargetRecord,
)
from .rule_binding_directory_reader import binding_from_authority_row

_ERROR_STATE = {
    "target_missing": RuleBindingObservedState.TARGET_MISSING,
    "content_invalid": RuleBindingObservedState.CONTENT_INVALID,
    "unsupported_profile": RuleBindingObservedState.UNSUPPORTED_PROFILE,
    "source_unavailable": RuleBindingObservedState.SOURCE_UNAVAILABLE,
}


class SqlAlchemyRuleBindingStateReader(RuleBindingStateReader):
    """Read current binding metadata and catalog outcomes from one SQL authority."""

    def __init__(self, engine: AsyncEngine, *, clock=current_utc_millisecond_instant) -> None:
        self._engine = engine
        self._clock = clock

    async def read_binding_states(
        self, query: RuleBindingStatesQuery
    ) -> RuleBindingStatesPage:
        if not isinstance(query, RuleBindingStatesQuery):
            raise TypeError("rule binding state query is invalid")
        binding = RuleBindingRecord.__table__
        source = RegisteredConfigurationSourceRecord.__table__
        snapshot = RuleCatalogSnapshotRecord.__table__
        target = RulePublicationTargetRecord.__table__
        conditions = [binding.c.environment_id == query.environment_id]
        if query.app_id is not None:
            conditions.append(binding.c.app_id == query.app_id)
        if query.kind is not None:
            conditions.append(binding.c.kind == query.kind.value)
        offset = (query.page - 1) * query.page_size
        try:
            async with self._engine.connect() as connection:
                total = int(
                    await connection.scalar(
                        select(func.count()).select_from(binding).where(*conditions)
                    )
                    or 0
                )
                statement = (
                    select(
                        binding.c.binding_id,
                        binding.c.environment_id,
                        binding.c.app_id,
                        binding.c.kind,
                        binding.c.profile,
                        binding.c.source_id,
                        binding.c.location,
                        source.c.name.label("source_label"),
                        source.c.provider.label("source_provider"),
                        target.c.source_id.label("target_source_id"),
                        target.c.target_body,
                        snapshot.c.read_state,
                        snapshot.c.error_code,
                        snapshot.c.last_attempt_at,
                        snapshot.c.checksum,
                        snapshot.c.source_revision,
                        snapshot.c.rule_count,
                    )
                    .select_from(
                        binding.join(source, binding.c.source_id == source.c.source_id)
                        .outerjoin(target, target.c.binding_id == binding.c.binding_id)
                        .outerjoin(snapshot, snapshot.c.binding_id == binding.c.binding_id)
                    )
                    .where(*conditions)
                    .order_by(binding.c.binding_id.asc())
                    .offset(offset)
                    .limit(query.page_size + 1)
                )
                rows = (await connection.execute(statement)).mappings().all()
                as_of = await connection.scalar(
                    select(func.max(snapshot.c.last_attempt_at)).where(
                        snapshot.c.environment_id == query.environment_id,
                        *(
                            [snapshot.c.app_id == query.app_id]
                            if query.app_id is not None
                            else []
                        ),
                    )
                )
        except SQLAlchemyError:
            raise RuntimeError("rule binding state projection is unavailable") from None

        has_more = len(rows) > query.page_size
        try:
            items = tuple(_item_from_row(row) for row in rows[: query.page_size])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("rule binding state projection is inconsistent") from None
        return RuleBindingStatesPage(
            query=query,
            as_of=_utc(as_of or self._clock()),
            coverage=RuleCatalogCoverage.COMPLETE,
            total=total,
            has_more=has_more,
            items=items,
        )


def _item_from_row(row: Mapping[str, object]) -> RuleBindingObservedStateItem:
    binding = binding_from_authority_row(row)
    read_state = row["read_state"]
    error_code = row["error_code"]
    checksum = row["checksum"]
    has_lkg = isinstance(checksum, str) and bool(checksum)
    attempted = row["last_attempt_at"]
    source_revision = row["source_revision"]
    if read_state is None:
        state = RuleBindingObservedState.NOT_READ
        freshness = RuleCatalogFreshness.NOT_READ
        rule_count = None
        source_revision = None
    elif read_state == "current":
        count = row["rule_count"]
        if type(count) is not int or count < 0:
            raise ValueError("rule catalog count is inconsistent")
        rule_count = count
        state = (
            RuleBindingObservedState.CONFIGURED_EMPTY
            if count == 0
            else RuleBindingObservedState.CURRENT_WITH_RULES
        )
        freshness = RuleCatalogFreshness.CURRENT
    else:
        state = _ERROR_STATE.get(
            error_code, RuleBindingObservedState.SOURCE_UNAVAILABLE
        )
        freshness = RuleCatalogFreshness.STALE if has_lkg else RuleCatalogFreshness.NOT_READ
        rule_count = None
        if not has_lkg:
            source_revision = None
    return RuleBindingObservedStateItem(
        binding=binding,
        state=state,
        rule_count=rule_count,
        source_revision=source_revision if isinstance(source_revision, str) else None,
        last_attempt_at=_utc(attempted) if isinstance(attempted, datetime) else None,
        freshness=freshness,
        has_last_known_good=has_lkg,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyRuleBindingStateReader"]
