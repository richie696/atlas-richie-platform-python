"""Consumer-owned port for deployment-provided protocol observations."""

from __future__ import annotations

from typing import Protocol

from ..domain.system_protocols import SystemProtocolsSnapshot


class SystemProtocolsReader(Protocol):
    """Read confirmed protocol facts from the host application's runtime authority."""

    async def read_system_protocols(self) -> SystemProtocolsSnapshot:
        """Return a snapshot without inferring absent deployment negotiations."""


class SystemProtocolsAuthorityUnavailable(RuntimeError):
    """The host runtime cannot provide a trustworthy protocol snapshot."""
