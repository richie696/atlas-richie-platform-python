"""Read and verify one authority-owned fleet overview snapshot."""

from __future__ import annotations

from ..domain.fleet_overview import FleetQuery, FleetSnapshot
from .fleet_overview_ports import FleetOverviewReader


class ReadFleetOverview:
    """Delegate a fleet query and reject snapshots that do not echo its identity."""

    def __init__(self, reader: FleetOverviewReader) -> None:
        self._reader = reader

    async def execute(self, query: FleetQuery) -> FleetSnapshot:
        """Return only a valid snapshot for the exact caller selection."""
        snapshot = await self._reader.read_fleet_overview(query)
        if not isinstance(snapshot, FleetSnapshot) or snapshot.query != query:
            raise ValueError("fleet authority returned a mismatched snapshot")
        return snapshot
