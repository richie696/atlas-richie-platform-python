"""SQLAlchemy adapter for bounded system audit queries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.system_audit_ports import (
    SystemAuditAuthorityUnavailable,
    SystemAuditReader,
)
from ...domain.system_audit import (
    AuditAction,
    AuditQuery,
    AuditRecord,
    AuditResult,
    SystemAuditPage,
)
from .models import AuditEventRecord

_ACTION_TO_STORAGE = {
    AuditAction.ACCOUNT_CREATE: "accounts.create",
    AuditAction.ACCOUNT_ROLE: "accounts.role",
    AuditAction.ACCOUNT_STATUS: "accounts.status",
    AuditAction.PASSWORD_CHANGE: "auth.password.change",
    AuditAction.SYSTEM_INITIALIZE: "system.bootstrap.initialize",
    AuditAction.RULE_VALIDATE: "rules.validate",
    AuditAction.SOURCE_REGISTER: "configuration.source.register",
    AuditAction.SOURCE_UPDATE: "configuration.source.update",
    AuditAction.DRAFT_SAVE: "rules.save_draft",
    AuditAction.DRAFT_DELETE: "rules.delete_draft",
    AuditAction.VERSION_FREEZE: "rules.freeze_version",
    AuditAction.RULE_PUBLISH: "rules.publish",
    AuditAction.PLAN_CREATE: "rules.create_plan",
    AuditAction.PLAN_CANCEL: "rules.cancel_plan",
    AuditAction.PLAN_ACTIVATE: "rules.activation_plan.activate",
    AuditAction.PLAN_RESTORE: "rules.activation_plan.restore",
}
_STORAGE_TO_ACTION = {value: key for key, value in _ACTION_TO_STORAGE.items()}
_OUTCOME_TO_RESULT = {
    "accepted": AuditResult.UNKNOWN,
    "completed": AuditResult.SUCCESS,
    "rejected": AuditResult.REJECTED,
}


class SqlAlchemySystemAuditReader(SystemAuditReader):
    """Read durable audit facts without returning secret or free-form fields."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_system_audit(self, query: AuditQuery) -> SystemAuditPage:
        """Return a newest-first page from the requested half-open UTC window."""
        as_of = _as_utc(self._clock())
        try:
            async with self._engine.connect() as connection:
                statement = self._filtered_statement(query, as_of)
                total = await connection.scalar(
                    select(func.count()).select_from(statement.subquery())
                )
                offset = (query.page - 1) * query.page_size
                rows = (
                    await connection.execute(
                        statement.order_by(
                            AuditEventRecord.created_at.desc(),
                            AuditEventRecord.event_id.desc(),
                        )
                        .offset(offset)
                        .limit(query.page_size)
                    )
                ).mappings().all()
        except SQLAlchemyError:
            raise SystemAuditAuthorityUnavailable(
                "system audit authority is unavailable"
            ) from None

        try:
            items = tuple(_record_from_row(row) for row in rows)
            return SystemAuditPage(query, as_of, int(total or 0), items)
        except (KeyError, TypeError, ValueError):
            raise SystemAuditAuthorityUnavailable(
                "system audit authority returned unsupported facts"
            ) from None

    @staticmethod
    def _filtered_statement(query: AuditQuery, as_of: datetime):
        statement = select(
            AuditEventRecord.event_id,
            AuditEventRecord.request_id,
            AuditEventRecord.actor_account_id,
            AuditEventRecord.action,
            AuditEventRecord.outcome,
            AuditEventRecord.target_id,
            AuditEventRecord.created_at,
        ).where(
            AuditEventRecord.created_at >= query.start.astimezone(UTC),
            AuditEventRecord.created_at < query.end.astimezone(UTC),
            AuditEventRecord.created_at <= as_of,
        )
        if query.actor_id:
            statement = statement.where(
                AuditEventRecord.actor_account_id == query.actor_id
            )
        if query.action is not None:
            storage_action = _ACTION_TO_STORAGE.get(query.action)
            if storage_action is None:
                statement = statement.where(AuditEventRecord.action == "")
            else:
                statement = statement.where(AuditEventRecord.action == storage_action)
        if query.result is not None:
            outcomes = tuple(
                outcome
                for outcome, result in _OUTCOME_TO_RESULT.items()
                if result is query.result
            )
            if outcomes:
                statement = statement.where(AuditEventRecord.outcome.in_(outcomes))
            else:
                statement = statement.where(AuditEventRecord.outcome == "")
        return statement


def _record_from_row(row) -> AuditRecord:
    action = _STORAGE_TO_ACTION[row["action"]]
    result = _OUTCOME_TO_RESULT[row["outcome"]]
    return AuditRecord(
        id=row["event_id"],
        occurred_at=_stored_utc(row["created_at"]),
        actor_id=row["actor_account_id"],
        action=action,
        target_id=row["target_id"],
        result=result,
        request_id=row["request_id"],
    )


def _as_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("audit timestamp is invalid")
    return value.astimezone(UTC)


def _stored_utc(value: datetime) -> datetime:
    """Interpret naive SQLite DateTime values as UTC, matching writer policy."""
    if not isinstance(value, datetime):
        raise ValueError("stored audit timestamp is invalid")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
