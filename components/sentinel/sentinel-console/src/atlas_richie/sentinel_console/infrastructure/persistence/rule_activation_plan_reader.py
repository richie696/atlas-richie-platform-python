"""SQL-backed reads for durable rule activation plans."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_activation_plan_ports import (
    RuleActivationPlanAuthorityUnavailable,
    RuleActivationPlanReader,
)
from ...domain.rule_activation_plans import RuleActivationPlanCollection
from .models import RuleActivationPlanRecord
from .rule_activation_plan_mapping import (
    activation_plan_body_from_row,
    activation_plan_from_body,
)

_MAX_PLANS_PER_BINDING = 1_000


class SqlAlchemyRuleActivationPlanReader(RuleActivationPlanReader):
    """Read a complete bounded schedule snapshot for one exact binding."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_rule_activation_plans(
        self, binding_id: str
    ) -> RuleActivationPlanCollection:
        """Return every saved plan ordered by activation time and identity."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RuleActivationPlanRecord.__table__)
                    .where(RuleActivationPlanRecord.binding_id == binding_id)
                    .order_by(
                        RuleActivationPlanRecord.activate_at.asc(),
                        RuleActivationPlanRecord.plan_id.asc(),
                    )
                    .limit(_MAX_PLANS_PER_BINDING + 1)
                )
                rows = result.mappings().all()
        except SQLAlchemyError:
            raise RuleActivationPlanAuthorityUnavailable(
                "rule activation plan collection is unavailable"
            ) from None
        if len(rows) > _MAX_PLANS_PER_BINDING:
            raise RuleActivationPlanAuthorityUnavailable(
                "rule activation plan collection exceeds its supported bound"
            )
        try:
            items = tuple(
                activation_plan_from_body(activation_plan_body_from_row(row))
                for row in rows
            )
            as_of = datetime.now(UTC)
            return RuleActivationPlanCollection(
                binding_id=binding_id,
                as_of=as_of.replace(
                    microsecond=(as_of.microsecond // 1000) * 1000
                ),
                items=items,
            )
        except (KeyError, TypeError, ValueError):
            raise RuleActivationPlanAuthorityUnavailable(
                "persisted rule activation plan collection is invalid"
            ) from None


__all__ = ["SqlAlchemyRuleActivationPlanReader"]
