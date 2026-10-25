"""Application-owned query contract for durable current rule-load facts."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_load_observation_query import (
    RuleLoadObservationPage,
    RuleLoadObservationQuery,
)


class RuleLoadObservationQueryReader(Protocol):
    """Read only persisted Collector receipts and active enrollments."""

    async def read_rule_load_observations(
        self, query: RuleLoadObservationQuery
    ) -> RuleLoadObservationPage:
        """Return target inventory and current observations for the query."""


__all__ = ["RuleLoadObservationQueryReader"]
