"""Report independently sourced protocol boundaries as unknown when unattached."""

from __future__ import annotations

from datetime import UTC, datetime

from ..application.system_protocols_ports import SystemProtocolsReader
from ..domain.system_protocols import (
    ProtocolBoundary,
    ProtocolCompatibility,
    ProtocolObservation,
    SystemProtocolsSnapshot,
)


class UnobservedSystemProtocolsReader(SystemProtocolsReader):
    """Do not infer rule-source or token compatibility without their peer authority."""

    async def read_system_protocols(self) -> SystemProtocolsSnapshot:
        """Return only explicitly unknown independent boundaries."""
        return SystemProtocolsSnapshot(
            as_of=datetime.now(UTC),
            items=(
                _unknown(ProtocolBoundary.RULE_CONFIG),
                _unknown(ProtocolBoundary.CLUSTER_TOKEN),
            ),
        )


def _unknown(boundary: ProtocolBoundary) -> ProtocolObservation:
    return ProtocolObservation(
        kind=boundary,
        supported=(),
        active=None,
        compatibility=ProtocolCompatibility.UNKNOWN,
        observed_at=None,
    )


__all__ = ["UnobservedSystemProtocolsReader"]
