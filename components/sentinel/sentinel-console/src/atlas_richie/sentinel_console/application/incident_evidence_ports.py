"""Consumer-owned authority boundary for explicit incident evidence reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.incidents import IncidentDetailQuery, IncidentEvidence


class IncidentEvidenceReader(Protocol):
    """Read evidence for one selected event and exact set of active filters."""

    async def read_incident_evidence(
        self, query: IncidentDetailQuery
    ) -> IncidentEvidence:
        """Return evidence only when the event remains visible to this query."""


class IncidentEvidenceAuthorityUnavailable(RuntimeError):
    """The evidence authority is currently unavailable."""


class IncidentEvidenceNotFound(LookupError):
    """The selected event is missing or excluded by its active filters."""


class IncidentEvidenceRateLimited(RuntimeError):
    """The evidence authority cannot serve the read within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("incident evidence query rate limited")
