"""Consumer-owned persistence boundary for authenticated session reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.session import ActiveAccountSession


class CurrentSessionReader(Protocol):
    """Resolve a digest to an active account session, never a raw cookie."""

    async def read_active_session(
        self, session_digest: str
    ) -> ActiveAccountSession | None:
        """Return the current active session or ``None`` when it is anonymous."""
