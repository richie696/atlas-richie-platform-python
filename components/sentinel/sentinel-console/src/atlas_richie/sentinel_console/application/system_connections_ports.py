"""Consumer-owned port for runtime connection-health observations."""

from __future__ import annotations

from typing import Protocol

from ..domain.system_connections import SystemConnectionsSnapshot


class SystemConnectionsReader(Protocol):
    """Read server-probed connections from the host application's runtime owner."""

    async def read_system_connections(self) -> SystemConnectionsSnapshot:
        """Return bounded probe facts without browser-derived health claims."""


class SystemConnectionsAuthorityUnavailable(RuntimeError):
    """The host runtime cannot provide trustworthy connection observations."""
