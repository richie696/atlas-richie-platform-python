"""Application-owned ports for the registered-source rule catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.rule_bindings import RuleBinding
from ..domain.rule_catalog import RuleCatalogPage, RuleCatalogQuery
from ..domain.rule_snapshots import RuleSetSnapshot


class RuleCatalogProjection(Protocol):
    """Persist and query bounded read projections without owning source truth."""

    async def refresh_candidates(
        self, environment_id: str, app_id: str | None, limit: int
    ) -> tuple[RuleBinding, ...]:
        """Select never-read and least-recently-attempted bindings first."""

    async def record_success(self, snapshot: RuleSetSnapshot, attempted_at: datetime) -> None:
        """Atomically replace one binding's projected rules and current facts."""

    async def record_failure(
        self, binding: RuleBinding, reason: str, attempted_at: datetime
    ) -> None:
        """Retain the last successful projection while marking it stale."""

    async def read_catalog(self, query: RuleCatalogQuery) -> RuleCatalogPage:
        """Read a SQL-paginated page and complete scope coverage facts."""


__all__ = ["RuleCatalogProjection"]
