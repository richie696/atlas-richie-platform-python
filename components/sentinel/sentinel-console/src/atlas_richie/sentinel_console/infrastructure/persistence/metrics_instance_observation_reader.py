"""SQL composition for incarnation-bound instance detail reads."""

from __future__ import annotations

from datetime import datetime

from ...application.instance_catalog_ports import (
    InstanceCatalogAuthorityUnavailable,
    InstanceCatalogReader,
    InstanceCatalogTargetNotFound,
    InstanceIncarnationRetired,
    InstanceObservationReader,
)
from ...application.metrics_ports import MetricsReader
from ...domain.instance_catalog import (
    OPERATIONAL_METRIC_NAMES,
    InstanceCatalogQuery,
    ObservationScope,
    ObservedInstance,
)
from ...domain.instance_observation import (
    InstanceDetailQuery,
    InstanceObservation,
    MetricQuery,
)

_MAX_INSTANCE_MATCHES = 100


class SQLAlchemyMetricsInstanceObservationReader(InstanceObservationReader):
    """Join the current SQL-backed instance identity with its scoped metrics.

    The reader uses the authoritative directory before and after the metric
    query. This detects an instance restart that races the read and prevents a
    response from pairing one process epoch with another epoch's measurements.
    """

    def __init__(
        self,
        *,
        catalog_reader: InstanceCatalogReader,
        metrics_reader: MetricsReader,
    ) -> None:
        if catalog_reader is None or metrics_reader is None:
            raise TypeError("instance detail requires catalog and metrics readers")
        self._catalog_reader = catalog_reader
        self._metrics_reader = metrics_reader

    async def read_instance_observation(
        self, query: InstanceDetailQuery
    ) -> InstanceObservation:
        """Read one current process incarnation without borrowing another scope."""
        if not isinstance(query, InstanceDetailQuery):
            raise TypeError("instance detail query is required")

        initial = await self._read_exact_instance(query)
        metrics = None
        as_of = initial[0]
        if query.scope in initial[1].supported_scopes:
            metric_query = MetricQuery(
                context=query.context,
                metrics=OPERATIONAL_METRIC_NAMES,
                step_ms=query.step_ms,
            )
            metrics = await self._metrics_reader.read_metrics(metric_query)
            if getattr(metrics, "query", None) != metric_query:
                raise InstanceCatalogAuthorityUnavailable(
                    "instance metrics authority returned a mismatched query"
                )
            as_of = metrics.as_of

        current = await self._read_exact_instance(query)
        if current[1].process_epoch != initial[1].process_epoch:
            raise InstanceIncarnationRetired(
                "instance process incarnation changed during the read"
            )
        return InstanceObservation(
            query=query,
            as_of=as_of,
            instance=current[1],
            metrics=metrics,
        )

    async def _read_exact_instance(
        self, query: InstanceDetailQuery
    ) -> tuple[datetime, ObservedInstance]:
        catalog = await self._catalog_reader.read_instance_catalog(
            InstanceCatalogQuery(
                environment_id=query.environment_id,
                app_id=query.app_id,
                instance_id=None,
                resource=None,
                scope=ObservationScope.APPLICATION,
                window=query.window,
                page=1,
                page_size=_MAX_INSTANCE_MATCHES,
                search=query.instance_id,
                attention_only=False,
            )
        )
        matches = tuple(
            item for item in catalog.items if item.instance_id == query.instance_id
        )
        if len(matches) > 1:
            raise InstanceCatalogAuthorityUnavailable(
                "instance directory returned duplicate target identities"
            )
        if not matches:
            if catalog.filtered_total > len(catalog.items):
                raise InstanceCatalogAuthorityUnavailable(
                    "instance directory target page is incomplete"
                )
            raise InstanceCatalogTargetNotFound("instance target is not registered")
        instance = matches[0]
        if instance.process_epoch != query.process_epoch:
            raise InstanceIncarnationRetired(
                "requested process incarnation is no longer current"
            )
        return catalog.as_of, instance


__all__ = ["SQLAlchemyMetricsInstanceObservationReader"]
