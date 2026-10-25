"""SQL-backed, checksum-verified reads for immutable rule versions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_version_ports import (
    RuleSetVersionAuthorityUnavailable,
    RuleSetVersionDetailReader,
    RuleSetVersionNotFound,
    RuleSetVersionReader,
)
from ...domain.rule_versions import RuleSetVersion, RuleSetVersionCollection
from .models import RuleSetVersionRecord
from .rule_version_mapping import version_body_from_row, version_from_body

_MAX_VERSIONS_PER_BINDING = 1_000


class SqlAlchemyRuleVersionReader(RuleSetVersionReader, RuleSetVersionDetailReader):
    """Read immutable version history and verify each stored record checksum."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_versions(self, binding_id: str) -> RuleSetVersionCollection:
        """Read a complete, bounded collection ordered newest-first."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RuleSetVersionRecord.__table__)
                    .where(RuleSetVersionRecord.binding_id == binding_id)
                    .order_by(
                        RuleSetVersionRecord.created_at.desc(),
                        RuleSetVersionRecord.version_id.asc(),
                    )
                    .limit(_MAX_VERSIONS_PER_BINDING + 1)
                )
                rows = result.mappings().all()
        except SQLAlchemyError:
            raise RuleSetVersionAuthorityUnavailable(
                "rule version collection is unavailable"
            ) from None
        if len(rows) > _MAX_VERSIONS_PER_BINDING:
            raise RuleSetVersionAuthorityUnavailable(
                "rule version collection exceeds its supported bound"
            )
        try:
            items = tuple(_version_from_row(row) for row in rows)
            as_of = datetime.now(UTC)
            return RuleSetVersionCollection(
                binding_id=binding_id,
                as_of=as_of.replace(microsecond=(as_of.microsecond // 1000) * 1000),
                items=items,
            )
        except (KeyError, TypeError, ValueError):
            raise RuleSetVersionAuthorityUnavailable(
                "persisted rule version collection is invalid"
            ) from None

    async def read_rule_version(
        self, binding_id: str, version_id: str
    ) -> RuleSetVersion:
        """Read one exact version within its binding path."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RuleSetVersionRecord.__table__).where(
                        RuleSetVersionRecord.binding_id == binding_id,
                        RuleSetVersionRecord.version_id == version_id,
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise RuleSetVersionAuthorityUnavailable(
                "rule version detail is unavailable"
            ) from None
        if row is None:
            raise RuleSetVersionNotFound("rule version does not exist")
        try:
            return _version_from_row(row)
        except (KeyError, TypeError, ValueError):
            raise RuleSetVersionAuthorityUnavailable(
                "persisted rule version is invalid"
            ) from None


def _version_from_row(row) -> RuleSetVersion:
    return version_from_body(version_body_from_row(row))


__all__ = ["SqlAlchemyRuleVersionReader"]
