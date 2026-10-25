"""Read an exact, query-bound instance catalog snapshot."""

from __future__ import annotations

from ..domain.instance_catalog import InstanceCatalogQuery, InstanceCatalogSnapshot
from .instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceCatalogReader,
)


class ReadInstanceCatalog:
    """Delegate to the host authority and reject mismatched query snapshots."""

    def __init__(self, reader: InstanceCatalogReader) -> None:
        self._reader = reader

    async def execute(self, query: InstanceCatalogQuery) -> InstanceCatalogSnapshot:
        snapshot = await self._reader.read_instance_catalog(query)
        if not isinstance(snapshot, InstanceCatalogSnapshot) or snapshot.query != query:
            raise InstanceCatalogAuthorityUnavailable(
                "instance catalog authority returned an invalid query snapshot"
            )
        return snapshot
