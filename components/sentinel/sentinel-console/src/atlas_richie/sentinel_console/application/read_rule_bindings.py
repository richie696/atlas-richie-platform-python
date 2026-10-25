"""Read and verify one query-bound rule binding directory page."""

from __future__ import annotations

from ..domain.rule_bindings import RuleBindingPage, RuleBindingQuery
from .rule_binding_ports import RuleBindingDirectoryReader


class ReadRuleBindings:
    """Delegate directory authority reads and reject mismatched query pages."""

    def __init__(self, reader: RuleBindingDirectoryReader) -> None:
        self._reader = reader

    async def execute(self, query: RuleBindingQuery) -> RuleBindingPage:
        """Return only a valid page bound to the requested filters."""
        page = await self._reader.read_rule_bindings(query)
        if not isinstance(page, RuleBindingPage) or page.query != query:
            raise ValueError("rule binding authority returned a mismatched page")
        return page

