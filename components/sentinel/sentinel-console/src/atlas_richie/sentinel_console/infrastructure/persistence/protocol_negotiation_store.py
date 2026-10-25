"""SQL Adapter for authenticated Agent Reporting protocol facts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.metrics_ingest_ports import VerifiedMetricsPeer
from ...application.negotiate_agent_reporting import (
    ProtocolNegotiationIdentityUnavailable,
    ProtocolNegotiationUnavailable,
)
from ...application.protocol_negotiation_ports import (
    ProtocolNegotiationStore,
    RuleLoadObservationNegotiationStore,
)
from ...domain.protocol_negotiations import (
    AGENT_REPORTING_V1,
    INCIDENT_EVENTS_V1,
    NegotiatedCompatibility,
    ProtocolNegotiation,
    ProtocolNegotiationPage,
)
from .models import (
    AgentReportingNegotiationRecord,
    IncidentEventNegotiationRecord,
    MetricsReporterBindingRecord,
    RuleLoadObservationNegotiationRecord,
)


class SQLAlchemyProtocolNegotiationStore(
    ProtocolNegotiationStore, RuleLoadObservationNegotiationStore
):
    """Persist negotiation facts in the selected SQLite, PostgreSQL, or MySQL DB."""

    def __init__(self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]) -> None:
        self._engine_resolver = engine_resolver

    async def _sessions(self) -> async_sessionmaker[AsyncSession]:
        engine = await self._engine_resolver()
        return async_sessionmaker(engine, expire_on_commit=False)

    async def accept_agent_reporting_negotiation(
        self,
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Commit latest handshake before allowing a response to be returned."""
        return await self._accept_negotiation(
            AgentReportingNegotiationRecord,
            peer,
            runtime_version=runtime_version,
            collector_supported=collector_supported,
            compatibility=compatibility,
            observed_at=observed_at,
        )

    async def accept_incident_event_negotiation(
        self,
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Commit Incident Event facts in their independent protocol table."""
        return await self._accept_negotiation(
            IncidentEventNegotiationRecord,
            peer,
            runtime_version=runtime_version,
            collector_supported=collector_supported,
            compatibility=compatibility,
            observed_at=observed_at,
        )

    async def accept_rule_load_observation_negotiation(
        self,
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Persist Rule Load Observation independently from other boundaries."""
        return await self._accept_negotiation(
            RuleLoadObservationNegotiationRecord,
            peer,
            runtime_version=runtime_version,
            collector_supported=collector_supported,
            compatibility=compatibility,
            observed_at=observed_at,
        )

    async def _accept_negotiation(
        self,
        record_type: type[
            AgentReportingNegotiationRecord
            | IncidentEventNegotiationRecord
            | RuleLoadObservationNegotiationRecord
        ],
        peer: VerifiedMetricsPeer,
        *,
        runtime_version: str,
        collector_supported: tuple[str, ...],
        compatibility: NegotiatedCompatibility,
        observed_at: datetime,
    ) -> ProtocolNegotiation:
        """Persist a protocol-specific observation before its HTTP response."""
        try:
            sessions = await self._sessions()
            async with sessions.begin() as session:
                binding = await session.scalar(
                    select(MetricsReporterBindingRecord)
                    .where(
                        MetricsReporterBindingRecord.certificate_sha256
                        == peer.certificate_sha256,
                        MetricsReporterBindingRecord.revoked_at.is_(None),
                    )
                    .with_for_update()
                )
                if binding is None:
                    raise ProtocolNegotiationIdentityUnavailable(
                        "reporter identity unavailable"
                    )
                record = await session.get(record_type, binding.certificate_principal)
                if record is None:
                    session.add(
                        record_type(
                            certificate_principal=binding.certificate_principal,
                            runtime_version=runtime_version,
                            collector_supported=list(collector_supported),
                            compatibility=compatibility.value,
                            observed_at=observed_at,
                        )
                    )
                else:
                    record.runtime_version = runtime_version
                    record.collector_supported = list(collector_supported)
                    record.compatibility = compatibility.value
                    record.observed_at = observed_at
                return ProtocolNegotiation(
                    certificate_principal=binding.certificate_principal,
                    reporter_id=binding.reporter_id,
                    environment_id=binding.environment_id,
                    app_id=binding.app_id,
                    instance_id=binding.instance_id,
                    process_id=binding.process_id,
                    runtime_version=runtime_version,
                    collector_supported=collector_supported,
                    compatibility=compatibility,
                    observed_at=observed_at,
                )
        except ProtocolNegotiationUnavailable:
            raise
        except IntegrityError:
            # A concurrent first handshake wins; caller safely retries the same hello.
            raise ProtocolNegotiationUnavailable("negotiation write conflict") from None
        except SQLAlchemyError:
            raise ProtocolNegotiationUnavailable(
                "negotiation storage unavailable"
            ) from None

    async def read_agent_reporting_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        """Join active enrolled workers with their last durable negotiation."""
        return await self._read_negotiations(
            AgentReportingNegotiationRecord,
            AGENT_REPORTING_V1,
            page=page,
            page_size=page_size,
            as_of=as_of,
        )

    async def read_incident_event_negotiations(
        self, *, page: int, page_size: int, as_of: datetime
    ) -> ProtocolNegotiationPage:
        """Read Incident Event facts independently from Agent Reporting."""
        return await self._read_negotiations(
            IncidentEventNegotiationRecord,
            INCIDENT_EVENTS_V1,
            page=page,
            page_size=page_size,
            as_of=as_of,
        )

    async def _read_negotiations(
        self,
        record_type: type[
            AgentReportingNegotiationRecord | IncidentEventNegotiationRecord
        ],
        default_supported_version: str,
        *,
        page: int,
        page_size: int,
        as_of: datetime,
    ) -> ProtocolNegotiationPage:
        """Join one selected protocol's facts to current Reporter enrollment."""
        try:
            sessions = await self._sessions()
            async with sessions() as session:
                conditions = MetricsReporterBindingRecord.revoked_at.is_(None)
                total = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(MetricsReporterBindingRecord)
                        .where(conditions)
                    )
                    or 0
                )
                rows = (
                    await session.execute(
                        select(
                            MetricsReporterBindingRecord,
                            record_type,
                        )
                        .outerjoin(
                            record_type,
                            record_type.certificate_principal
                            == MetricsReporterBindingRecord.certificate_principal,
                        )
                        .where(conditions)
                        .order_by(
                            MetricsReporterBindingRecord.environment_id,
                            MetricsReporterBindingRecord.app_id,
                            MetricsReporterBindingRecord.instance_id,
                        )
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                ).all()
        except SQLAlchemyError:
            raise ProtocolNegotiationUnavailable(
                "negotiation storage unavailable"
            ) from None

        items = tuple(
            _observation(binding, negotiation, default_supported_version)
            for binding, negotiation in rows
        )
        return ProtocolNegotiationPage(
            as_of=as_of.astimezone(UTC),
            page=page,
            page_size=page_size,
            total=total,
            items=items,
        )


def _observation(
    binding: MetricsReporterBindingRecord,
    record: AgentReportingNegotiationRecord | IncidentEventNegotiationRecord | None,
    default_supported_version: str,
) -> ProtocolNegotiation:
    observed_at = _aware_utc(record.observed_at) if record is not None else None
    versions = (
        tuple(record.collector_supported)
        if record is not None
        else (default_supported_version,)
    )
    compatibility = (
        NegotiatedCompatibility(record.compatibility)
        if record is not None
        else NegotiatedCompatibility.UNKNOWN
    )
    return ProtocolNegotiation(
        certificate_principal=binding.certificate_principal,
        reporter_id=binding.reporter_id,
        environment_id=binding.environment_id,
        app_id=binding.app_id,
        instance_id=binding.instance_id,
        process_id=binding.process_id,
        runtime_version=record.runtime_version if record is not None else None,
        collector_supported=versions,
        compatibility=compatibility,
        observed_at=observed_at,
    )


def _aware_utc(value: datetime) -> datetime:
    """Normalize UTC values returned naive by SQLite's timezone-less storage."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SQLAlchemyProtocolNegotiationStore"]
