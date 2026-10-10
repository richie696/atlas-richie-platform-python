"""Consumer-owned authority boundary for the incident timeline read model."""

from __future__ import annotations

from typing import Protocol

from ..domain.incidents import IncidentPage, IncidentQuery


class IncidentTimelineReader(Protocol):
    """Read one exact incident scope, filter, time window, and cursor page."""

    async def read_incident_timeline(self, query: IncidentQuery) -> IncidentPage:
        """Return a query-bound page with whole-scope counters and safe facts."""


class IncidentTimelineAuthorityUnavailable(RuntimeError):
    """No trustworthy event timeline is currently available."""


class IncidentTimelineTargetNotFound(LookupError):
    """The environment or application named by the query is not registered."""


class IncidentTimelineRateLimited(RuntimeError):
    """The event authority cannot serve the query within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("incident timeline query rate limited")
