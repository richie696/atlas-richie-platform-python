"""Read-only use case for system connection observations."""

from __future__ import annotations

from ..domain.system_connections import SystemConnectionsSnapshot
from .system_connections_ports import (
    SystemConnectionsAuthorityUnavailable,
    SystemConnectionsReader,
)


class ReadSystemConnections:
    """Delegate the read to the host-owned connection-fact authority."""

    def __init__(self, reader: SystemConnectionsReader) -> None:
        self._reader = reader

    async def execute(self) -> SystemConnectionsSnapshot:
        """Read observed facts without converting missing sources into success."""
        snapshot = await self._reader.read_system_connections()
        if not isinstance(snapshot, SystemConnectionsSnapshot):
            raise SystemConnectionsAuthorityUnavailable(
                "connection authority returned an invalid snapshot"
            )
        return snapshot
