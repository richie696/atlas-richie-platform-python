"""Consumer-owned persistence boundary for filtered system audit reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.system_audit import AuditQuery, SystemAuditPage


class SystemAuditReader(Protocol):
    """Read bounded, credential-free audit facts from the control-plane store."""

    async def read_system_audit(self, query: AuditQuery) -> SystemAuditPage:
        """Return the requested UTC half-open window and stable page."""


class SystemAuditAuthorityUnavailable(RuntimeError):
    """The audit authority cannot provide a trustworthy page."""
