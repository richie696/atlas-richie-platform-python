"""Read a query-bound metric summary, series, and annotations bundle."""

from __future__ import annotations

from ..domain.instance_observation import MetricBundle, MetricQuery
from .instance_catalog_ports import InstanceCatalogAuthorityUnavailable
from .metrics_ports import MetricsReader


class ReadMetrics:
    """Delegate generic scope/window queries to an injected observation authority."""

    def __init__(self, reader: MetricsReader) -> None:
        self._reader = reader

    async def execute(self, query: MetricQuery) -> MetricBundle:
        bundle = await self._reader.read_metrics(query)
        if not isinstance(bundle, MetricBundle) or bundle.query != query:
            raise InstanceCatalogAuthorityUnavailable(
                "metrics authority returned an invalid query bundle"
            )
        return bundle
