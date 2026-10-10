"""SQLAlchemy persistence adapter for immutable rule-validation evidence."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_validation_ports import (
    RuleValidationAuthorityUnavailable,
    RuleValidationReceiptReader,
    RuleValidationReceiptWriter,
)
from ...domain.rule_validation import (
    RuleCandidateValidationReceipt,
    RuleValidationIssue,
    RuleValidationIssueCode,
)
from .models import AuditEventRecord, RuleValidationReceiptRecord


class SqlAlchemyRuleValidationReceiptStore(
    RuleValidationReceiptReader, RuleValidationReceiptWriter
):
    """Atomically persist/read safe validation receipts and their audit facts."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record_validation(
        self,
        receipt: RuleCandidateValidationReceipt,
        *,
        actor_id: str,
        request_id: str,
        created_at: datetime,
    ) -> None:
        """Commit immutable receipt and audit row in the same transaction."""
        issue_rows = [
            {
                "code": issue.code.value,
                "recordIndex": issue.record_index,
                "path": issue.path,
            }
            for issue in receipt.issues
        ]
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    insert(RuleValidationReceiptRecord).values(
                        validation_id=receipt.validation_id,
                        binding_id=receipt.binding_id,
                        profile=receipt.profile,
                        base_checksum=receipt.base_checksum,
                        candidate_checksum=receipt.candidate_checksum,
                        is_publishable=receipt.is_publishable,
                        issues=issue_rows,
                        actor_account_id=actor_id,
                        request_id=request_id,
                        created_at=created_at,
                    )
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=str(uuid4()),
                        request_id=request_id,
                        actor_account_id=actor_id,
                        action="rules.validate",
                        outcome="completed",
                        target_kind="rule_binding",
                        target_id=receipt.binding_id,
                        created_at=created_at,
                    )
                )
        except SQLAlchemyError:
            raise RuleValidationAuthorityUnavailable(
                "validation receipt authority is unavailable"
            ) from None

    async def read_validation(
        self, validation_id: str
    ) -> RuleCandidateValidationReceipt | None:
        """Read the exact persisted receipt or fail closed on corrupt evidence."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RuleValidationReceiptRecord.__table__).where(
                        RuleValidationReceiptRecord.validation_id == validation_id
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise RuleValidationAuthorityUnavailable(
                "validation receipt authority is unavailable"
            ) from None
        if row is None:
            return None
        try:
            return _receipt_from_row(row)
        except (KeyError, TypeError, ValueError):
            raise RuleValidationAuthorityUnavailable(
                "persisted validation receipt is invalid"
            ) from None


def _receipt_from_row(row) -> RuleCandidateValidationReceipt:
    issue_data = row["issues"]
    if not isinstance(issue_data, list):
        raise ValueError("persisted validation issues are invalid")
    issues = tuple(
        RuleValidationIssue(
            RuleValidationIssueCode(issue["code"]),
            issue["recordIndex"],
            issue["path"],
        )
        for issue in issue_data
        if isinstance(issue, dict)
        and set(issue) == {"code", "recordIndex", "path"}
    )
    if len(issues) != len(issue_data):
        raise ValueError("persisted validation issues are invalid")
    return RuleCandidateValidationReceipt(
        binding_id=row["binding_id"],
        profile=row["profile"],
        base_checksum=row["base_checksum"],
        candidate_checksum=row["candidate_checksum"],
        validation_id=row["validation_id"],
        is_publishable=row["is_publishable"],
        issues=issues,
    )


__all__ = ["SqlAlchemyRuleValidationReceiptStore"]
