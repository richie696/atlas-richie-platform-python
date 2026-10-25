"""Explicit metric authority for deployments without Agent ingestion."""

from __future__ import annotations

from datetime import UTC, datetime

from ..application.metrics_ports import MetricsReader
from ..domain.instance_catalog import (
    METRIC_DENOMINATORS,
    METRIC_UNITS,
    MetricQuality,
    MetricReading,
    ObservationCoverage,
)
from ..domain.instance_observation import (
    MetricBundle,
    MetricQuery,
    MetricSeries,
)

_UNAVAILABLE_METRIC_SOURCE_ID = "not-integrated"


class UnavailableMetricsReader(MetricsReader):
    """Return explicit unintegrated metric facts without inventing samples.

    This reader is used only by the SQL Console composition when no host-owned
    metrics authority is supplied. It reports unknown coverage, zero reporters,
    null summary values, and empty series; the generic ``build_app`` boundary
    continues to return service-unavailable when no reader is configured.
    """

    async def read_metrics(self, query: MetricQuery) -> MetricBundle:
        """Return the requested metrics as unavailable for the exact query."""
        coverage = ObservationCoverage(
            expected=None,
            inventory_source=None,
            reporting=0,
        )
        summary: list[MetricReading] = []
        series: list[MetricSeries] = []

        for metric in query.metrics:
            unit = METRIC_UNITS[metric]
            denominator = METRIC_DENOMINATORS[metric]
            summary.append(
                MetricReading(
                    source=_UNAVAILABLE_METRIC_SOURCE_ID,
                    denominator=denominator,
                    coverage=coverage,
                    quality=MetricQuality.NOT_INTEGRATED,
                    metric=metric,
                    unit=unit,
                    value=None,
                    sampled_at=None,
                )
            )
            series.append(
                MetricSeries(
                    source=_UNAVAILABLE_METRIC_SOURCE_ID,
                    denominator=denominator,
                    coverage=coverage,
                    quality=MetricQuality.NOT_INTEGRATED,
                    metric=metric,
                    unit=unit,
                    samples=(),
                )
            )

        return MetricBundle(
            query=query,
            as_of=datetime.now(UTC),
            summary=tuple(summary),
            series=tuple(series),
            annotations=(),
        )
