"""Read the Console-owned deployment guidance facts used by onboarding UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from ..domain.wire_strings import is_bounded_wire_identifier


class DeploymentGuideId(StrEnum):
    """Finite onboarding choices shared by the current server catalog."""

    EXISTING = "existing"
    LINUX = "linux"
    KUBERNETES = "kubernetes"


class DeploymentGuideReadiness(StrEnum):
    """Readiness is deliberately distinct from whether a guide can be viewed."""

    CONFIGURATION_REQUIRED = "configuration-required"
    GUIDE_ONLY = "guide-only"


@dataclass(frozen=True, slots=True)
class DeploymentGuidePath:
    """One supported onboarding path and its current server-owned readiness."""

    guide_id: DeploymentGuideId
    readiness: DeploymentGuideReadiness
    profile_revision: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.guide_id, DeploymentGuideId):
            raise ValueError("deployment guide id is unsupported")
        if not isinstance(self.readiness, DeploymentGuideReadiness):
            raise ValueError("deployment guide readiness is unsupported")
        if self.profile_revision is not None and not is_bounded_wire_identifier(
            self.profile_revision, 64
        ):
            raise ValueError("deployment profile revision is invalid")


@dataclass(frozen=True, slots=True)
class DeploymentGuidesSnapshot:
    """Credential-free facts; absent public endpoints remain explicitly absent."""

    catalog_revision: str
    runtime_collector_endpoint: str | None
    paths: tuple[DeploymentGuidePath, ...]

    def __post_init__(self) -> None:
        if not is_bounded_wire_identifier(self.catalog_revision, 64):
            raise ValueError("deployment guide catalog revision is invalid")
        if self.runtime_collector_endpoint is not None:
            endpoint = self.runtime_collector_endpoint
            try:
                parsed = urlsplit(endpoint)
                port = parsed.port
            except (TypeError, ValueError):
                raise ValueError("advertised runtime Collector endpoint is invalid") from None
            if (
                not isinstance(endpoint, str)
                or len(endpoint) > 512
                or endpoint != endpoint.strip()
                or parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or (port is not None and not 1 <= port <= 65535)
            ):
                raise ValueError("advertised runtime Collector endpoint is invalid")
        if not isinstance(self.paths, tuple) or len(self.paths) > 3:
            raise ValueError("deployment guide paths are invalid")
        if any(not isinstance(path, DeploymentGuidePath) for path in self.paths):
            raise ValueError("deployment guide path is invalid")
        if len({path.guide_id for path in self.paths}) != len(self.paths):
            raise ValueError("deployment guide ids must be unique")


class DeploymentGuidesReader(Protocol):
    """Consumer-owned source of supported profiles and explicit deployment facts."""

    async def read_deployment_guides(self) -> DeploymentGuidesSnapshot:
        """Return the immutable guide catalog without inferring network addresses."""


class DeploymentGuidesAuthorityUnavailable(RuntimeError):
    """The deployment profile authority could not provide trustworthy facts."""


class ReadDeploymentGuides:
    """Read the deployment catalog through its application-owned port."""

    def __init__(self, reader: DeploymentGuidesReader) -> None:
        self._reader = reader

    async def execute(self) -> DeploymentGuidesSnapshot:
        snapshot = await self._reader.read_deployment_guides()
        if not isinstance(snapshot, DeploymentGuidesSnapshot):
            raise DeploymentGuidesAuthorityUnavailable(
                "deployment guide authority returned an invalid snapshot"
            )
        return snapshot


__all__ = [
    "DeploymentGuidePath",
    "DeploymentGuideId",
    "DeploymentGuideReadiness",
    "DeploymentGuidesAuthorityUnavailable",
    "DeploymentGuidesReader",
    "DeploymentGuidesSnapshot",
    "ReadDeploymentGuides",
]
