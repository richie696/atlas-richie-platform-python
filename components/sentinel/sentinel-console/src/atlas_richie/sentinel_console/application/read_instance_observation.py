"""Read one exact instance incarnation and validate its scoped response."""

from __future__ import annotations

from .instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceObservationReader,
)
from ..domain.instance_observation import InstanceDetailQuery, InstanceObservation


class ReadInstanceObservation:
    """Delegate detail reads to the configured inventory/telemetry authority."""

    def __init__(self, reader: InstanceObservationReader) -> None:
        self._reader = reader

    async def execute(self, query: InstanceDetailQuery) -> InstanceObservation:
        observation = await self._reader.read_instance_observation(query)
        if (
            not isinstance(observation, InstanceObservation)
            or observation.query != query
        ):
            raise InstanceCatalogAuthorityUnavailable(
                "instance observation authority returned an invalid query snapshot"
            )
        return observation
