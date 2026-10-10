"""Consumer-owned persistence boundary for revoking a browser session."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.session import SessionRevocationResult


class CurrentSessionRevoker(Protocol):
    """Revoke a session using digests only; raw browser credentials stay at HTTP."""

    async def revoke_active_session(
        self,
        session_digest: str,
        csrf_digest: str,
        revoked_at: datetime,
    ) -> SessionRevocationResult:
        """Atomically revoke an active session when its CSRF digest matches."""
