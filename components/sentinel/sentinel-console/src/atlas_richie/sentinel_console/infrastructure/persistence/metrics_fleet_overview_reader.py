"""SQL Adapter projecting authenticated Reporter facts into Fleet overview."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ...application.fleet_overview_ports import (
    FleetOverviewAuthorityUnavailable,
    FleetOverviewReader,
    FleetOverviewTargetNotFound,
)
from ...application.instance_catalog_ports import InstanceCatalogAuthorityUnavailable
from ...application.metrics_ports import MetricsReader
from ...domain.fleet_overview import (
    FleetApplication,
    FleetApplicationHealth,
    FleetApplicationPage,
    FleetQuery,
    FleetSnapshot,
)
from ...domain.instance_catalog import (
    ObservationCoverage,
    ObservationScope,
    is_aware_instant,
)
from ...domain.observation_catalog import MAX_OBSERVATION_CATALOG_ITEMS
from .models import MetricsReporterBindingRecord

_REPORTER_STALE_AFTER = timedelta(seconds=3)
_MAX_METRIC_READS = 8


class SQLAlchemyMetricsFleetOverviewReader(FleetOverviewReader):
    """Build a bounded Fleet snapshot from Reporter bindings and Metrics V2 history.

    Application health and rule coverage are intentionally unknown: Reporter
    freshness is not an application health probe, and rule receipts are owned
    by the separate publication-receipt read model.
    """

    def __init__(
        self,
        engine_resolver: Callable[[], Awaitable[AsyncEngine]],
        metrics_reader: MetricsReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine_resolver = engine_resolver
        self._metrics_reader = metrics_reader
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_fleet_overview(self, query: FleetQuery) -> FleetSnapshot:
        """Return authoritative reporter scope and metrics for the exact query."""
        if not isinstance(query, FleetQuery):
            raise TypeError("fleet query is required")
        as_of = self._clock()
        if not is_aware_instant(as_of):
            raise ValueError("fleet overview clock must return an aware instant")
        as_of = as_of.astimezone(UTC)

        try:
            (
                applications,
                total_applications,
                filtered_applications,
                fresh_reporters,
            ) = await self._read_application_directory(query, as_of)
        except SQLAlchemyError:
            raise FleetOverviewAuthorityUnavailable(
                "fleet overview authority is unavailable"
            ) from None

        if query.context.app_id is not None and total_applications == 0:
            raise FleetOverviewTargetNotFound("fleet application is not registered")

        metric_reader = self._metrics_reader
        try:
            metrics = await metric_reader.read_metrics(query.metric_query)
            metrics = replace(metrics, as_of=as_of)
            selected = applications[
                (query.page - 1) * query.page_size : query.page * query.page_size
            ]
            application_rows = await self._read_application_metrics(
                query, selected, as_of
            )
        except InstanceCatalogAuthorityUnavailable:
            raise FleetOverviewAuthorityUnavailable(
                "fleet metrics authority is unavailable"
            ) from None
        except SQLAlchemyError:
            raise FleetOverviewAuthorityUnavailable(
                "fleet metrics authority is unavailable"
            ) from None

        return FleetSnapshot(
            query=query,
            as_of=as_of,
            coverage=ObservationCoverage(None, None, fresh_reporters),
            total_applications=total_applications,
            attention_applications=0,
            attention_targets=(),
            applications=FleetApplicationPage(
                items=application_rows,
                total=filtered_applications,
                page=query.page,
                page_size=query.page_size,
            ),
            metrics=metrics,
            connections=(),
        )

    async def _read_application_directory(
        self, query: FleetQuery, as_of: datetime
    ) -> tuple[tuple[tuple[str, int], ...], int, int, int]:
        stale_after = as_of - _REPORTER_STALE_AFTER
        is_fresh = and_(
            MetricsReporterBindingRecord.last_received_at >= stale_after,
            MetricsReporterBindingRecord.last_received_at <= as_of,
        )
        filters = (
            MetricsReporterBindingRecord.environment_id == query.context.environment_id,
            MetricsReporterBindingRecord.revoked_at.is_(None),
            MetricsReporterBindingRecord.current_epoch.is_not(None),
            MetricsReporterBindingRecord.last_received_at.is_not(None),
        )
        statement = select(
            MetricsReporterBindingRecord.app_id,
            func.sum(case((is_fresh, 1), else_=0)),
        ).where(*filters)
        statement = (
            statement.group_by(MetricsReporterBindingRecord.app_id)
            .order_by(MetricsReporterBindingRecord.app_id)
            .limit(MAX_OBSERVATION_CATALOG_ITEMS + 1)
        )

        engine = await self._engine_resolver()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            rows = tuple((await session.execute(statement)).all())
        if len(rows) > MAX_OBSERVATION_CATALOG_ITEMS:
            raise FleetOverviewAuthorityUnavailable(
                "fleet application inventory exceeds its configured bound"
            )
        all_values = tuple(
            (app_id, int(fresh_count or 0)) for app_id, fresh_count in rows
        )
        scoped_values = tuple(
            item
            for item in all_values
            if query.context.app_id is None or item[0] == query.context.app_id
        )
        search = query.search.strip().casefold()
        filtered_values = (
            tuple(item for item in scoped_values if search in item[0].casefold())
            if search
            else scoped_values
        )
        return (
            filtered_values,
            len(scoped_values),
            len(filtered_values),
            sum(fresh_count for _app_id, fresh_count in scoped_values),
        )

    async def _read_application_metrics(
        self,
        query: FleetQuery,
        applications: tuple[tuple[str, int], ...],
        as_of: datetime,
    ) -> tuple[FleetApplication, ...]:
        semaphore = asyncio.Semaphore(_MAX_METRIC_READS)

        async def read_application(
            app_id: str, fresh_reporters: int
        ) -> FleetApplication:
            context = replace(
                query.context,
                app_id=app_id,
                scope=ObservationScope.APPLICATION,
            )
            metric_query = replace(query.metric_query, context=context)
            async with semaphore:
                bundle = await self._metrics_reader.read_metrics(metric_query)
            bundle = replace(bundle, as_of=as_of)
            return FleetApplication(
                app_id=app_id,
                name=app_id,
                health=FleetApplicationHealth.UNKNOWN,
                instance_coverage=ObservationCoverage(None, None, fresh_reporters),
                rule_coverage=ObservationCoverage(None, None, 0),
                metrics=bundle.summary,
            )

        return tuple(
            await asyncio.gather(
                *(
                    read_application(app_id, fresh_reporters)
                    for app_id, fresh_reporters in applications
                )
            )
        )


__all__ = ["SQLAlchemyMetricsFleetOverviewReader"]
