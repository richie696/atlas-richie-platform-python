"""Consumer-owned storage boundary for incident retention maintenance."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class IncidentHistoryRetention(Protocol):
    """Physically remove incident records whose durable expiry has passed."""

    async def expire_incident_history(self, now: datetime) -> int:
        """Delete rows expiring at or before the supplied UTC instant."""


__all__ = ["IncidentHistoryRetention"]
