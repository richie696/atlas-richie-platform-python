"""Use case for one bounded incident-retention maintenance pass."""

from __future__ import annotations

from datetime import UTC, datetime

from .incident_retention_ports import IncidentHistoryRetention


class ExpireIncidentHistory:
    """Run one idempotent purge pass against the incident-history authority."""

    def __init__(self, retention: IncidentHistoryRetention) -> None:
        self._retention = retention

    async def execute(self, now: datetime) -> int:
        """Delete expired rows using an explicit aware UTC instant."""
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError("incident retention time must be timezone-aware")
        expired_count = await self._retention.expire_incident_history(
            now.astimezone(UTC)
        )
        if type(expired_count) is not int or expired_count < 0:
            raise RuntimeError("incident retention authority returned an invalid count")
        return expired_count


__all__ = ["ExpireIncidentHistory"]
