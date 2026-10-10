"""Consumer-owned boundary for the authorized fleet overview read model."""

from __future__ import annotations

from typing import Protocol

from ..domain.fleet_overview import FleetQuery, FleetSnapshot


class FleetOverviewReader(Protocol):
    """Read whole-population facts and one bounded page for the exact query."""

    async def read_fleet_overview(self, query: FleetQuery) -> FleetSnapshot:
        """Return server-authoritative totals, page, metrics, and dependency facts."""


class FleetOverviewAuthorityUnavailable(RuntimeError):
    """No trustworthy fleet observation is currently available."""


class FleetOverviewTargetNotFound(LookupError):
    """The environment or application named by the query is not registered."""


class FleetOverviewRateLimited(RuntimeError):
    """The observation authority cannot serve the query within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("fleet overview query rate limited")
