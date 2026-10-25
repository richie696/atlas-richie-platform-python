"""Shared session test authorities for Console HTTP tests."""

from __future__ import annotations

from datetime import datetime

from atlas_richie.sentinel_console.domain.session import SessionRevocationResult


class UnusedSessionRevoker:
    """Fail when a test unexpectedly reaches logout persistence."""

    async def revoke_active_session(
        self,
        session_digest: str,
        csrf_digest: str,
        revoked_at: datetime,
    ) -> SessionRevocationResult:
        raise AssertionError("logout route must not revoke a session")
