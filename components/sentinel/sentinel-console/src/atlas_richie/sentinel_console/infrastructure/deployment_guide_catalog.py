"""Versioned, immutable deployment guide catalog for the Console release."""

from __future__ import annotations

from ..application.deployment_guides import (
    DeploymentGuidePath,
    DeploymentGuideId,
    DeploymentGuideReadiness,
    DeploymentGuidesSnapshot,
)


class StaticDeploymentGuideCatalog:
    """Provide only paths whose content/readiness is owned by this Console build.

    Linux and Kubernetes paths deliberately remain ``guide-only`` until their
    install artifacts have pinned dependencies and passed their own validation.
    This catalog does not claim that a collector is installed or reachable.
    """

    def __init__(self, runtime_collector_endpoint: str | None = None) -> None:
        self._runtime_collector_endpoint = runtime_collector_endpoint

    async def read_deployment_guides(self) -> DeploymentGuidesSnapshot:
        return DeploymentGuidesSnapshot(
            catalog_revision="2026-10-17.1",
            runtime_collector_endpoint=self._runtime_collector_endpoint,
            paths=(
                DeploymentGuidePath(
                    DeploymentGuideId.EXISTING,
                    DeploymentGuideReadiness.CONFIGURATION_REQUIRED,
                    None,
                ),
                DeploymentGuidePath(
                    DeploymentGuideId.LINUX,
                    DeploymentGuideReadiness.GUIDE_ONLY,
                    None,
                ),
                DeploymentGuidePath(
                    DeploymentGuideId.KUBERNETES,
                    DeploymentGuideReadiness.GUIDE_ONLY,
                    None,
                ),
            ),
        )


__all__ = ["StaticDeploymentGuideCatalog"]
