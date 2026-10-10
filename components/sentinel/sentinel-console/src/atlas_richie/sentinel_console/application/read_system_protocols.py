"""Read-only use case for deployment protocol observations."""

from __future__ import annotations

from .system_protocols_ports import (
    SystemProtocolsAuthorityUnavailable,
    SystemProtocolsReader,
)
from ..domain.system_protocols import SystemProtocolsSnapshot


class ReadSystemProtocols:
    """Delegate the read to the host-owned protocol-fact authority."""

    def __init__(self, reader: SystemProtocolsReader) -> None:
        self._reader = reader

    async def execute(self) -> SystemProtocolsSnapshot:
        """Read the current confirmed snapshot without manufacturing defaults."""
        snapshot = await self._reader.read_system_protocols()
        if not isinstance(snapshot, SystemProtocolsSnapshot):
            raise SystemProtocolsAuthorityUnavailable(
                "protocol authority returned an invalid snapshot"
            )
        return snapshot
