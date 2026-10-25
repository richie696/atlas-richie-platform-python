"""Application port for durable historical process observations."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_load_observation_history import (
    RuleLoadObservationHistoryPage,
    RuleLoadObservationHistoryQuery,
)


class RuleLoadObservationHistoryReader(Protocol):
    """Read retained inbox facts for old or revoked process epochs."""

    async def read_rule_load_observation_history(
        self, query: RuleLoadObservationHistoryQuery
    ) -> RuleLoadObservationHistoryPage:
        """Return only observations outside the currently active epoch."""


__all__ = ["RuleLoadObservationHistoryReader"]
