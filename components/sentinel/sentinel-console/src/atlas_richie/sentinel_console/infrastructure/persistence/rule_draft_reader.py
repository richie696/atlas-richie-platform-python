"""SQL-backed, validated reads for binding-scoped rule drafts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_draft_detail_ports import (
    RuleDraftDetailAuthorityUnavailable,
    RuleDraftDetailNotFound,
    RuleDraftDetailReader,
)
from ...application.rule_draft_ports import (
    RuleDraftAuthorityUnavailable,
    RuleDraftReader,
)
from ...domain.rule_drafts import RuleDraftCollection, StoredRuleDraft
from .models import RuleDraftRecord
from .rule_draft_mapping import draft_body_from_row, draft_from_body

_MAX_DRAFTS_PER_BINDING = 1_000


class SqlAlchemyRuleDraftReader(RuleDraftReader, RuleDraftDetailReader):
    """Read complete persisted drafts without widening a binding's result scope."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_drafts(self, binding_id: str) -> RuleDraftCollection:
        """Read one bounded, deterministically ordered binding collection."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RuleDraftRecord.__table__)
                    .where(RuleDraftRecord.binding_id == binding_id)
                    .order_by(
                        RuleDraftRecord.updated_at.desc(),
                        RuleDraftRecord.draft_id.asc(),
                    )
                    .limit(_MAX_DRAFTS_PER_BINDING + 1)
                )
                rows = result.mappings().all()
        except SQLAlchemyError:
            raise RuleDraftAuthorityUnavailable(
                "rule draft collection is unavailable"
            ) from None
        if len(rows) > _MAX_DRAFTS_PER_BINDING:
            raise RuleDraftAuthorityUnavailable(
                "rule draft collection exceeds its supported bound"
            )
        try:
            items = tuple(_draft_from_row(row) for row in rows)
            as_of = datetime.now(UTC)
            return RuleDraftCollection(
                binding_id=binding_id,
                as_of=as_of.replace(microsecond=(as_of.microsecond // 1000) * 1000),
                items=items,
            )
        except (KeyError, TypeError, ValueError):
            raise RuleDraftAuthorityUnavailable(
                "persisted rule draft collection is invalid"
            ) from None

    async def read_rule_draft(
        self, binding_id: str, draft_id: str
    ) -> StoredRuleDraft:
        """Read one draft only when both supplied identities match the row."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RuleDraftRecord.__table__).where(
                        RuleDraftRecord.binding_id == binding_id,
                        RuleDraftRecord.draft_id == draft_id,
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise RuleDraftDetailAuthorityUnavailable(
                "rule draft detail is unavailable"
            ) from None
        if row is None:
            raise RuleDraftDetailNotFound("rule draft does not exist")
        try:
            return _draft_from_row(row)
        except (KeyError, TypeError, ValueError):
            raise RuleDraftDetailAuthorityUnavailable(
                "persisted rule draft is invalid"
            ) from None


def _draft_from_row(row) -> StoredRuleDraft:
    return draft_from_body(draft_body_from_row(row))


__all__ = ["SqlAlchemyRuleDraftReader"]
