"""Consumer-owned boundary for authorized, paged instance observations."""

from __future__ import annotations

from typing import Protocol

from ..domain.instance_catalog import InstanceCatalogQuery, InstanceCatalogSnapshot
from ..domain.instance_observation import InstanceDetailQuery, InstanceObservation


class InstanceCatalogReader(Protocol):
    """Read one exact query from the configured instance/telemetry authority."""

    async def read_instance_catalog(
        self, query: InstanceCatalogQuery
    ) -> InstanceCatalogSnapshot:
        """Return the bounded page and whole-population counters for the query."""


class InstanceObservationReader(Protocol):
    """Read one exact process incarnation and requested collection scope."""

    async def read_instance_observation(
        self, query: InstanceDetailQuery
    ) -> InstanceObservation:
        """Return current identity, scoped metrics, and aligned management facts."""


class InstanceCatalogAuthorityUnavailable(RuntimeError):
    """No trustworthy inventory/telemetry snapshot can be served."""


class InstanceCatalogTargetNotFound(LookupError):
    """The requested environment or scoped target is not registered."""


class InstanceIncarnationRetired(LookupError):
    """The instance ID exists, but the requested process epoch is no longer current."""


class InstanceCatalogRateLimited(RuntimeError):
    """The observation authority cannot serve the query within its rate budget."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or retry_after_ms < 0:
            raise ValueError("retry delay must be a non-negative integer")
        self.retry_after_ms = retry_after_ms
        super().__init__("instance catalog query rate limited")
