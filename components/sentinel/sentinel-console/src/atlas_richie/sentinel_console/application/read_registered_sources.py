"""Read registered configuration-source facts without probing or mutation."""

from __future__ import annotations

from ..domain.registered_sources import RegisteredSourcesSnapshot
from .registered_source_ports import (
    RegisteredSourcesAuthorityUnavailable,
    RegisteredSourcesReader,
)


class ReadRegisteredSources:
    """Delegate the registry read to its authoritative host-owned provider."""

    def __init__(self, reader: RegisteredSourcesReader) -> None:
        self._reader = reader

    async def execute(self) -> RegisteredSourcesSnapshot:
        """Return persisted safe facts; do not infer health or credentials."""
        snapshot = await self._reader.read_registered_sources()
        if not isinstance(snapshot, RegisteredSourcesSnapshot):
            raise RegisteredSourcesAuthorityUnavailable(
                "source registry authority returned an invalid snapshot"
            )
        return snapshot

