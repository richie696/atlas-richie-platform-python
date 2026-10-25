"""Read the Console-owned provider state projection for registered bindings."""

from __future__ import annotations

from ..domain.rule_catalog import RuleBindingStatesPage, RuleBindingStatesQuery
from .rule_binding_state_ports import RuleBindingStateReader


class ReadRuleBindingStates:
    """Validate ownership of the typed binding-state query result."""

    def __init__(self, reader: RuleBindingStateReader) -> None:
        self._reader = reader

    async def execute(self, query: RuleBindingStatesQuery) -> RuleBindingStatesPage:
        """Read an exact query; reject a reader that returns another scope."""
        page = await self._reader.read_binding_states(query)
        if not isinstance(page, RuleBindingStatesPage) or page.query != query:
            raise ValueError("rule binding state reader returned a mismatched page")
        return page


__all__ = ["ReadRuleBindingStates"]
