"""Application-owned query boundary for provider state by registered binding."""

from __future__ import annotations

from typing import Protocol

from ..domain.rule_catalog import RuleBindingStatesPage, RuleBindingStatesQuery


class RuleBindingStateReader(Protocol):
    """Read persisted provider outcomes without calling external providers."""

    async def read_binding_states(
        self, query: RuleBindingStatesQuery
    ) -> RuleBindingStatesPage:
        """Return a stable, bounded page for the exact binding scope."""


__all__ = ["RuleBindingStateReader"]
