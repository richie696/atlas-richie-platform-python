"""SQL adapter for authenticated Rule Load Observation V1 acceptance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from atlas_richie.contracts.rules.load_observation.v1 import RuleLoadObservationV1
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.metrics_ingest_ports import VerifiedMetricsPeer
from ...application.rule_load_observation_ingest_ports import (
    RuleLoadObservationInboxPort,
    RuleLoadObservationIngestError,
)
from ...application.rule_load_observation_ingest_ports import (
    RuleLoadObservationIngestErrorCode as ErrorCode,
)
from .models import (
    MetricsReporterBindingRecord,
    RuleBindingRecord,
    RuleLoadObservationInboxRecord,
    RuleLoadObservationOutboxRecord,
    RuleLoadObservationSequenceRecord,
)


class SQLAlchemyRuleLoadObservationInbox(RuleLoadObservationInboxPort):
    """Commit validated observations and projection work atomically."""

    def __init__(
        self, engine_resolver: Callable[[], Awaitable[AsyncEngine]]
    ) -> None:
        self._engine_resolver = engine_resolver

    async def accept(
        self,
        *,
        peer: VerifiedMetricsPeer,
        observation: RuleLoadObservationV1,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> None:
        if hashlib.sha256(body).hexdigest() != body_sha256 or not _is_utc(received_at):
            raise ValueError("observation digest or receive time is invalid")
        canonical_body = json.loads(body.decode("utf-8"))
        received_at = received_at.astimezone(UTC)
        try:
            engine = await self._engine_resolver()
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions.begin() as session:
                reporter = await self._lock_enrollment(session, peer)
                if reporter is None:
                    raise RuleLoadObservationIngestError(
                        ErrorCode.IDENTITY_NOT_ENROLLED
                    )
                if reporter.revoked_at is not None:
                    raise RuleLoadObservationIngestError(ErrorCode.IDENTITY_REVOKED)
                if reporter.current_epoch != observation.process_epoch:
                    raise RuleLoadObservationIngestError(ErrorCode.INVALID_EPOCH)

                existing = await session.get(
                    RuleLoadObservationInboxRecord, observation.observation_id
                )
                if existing is not None:
                    if (
                        existing.certificate_principal != reporter.certificate_principal
                        or existing.body_sha256 != body_sha256
                    ):
                        raise RuleLoadObservationIngestError(
                            ErrorCode.IDEMPOTENCY_CONFLICT
                        )
                    return

                binding = await session.get(RuleBindingRecord, observation.binding_id)
                if binding is None:
                    raise RuleLoadObservationIngestError(ErrorCode.BINDING_NOT_FOUND)
                if (
                    binding.environment_id != reporter.environment_id
                    or binding.app_id != reporter.app_id
                ):
                    raise RuleLoadObservationIngestError(ErrorCode.SCOPE_MISMATCH)
                if binding.profile != observation.profile_id:
                    raise RuleLoadObservationIngestError(ErrorCode.PROFILE_MISMATCH)

                sequence_key = (
                    reporter.certificate_principal,
                    observation.process_epoch,
                    observation.binding_id,
                )
                sequence = await session.get(
                    RuleLoadObservationSequenceRecord, sequence_key
                )
                if sequence is None:
                    sequence = RuleLoadObservationSequenceRecord(
                        certificate_principal=reporter.certificate_principal,
                        process_epoch=observation.process_epoch,
                        binding_id=observation.binding_id,
                        last_sequence=0,
                    )
                    session.add(sequence)
                    await session.flush()
                if observation.sequence <= sequence.last_sequence:
                    raise RuleLoadObservationIngestError(ErrorCode.STALE_SEQUENCE)

                snapshot = canonical_body["active_snapshot"]
                attempt = canonical_body["attempt"]
                session.add(
                    RuleLoadObservationInboxRecord(
                        observation_id=observation.observation_id,
                        certificate_principal=reporter.certificate_principal,
                        environment_id=reporter.environment_id,
                        app_id=reporter.app_id,
                        instance_id=reporter.instance_id,
                        process_id=reporter.process_id,
                        process_epoch=observation.process_epoch,
                        sequence=observation.sequence,
                        binding_id=observation.binding_id,
                        profile_id=observation.profile_id,
                        event_kind=observation.event_kind.value,
                        active_snapshot=snapshot,
                        attempt=attempt,
                        observed_at=observation.observed_at,
                        received_at=received_at,
                        body_sha256=body_sha256,
                        body=body,
                    )
                )
                session.add(
                    RuleLoadObservationOutboxRecord(
                        observation_id=observation.observation_id,
                        state="pending",
                        available_at=received_at,
                        lease_token=None,
                        lease_until=None,
                        attempt_count=0,
                        rejection_code=None,
                        updated_at=received_at,
                    )
                )
                sequence.last_sequence = observation.sequence
                await session.flush()
        except RuleLoadObservationIngestError:
            raise
        except IntegrityError as error:
            if "uq_console_rule_load_observation_sequence" in str(error.orig).lower():
                raise RuleLoadObservationIngestError(ErrorCode.STALE_SEQUENCE) from None
            raise RuleLoadObservationIngestError(ErrorCode.STORAGE_UNAVAILABLE) from None
        except SQLAlchemyError:
            raise RuleLoadObservationIngestError(ErrorCode.STORAGE_UNAVAILABLE) from None

    async def _lock_enrollment(
        self, session: AsyncSession, peer: VerifiedMetricsPeer
    ) -> MetricsReporterBindingRecord | None:
        """Serialize observations with certificate revoke/epoch rotation."""
        await session.execute(
            update(MetricsReporterBindingRecord)
            .where(
                MetricsReporterBindingRecord.certificate_sha256
                == peer.certificate_sha256
            )
            .values(current_epoch=MetricsReporterBindingRecord.current_epoch)
        )
        return await session.scalar(
            select(MetricsReporterBindingRecord)
            .where(
                MetricsReporterBindingRecord.certificate_sha256
                == peer.certificate_sha256
            )
            .with_for_update()
        )


def _is_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


__all__ = ["SQLAlchemyRuleLoadObservationInbox"]
