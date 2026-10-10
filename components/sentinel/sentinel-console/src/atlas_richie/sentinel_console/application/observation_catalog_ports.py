"""Consumer-owned boundary for authoritative observation catalog reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.observation_catalog import ObservationCatalogSnapshot


class ObservationCatalogReader(Protocol):
    """Read environment and application identities from the host authority."""

    async def read_observation_catalog(self) -> ObservationCatalogSnapshot:
        """Return confirmed catalog facts without inventing demo entries."""


class ObservationCatalogAuthorityUnavailable(RuntimeError):
    """The host cannot provide a trustworthy observation catalog snapshot."""
