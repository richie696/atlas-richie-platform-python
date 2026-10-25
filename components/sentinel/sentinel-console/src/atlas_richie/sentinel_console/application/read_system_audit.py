"""Read-only system audit use case."""

from __future__ import annotations

from ..domain.system_audit import AuditQuery, SystemAuditPage
from .system_audit_ports import SystemAuditAuthorityUnavailable, SystemAuditReader


class ReadSystemAudit:
    """Delegate an authorized audit query to its configured storage authority."""

    def __init__(self, reader: SystemAuditReader) -> None:
        self._reader = reader

    async def execute(self, query: AuditQuery) -> SystemAuditPage:
        """Read the selected bounded page without exposing persistence details."""
        page = await self._reader.read_system_audit(query)
        if not isinstance(page, SystemAuditPage) or page.query != query:
            raise SystemAuditAuthorityUnavailable(
                "audit authority returned a mismatched query page"
            )
        return page
