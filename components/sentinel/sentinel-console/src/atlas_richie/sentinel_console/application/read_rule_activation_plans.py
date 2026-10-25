"""Read and verify persisted activation plans for one rule binding."""

from __future__ import annotations

from ..domain.rule_activation_plans import (
    RuleActivationPlanCollection,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from .rule_activation_plan_ports import RuleActivationPlanReader
from .rule_binding_errors import InvalidRuleIdentifier


class ReadRuleActivationPlans:
    """Delegate schedule reads and reject cross-binding authority results."""

    def __init__(self, reader: RuleActivationPlanReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str) -> RuleActivationPlanCollection:
        """Return only a schedule collection bound to the requested ruleset."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        collection = await self._reader.read_rule_activation_plans(binding_id)
        if (
            not isinstance(collection, RuleActivationPlanCollection)
            or collection.binding_id != binding_id
        ):
            raise ValueError("schedule authority returned another binding")
        return collection
