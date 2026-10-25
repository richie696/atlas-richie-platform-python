"""SQL Adapter for the authenticated Metrics V2 observation catalog."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ...application.observation_catalog_ports import (
    ObservationCatalogAuthorityUnavailable,
    ObservationCatalogReader,
)
from ...domain.observation_catalog import (
    MAX_OBSERVATION_CATALOG_ITEMS,
    ObservationApplication,
    ObservationCatalogSnapshot,
    ObservationEnvironment,
)
from .models import MetricsReporterBindingRecord, MonitoringSourceRecord


class SQLAlchemyMetricsObservationCatalogReader(ObservationCatalogReader):
    """Project active Reporter bindings with durable snapshots into selectors."""

    def __init__(
        self,
        engine_resolver: Callable[[], Awaitable[AsyncEngine]],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine_resolver = engine_resolver
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_observation_catalog(self) -> ObservationCatalogSnapshot:
        """Return only scopes confirmed by a non-revoked accepted Reporter."""
        as_of = self._clock()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("catalog clock must return an aware instant")
        as_of = as_of.astimezone(UTC)
        try:
            engine = await self._engine_resolver()
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                scopes = tuple(
                    await session.execute(
                        select(
                            MetricsReporterBindingRecord.environment_id,
                            MetricsReporterBindingRecord.app_id,
                        )
                        .where(
                            MetricsReporterBindingRecord.revoked_at.is_(None),
                            MetricsReporterBindingRecord.current_epoch.is_not(None),
                            MetricsReporterBindingRecord.last_received_at.is_not(None),
                        )
                        .distinct()
                        .order_by(
                            MetricsReporterBindingRecord.environment_id,
                            MetricsReporterBindingRecord.app_id,
                        )
                        .limit(MAX_OBSERVATION_CATALOG_ITEMS + 1)
                    )
                )
                monitoring_environment_ids = tuple(
                    await session.scalars(
                        select(MonitoringSourceRecord.environment_id)
                        .distinct()
                        .order_by(MonitoringSourceRecord.environment_id)
                        .limit(MAX_OBSERVATION_CATALOG_ITEMS + 1)
                    )
                )
        except SQLAlchemyError:
            raise ObservationCatalogAuthorityUnavailable(
                "observation catalog authority is unavailable"
            ) from None

        if (
            len(scopes) > MAX_OBSERVATION_CATALOG_ITEMS
            or len(monitoring_environment_ids) > MAX_OBSERVATION_CATALOG_ITEMS
        ):
            raise ObservationCatalogAuthorityUnavailable(
                "observation catalog exceeds its configured bound"
            )

        environment_ids = tuple(
            sorted(
                {environment_id for environment_id, _ in scopes}
                | set(monitoring_environment_ids)
            )
        )
        if len(environment_ids) > MAX_OBSERVATION_CATALOG_ITEMS:
            raise ObservationCatalogAuthorityUnavailable(
                "observation catalog exceeds its configured bound"
            )
        applications = tuple(
            ObservationApplication(
                id=app_id,
                environment_id=environment_id,
                name=app_id,
            )
            for environment_id, app_id in scopes
        )
        try:
            return ObservationCatalogSnapshot(
                as_of=as_of,
                environments=tuple(
                    ObservationEnvironment(id=item, name=item)
                    for item in environment_ids
                ),
                applications=applications,
            )
        except ValueError:
            raise ObservationCatalogAuthorityUnavailable(
                "observation catalog authority returned invalid identities"
            ) from None


__all__ = ["SQLAlchemyMetricsObservationCatalogReader"]
