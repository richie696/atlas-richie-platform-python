"""Read exact-binding historical process-epoch observations."""

from __future__ import annotations

from ..domain.rule_load_observation_history import (
    RuleLoadObservationHistoryPage,
    RuleLoadObservationHistoryQuery,
)
from .rule_load_observation_history_ports import RuleLoadObservationHistoryReader


class ReadRuleLoadObservationHistory:
    """Ensure adapters return exactly the requested immutable history scope."""

    def __init__(self, reader: RuleLoadObservationHistoryReader) -> None:
        self._reader = reader

    async def execute(
        self, query: RuleLoadObservationHistoryQuery
    ) -> RuleLoadObservationHistoryPage:
        page = await self._reader.read_rule_load_observation_history(query)
        if not isinstance(page, RuleLoadObservationHistoryPage) or page.query != query:
            raise ValueError("rule-load history reader returned a mismatched query")
        return page


__all__ = ["ReadRuleLoadObservationHistory"]
