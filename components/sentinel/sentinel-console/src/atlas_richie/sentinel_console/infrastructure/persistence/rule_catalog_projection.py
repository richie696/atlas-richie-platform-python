"""SQL projection adapter for bounded source-backed rule catalog reads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_catalog_ports import RuleCatalogProjection
from ...application.rule_value_codec import parse_rule_value
from ...application.rule_value_projection import rule_value_fields
from ...domain.rule_bindings import RuleBinding, RuleKind
from ...domain.rule_catalog import (
    MAX_RULE_CATALOG_ISSUES,
    RuleCatalogCoverage,
    RuleCatalogEntry,
    RuleCatalogFreshness,
    RuleCatalogIssue,
    RuleCatalogIssueReason,
    RuleCatalogPage,
    RuleCatalogQuery,
)
from ...domain.rule_snapshots import RuleRecord, RuleSetSnapshot
from ...domain.utc_time import current_utc_millisecond_instant
from .models import (
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleCatalogRuleRecord,
    RuleCatalogSnapshotRecord,
    RulePublicationTargetRecord,
)
from .rule_binding_directory_reader import binding_from_authority_row

_ERROR_CODES = frozenset(
    {
        "source_unavailable",
        "content_invalid",
        "target_missing",
        "unsupported_profile",
    }
)


class SqlAlchemyRuleCatalogProjection(RuleCatalogProjection):
    """Persist per-binding last-known-good rules and query them in SQL pages."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        clock=current_utc_millisecond_instant,
    ) -> None:
        self._engine = engine
        self._clock = clock

    async def refresh_candidates(
        self, environment_id: str, app_id: str | None, limit: int
    ) -> tuple[RuleBinding, ...]:
        if (
            not isinstance(environment_id, str)
            or not environment_id.strip()
            or (app_id is not None and not app_id.strip())
            or type(limit) is not int
            or not 1 <= limit <= 24
        ):
            raise ValueError("rule catalog refresh scope is invalid")
        binding = RuleBindingRecord.__table__
        source = RegisteredConfigurationSourceRecord.__table__
        target = RulePublicationTargetRecord.__table__
        snapshot = RuleCatalogSnapshotRecord.__table__
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
                snapshot.c.last_attempt_at,
            )
            .select_from(
                binding.outerjoin(source, binding.c.source_id == source.c.source_id)
                .outerjoin(target, binding.c.binding_id == target.c.binding_id)
                .outerjoin(snapshot, binding.c.binding_id == snapshot.c.binding_id)
            )
            .where(binding.c.environment_id == environment_id)
            .order_by(
                case((snapshot.c.last_attempt_at.is_(None), 0), else_=1),
                snapshot.c.last_attempt_at.asc(),
                binding.c.binding_id.asc(),
            )
            .limit(limit)
        )
        if app_id is not None:
            statement = statement.where(binding.c.app_id == app_id)
        try:
            async with self._engine.connect() as connection:
                rows = (await connection.execute(statement)).mappings().all()
        except SQLAlchemyError:
            raise RuntimeError("rule catalog projection is unavailable") from None
        try:
            return tuple(binding_from_authority_row(row) for row in rows)
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("rule catalog binding authority is inconsistent") from None

    async def record_success(
        self, snapshot: RuleSetSnapshot, attempted_at: datetime
    ) -> None:
        if not isinstance(snapshot, RuleSetSnapshot) or not _aware(attempted_at):
            raise ValueError("rule catalog success fact is invalid")
        binding = snapshot.binding
        snapshot_table = RuleCatalogSnapshotRecord.__table__
        rules_table = RuleCatalogRuleRecord.__table__
        metadata = {
            "binding_id": binding.id,
            "environment_id": binding.environment_id,
            "app_id": binding.app_id,
            "kind": binding.kind.value,
            "read_state": "current",
            "error_code": None,
            "last_attempt_at": _utc(attempted_at),
            "snapshot_as_of": _utc(snapshot.as_of),
            "checksum": snapshot.checksum,
            "source_revision": snapshot.source_revision,
            "version_id": snapshot.version_id,
            "rule_count": len(snapshot.records),
        }
        projected: list[dict[str, object]] = []
        for record in snapshot.records:
            resource = getattr(record.rule, "resource", "")
            projected.append(
                {
                    "binding_id": binding.id,
                    "rule_id": record.id,
                    "environment_id": binding.environment_id,
                    "app_id": binding.app_id,
                    "kind": binding.kind.value,
                    "resource_search": resource,
                    "rule_body": rule_value_fields(record.rule),
                }
            )
        try:
            async with self._engine.begin() as connection:
                exists = await connection.scalar(
                    select(snapshot_table.c.binding_id).where(
                        snapshot_table.c.binding_id == binding.id
                    )
                )
                if exists is None:
                    await connection.execute(snapshot_table.insert().values(**metadata))
                else:
                    await connection.execute(
                        update(snapshot_table)
                        .where(snapshot_table.c.binding_id == binding.id)
                        .values(**metadata)
                    )
                await connection.execute(
                    delete(rules_table).where(rules_table.c.binding_id == binding.id)
                )
                if projected:
                    await connection.execute(rules_table.insert(), projected)
        except SQLAlchemyError:
            raise RuntimeError("rule catalog projection write failed") from None

    async def record_failure(
        self, binding: RuleBinding, reason: str, attempted_at: datetime
    ) -> None:
        if (
            not isinstance(binding, RuleBinding)
            or reason not in _ERROR_CODES
            or not _aware(attempted_at)
        ):
            raise ValueError("rule catalog failure fact is invalid")
        table = RuleCatalogSnapshotRecord.__table__
        try:
            async with self._engine.begin() as connection:
                current = (
                    await connection.execute(
                        select(table.c.checksum).where(table.c.binding_id == binding.id)
                    )
                ).scalar_one_or_none()
                metadata = {
                    "environment_id": binding.environment_id,
                    "app_id": binding.app_id,
                    "kind": binding.kind.value,
                    "read_state": "stale" if current is not None else "unavailable",
                    "error_code": reason,
                    "last_attempt_at": _utc(attempted_at),
                }
                if current is None:
                    exists = await connection.scalar(
                        select(table.c.binding_id).where(
                            table.c.binding_id == binding.id
                        )
                    )
                    if exists is None:
                        await connection.execute(
                            table.insert().values(
                                binding_id=binding.id,
                                **metadata,
                                snapshot_as_of=None,
                                checksum=None,
                                source_revision=None,
                                version_id=None,
                                rule_count=0,
                            )
                        )
                    else:
                        await connection.execute(
                            update(table)
                            .where(table.c.binding_id == binding.id)
                            .values(**metadata)
                        )
                else:
                    await connection.execute(
                        update(table)
                        .where(table.c.binding_id == binding.id)
                        .values(**metadata)
                    )
        except SQLAlchemyError:
            raise RuntimeError("rule catalog freshness write failed") from None

    async def read_catalog(self, query: RuleCatalogQuery) -> RuleCatalogPage:
        if not isinstance(query, RuleCatalogQuery):
            raise TypeError("rule catalog query is invalid")
        binding = RuleBindingRecord.__table__
        source = RegisteredConfigurationSourceRecord.__table__
        snapshot = RuleCatalogSnapshotRecord.__table__
        rules = RuleCatalogRuleRecord.__table__
        target = RulePublicationTargetRecord.__table__
        scope = [binding.c.environment_id == query.environment_id]
        if query.app_id is not None:
            scope.append(binding.c.app_id == query.app_id)
        try:
            async with self._engine.connect() as connection:
                bindings_total = int(
                    await connection.scalar(
                        select(func.count()).select_from(binding).where(*scope)
                    )
                    or 0
                )
                states = (
                    await connection.execute(
                        select(snapshot.c.read_state, func.count())
                        .select_from(snapshot)
                        .where(
                            snapshot.c.environment_id == query.environment_id,
                            *(
                                [snapshot.c.app_id == query.app_id]
                                if query.app_id is not None
                                else []
                            ),
                        )
                        .group_by(snapshot.c.read_state)
                    )
                ).all()
                by_state = {state: int(count) for state, count in states}
                current = by_state.get("current", 0)
                stale = by_state.get("stale", 0)
                not_read = max(0, bindings_total - current - stale)
                complete = current == bindings_total and stale == 0
                predicates = [
                    rules.c.environment_id == query.environment_id,
                    snapshot.c.read_state.in_(("current", "stale")),
                ]
                if query.app_id is not None:
                    predicates.append(rules.c.app_id == query.app_id)
                if query.kind is not None:
                    predicates.append(rules.c.kind == query.kind.value)
                if query.search:
                    escaped = (
                        query.search.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    )
                    predicates.append(rules.c.resource_search.ilike(f"%{escaped}%", escape="\\"))
                rule_count_statement = (
                    select(func.count())
                    .select_from(rules.join(snapshot, rules.c.binding_id == snapshot.c.binding_id))
                    .where(*predicates)
                )
                exact_total = (
                    int(await connection.scalar(rule_count_statement) or 0)
                    if complete
                    else None
                )
                rows_statement = (
                    select(
                        binding.c.binding_id,
                        binding.c.environment_id,
                        binding.c.app_id,
                        binding.c.kind,
                        binding.c.profile,
                        binding.c.source_id,
                        binding.c.location,
                        source.c.name.label("source_label"),
                        rules.c.rule_id,
                        rules.c.rule_body,
                        snapshot.c.read_state,
                        snapshot.c.error_code,
                        snapshot.c.last_attempt_at,
                        snapshot.c.snapshot_as_of,
                        snapshot.c.checksum,
                        snapshot.c.source_revision,
                        snapshot.c.version_id,
                    )
                    .select_from(
                        rules.join(
                            binding, rules.c.binding_id == binding.c.binding_id
                        )
                        .join(snapshot, rules.c.binding_id == snapshot.c.binding_id)
                        .join(source, binding.c.source_id == source.c.source_id)
                    )
                    .where(*predicates)
                    .order_by(binding.c.binding_id.asc(), rules.c.rule_id.asc())
                    .offset((query.page - 1) * query.page_size)
                    .limit(query.page_size + 1)
                )
                rows = (await connection.execute(rows_statement)).mappings().all()
                issue_statement = (
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
                    )
                    .select_from(
                        binding.join(source, binding.c.source_id == source.c.source_id)
                        .outerjoin(
                            target, binding.c.binding_id == target.c.binding_id
                        )
                        .outerjoin(
                            snapshot, binding.c.binding_id == snapshot.c.binding_id
                        )
                    )
                    .where(
                        *scope,
                        or_(
                            snapshot.c.binding_id.is_(None),
                            snapshot.c.read_state != "current",
                        ),
                    )
                    .order_by(binding.c.binding_id.asc())
                    .limit(MAX_RULE_CATALOG_ISSUES)
                )
                issue_rows = (
                    await connection.execute(issue_statement)
                ).mappings().all()
                as_of_value = await connection.scalar(
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
            raise RuntimeError("rule catalog projection is unavailable") from None

        has_more = len(rows) > query.page_size
        items = tuple(_entry_from_row(row) for row in rows[: query.page_size])
        issues = tuple(_issue_from_row(row) for row in issue_rows)
        return RuleCatalogPage(
            query=query,
            as_of=_utc(as_of_value or self._clock()),
            coverage=(
                RuleCatalogCoverage.COMPLETE
                if complete
                else RuleCatalogCoverage.PARTIAL
            ),
            bindings_total=bindings_total,
            bindings_current=current,
            bindings_stale=stale,
            bindings_not_read=not_read,
            total=exact_total,
            has_more=has_more,
            items=items,
            issues=issues,
        )


def _entry_from_row(row: Mapping[str, object]) -> RuleCatalogEntry:
    binding = RuleBinding(
        id=row["binding_id"],
        environment_id=row["environment_id"],
        app_id=row["app_id"],
        kind=RuleKind(row["kind"]),
        profile=row["profile"],
        source_id=row["source_id"],
        source_label=row["source_label"],
        location=row["location"],
    )
    rule = parse_rule_value(binding.kind, row["rule_body"])
    return RuleCatalogEntry(
        binding=binding,
        record=RuleRecord(id=row["rule_id"], rule=rule),
        checksum=row["checksum"],
        source_revision=row["source_revision"],
        version_id=row["version_id"],
        snapshot_as_of=_utc(row["snapshot_as_of"]),
        last_attempt_at=_utc(row["last_attempt_at"]),
        freshness=(
            RuleCatalogFreshness.CURRENT
            if row["read_state"] == "current"
            else RuleCatalogFreshness.STALE
        ),
    )


def _issue_from_row(row: Mapping[str, object]) -> RuleCatalogIssue:
    binding = binding_from_authority_row(row)
    state = row["read_state"]
    error_code = row["error_code"]
    reason = (
        RuleCatalogIssueReason(error_code)
        if error_code in {value.value for value in RuleCatalogIssueReason}
        else RuleCatalogIssueReason.NOT_READ
    )
    attempted = row["last_attempt_at"]
    return RuleCatalogIssue(
        binding=binding,
        reason=reason,
        last_attempt_at=_utc(attempted) if attempted is not None else None,
        stale=state == "stale",
    )


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyRuleCatalogProjection"]
