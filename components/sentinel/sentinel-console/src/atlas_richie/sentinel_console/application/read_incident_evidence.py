"""Read and verify one selected incident's bounded evidence projection."""

from __future__ import annotations

from ..domain.incidents import IncidentDetailQuery, IncidentEvidence
from .incident_evidence_ports import IncidentEvidenceReader


class ReadIncidentEvidence:
    """Delegate to the evidence authority and reject mismatched identities."""

    def __init__(self, reader: IncidentEvidenceReader) -> None:
        self._reader = reader

    async def execute(self, query: IncidentDetailQuery) -> IncidentEvidence:
        """Return evidence bound to the exact event, scope, window, and filters."""
        evidence = await self._reader.read_incident_evidence(query)
        if not isinstance(evidence, IncidentEvidence) or evidence.query != query:
            raise ValueError("incident evidence authority returned a mismatched query")
        return evidence
