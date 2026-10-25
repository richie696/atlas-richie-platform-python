"""Read and verify the complete draft collection for one rule binding."""

from __future__ import annotations

from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_drafts import RuleDraftCollection
from .rule_binding_errors import InvalidRuleIdentifier
from .rule_draft_ports import RuleDraftReader


class ReadRuleDrafts:
    """Delegate to the durable authority and verify its binding identity."""

    def __init__(self, reader: RuleDraftReader) -> None:
        self._reader = reader

    async def execute(self, binding_id: str) -> RuleDraftCollection:
        """Return only a complete collection for the requested binding."""
        if not is_rule_binding_identifier(binding_id):
            raise InvalidRuleIdentifier("rule binding identity is invalid")
        collection = await self._reader.read_rule_drafts(binding_id)
        if (
            not isinstance(collection, RuleDraftCollection)
            or collection.binding_id != binding_id
        ):
            raise ValueError("rule draft authority returned another binding")
        return collection
