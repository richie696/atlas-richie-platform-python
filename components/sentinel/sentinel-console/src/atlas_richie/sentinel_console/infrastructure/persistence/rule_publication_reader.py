"""SQL-backed reads for immutable rule-publication lifecycle facts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationDetailReader,
    RulePublicationNotFound,
    RulePublicationReader,
)
from ...domain.rule_publications import RulePublicationCollection
from .models import RulePublicationRecord
from .rule_publication_mapping import publication_from_row

_MAX_PUBLICATIONS_PER_BINDING = 1_000


class SqlAlchemyRulePublicationReader(
    RulePublicationReader, RulePublicationDetailReader
):
    """Read complete bounded history and exact details from the SQL authority."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_publications(
        self, binding_id: str
    ) -> RulePublicationCollection:
        """Return the exact binding history newest first, refusing truncation."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RulePublicationRecord.__table__)
                    .where(RulePublicationRecord.binding_id == binding_id)
                    .order_by(
                        RulePublicationRecord.created_at.desc(),
                        RulePublicationRecord.publication_id.asc(),
                    )
                    .limit(_MAX_PUBLICATIONS_PER_BINDING + 1)
                )
                rows = result.mappings().all()
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "rule publication history is unavailable"
            ) from None
        if len(rows) > _MAX_PUBLICATIONS_PER_BINDING:
            raise RulePublicationAuthorityUnavailable(
                "rule publication history exceeds its supported bound"
            )
        try:
            items = tuple(publication_from_row(row) for row in rows)
            return RulePublicationCollection(
                binding_id=binding_id,
                as_of=_now(),
                items=items,
            )
        except (KeyError, TypeError, ValueError):
            raise RulePublicationAuthorityUnavailable(
                "persisted rule publication history is invalid"
            ) from None

    async def read_rule_publication(
        self, binding_id: str, publication_id: str
    ):
        """Read one publication only through its binding-scoped identity."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RulePublicationRecord.__table__).where(
                        RulePublicationRecord.binding_id == binding_id,
                        RulePublicationRecord.publication_id == publication_id,
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise RulePublicationAuthorityUnavailable(
                "rule publication detail is unavailable"
            ) from None
        if row is None:
            raise RulePublicationNotFound("rule publication does not exist")
        try:
            return publication_from_row(row)
        except (KeyError, TypeError, ValueError):
            raise RulePublicationAuthorityUnavailable(
                "persisted rule publication is invalid"
            ) from None


def _now() -> datetime:
    value = datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


__all__ = ["SqlAlchemyRulePublicationReader"]
