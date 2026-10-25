"""Read the host-owned catalog used by dashboard observation filters."""

from __future__ import annotations

from ..domain.observation_catalog import ObservationCatalogSnapshot
from .observation_catalog_ports import (
    ObservationCatalogAuthorityUnavailable,
    ObservationCatalogReader,
)


class ReadObservationCatalog:
    """Delegate the catalog query without adding local fallback data."""

    def __init__(self, reader: ObservationCatalogReader) -> None:
        self._reader = reader

    async def execute(self) -> ObservationCatalogSnapshot:
        """Return the current catalog facts from their configured authority."""
        snapshot = await self._reader.read_observation_catalog()
        if not isinstance(snapshot, ObservationCatalogSnapshot):
            raise ObservationCatalogAuthorityUnavailable(
                "catalog authority returned an invalid snapshot"
            )
        return snapshot
