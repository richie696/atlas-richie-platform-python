"""Consumer-owned read boundary for persisted registered-source facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..domain.registered_sources import RegisteredSourcesSnapshot

if TYPE_CHECKING:
    from .check_registered_source import (
        RegisteredSourceCheckResult,
        SourceConnectionInput,
    )


@dataclass(frozen=True, slots=True)
class RegisteredSourceProbe:
    """Latest bounded probe fact tied to one exact registered-source revision."""

    source_id: str
    revision: str
    result: RegisteredSourceCheckResult


class RegisteredSourcesReader(Protocol):
    """Read safe source-registry facts from the control-plane authority."""

    async def read_registered_sources(self) -> RegisteredSourcesSnapshot:
        """Return the current bounded registry snapshot."""


class RegisteredSourcesAuthorityUnavailable(RuntimeError):
    """The authoritative source registry cannot provide a trustworthy snapshot."""


class RegisteredSourceProbeRecorder(Protocol):
    """Persist a probe only when the checked input still matches its source."""

    async def record_registered_source_probe(
        self,
        command: SourceConnectionInput,
        result: RegisteredSourceCheckResult,
    ) -> bool:
        """Return false when registration/revision no longer matches the probe."""


class RegisteredSourceProbeReader(Protocol):
    """Read the most recent safe probe facts for the current source snapshot."""

    async def read_registered_source_probes(
        self, sources: tuple[tuple[str, str], ...]
    ) -> tuple[RegisteredSourceProbe, ...]:
        """Return probes for matching ``(source_id, revision)`` pairs only."""


class RegisteredSourceProbeAuthorityUnavailable(RuntimeError):
    """The SQL authority cannot safely persist or read source probe facts."""
