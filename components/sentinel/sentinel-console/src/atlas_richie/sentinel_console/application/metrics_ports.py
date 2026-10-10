"""Consumer-owned authority boundary for metric query reads."""

from __future__ import annotations

from typing import Protocol

from ..domain.instance_observation import MetricBundle, MetricQuery


class MetricsReader(Protocol):
    """Read one exact, potentially fleet-wide metrics selection and time window."""

    async def read_metrics(self, query: MetricQuery) -> MetricBundle:
        """Return one strict summary/series bundle for the requested metrics."""
