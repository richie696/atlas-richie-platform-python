"""Read and verify a query-bound incident timeline page."""

from __future__ import annotations

from ..domain.incidents import IncidentPage, IncidentQuery
from .incident_timeline_ports import IncidentTimelineReader


class ReadIncidentTimeline:
    """Delegate to the event authority and reject snapshots for another query."""

    def __init__(self, reader: IncidentTimelineReader) -> None:
        self._reader = reader

    async def execute(self, query: IncidentQuery) -> IncidentPage:
        """Return only a page whose frozen contract validates against the query."""
        page = await self._reader.read_incident_timeline(query)
        if not isinstance(page, IncidentPage) or page.query != query:
            raise ValueError("incident authority returned a mismatched page")
        return page
