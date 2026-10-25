"""Read the Console-owned current Rule Load Observation projection."""

from __future__ import annotations

from ..domain.rule_load_observation_query import (
    RuleLoadObservationPage,
    RuleLoadObservationQuery,
)
from .rule_load_observation_query_ports import RuleLoadObservationQueryReader


class ReadRuleLoadObservations:
    """Ensure the query adapter returns exactly the requested scope."""

    def __init__(self, reader: RuleLoadObservationQueryReader) -> None:
        self._reader = reader

    async def execute(
        self, query: RuleLoadObservationQuery
    ) -> RuleLoadObservationPage:
        """Return a validated application-level read result."""
        page = await self._reader.read_rule_load_observations(query)
        if not isinstance(page, RuleLoadObservationPage) or page.query != query:
            raise ValueError("rule-load reader returned a mismatched query")
        return page


__all__ = ["ReadRuleLoadObservations"]
