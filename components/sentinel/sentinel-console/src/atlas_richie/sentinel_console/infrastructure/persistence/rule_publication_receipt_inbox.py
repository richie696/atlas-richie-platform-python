"""SQL Adapter for authenticated receipt verification and durable outbox enqueue."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from atlas_richie.contracts.rules.publication_receipt import RulePublicationReceiptV1
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.metrics_ingest_ports import VerifiedMetricsPeer
from ...application.publication_receipt_ingest_ports import (
    PublicationReceiptInboxPort,
    PublicationReceiptIngestError,
)
from ...application.publication_receipt_ingest_ports import (
    PublicationReceiptIngestErrorCode as ErrorCode,
)
from .models import (
    MetricsReporterBindingRecord,
    RuleBindingRecord,
    RulePublicationReceiptInboxRecord,
    RulePublicationReceiptOutboxRecord,
    RulePublicationReceiptSequenceRecord,
    RulePublicationRecord,
)


class SQLAlchemyRulePublicationReceiptInbox(PublicationReceiptInboxPort):
    """Verify enrollment and publication authority while committing inbox/outbox."""

    def __init__(
        self,
        engine_resolver: Callable[[], Awaitable[AsyncEngine]],
    ) -> None:
        self._engine_resolver = engine_resolver

    async def accept(
        self,
        *,
        peer: VerifiedMetricsPeer,
        receipt: RulePublicationReceiptV1,
        body: bytes,
        body_sha256: str,
        received_at: datetime,
    ) -> None:
        """Commit the accepted immutable fact and delivery row in one transaction."""
        if hashlib.sha256(body).hexdigest() != body_sha256:
            raise ValueError("receipt digest does not match exact request bytes")
        if not _is_utc(received_at):
            raise ValueError("receipt receive time must be UTC-aware")
        received_at = received_at.astimezone(UTC)

        try:
            engine = await self._engine_resolver()
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions.begin() as session:
                binding = await self._lock_enrollment(session, peer)
                if binding is None:
                    raise PublicationReceiptIngestError(ErrorCode.IDENTITY_NOT_ENROLLED)
                if binding.revoked_at is not None:
                    raise PublicationReceiptIngestError(ErrorCode.IDENTITY_REVOKED)
                if binding.current_epoch is None or str(receipt.process_epoch) != str(
                    binding.current_epoch
                ):
                    raise PublicationReceiptIngestError(ErrorCode.INVALID_EPOCH)

                prior = await session.get(
                    RulePublicationReceiptInboxRecord, receipt.receipt_id
                )
                if prior is not None:
                    if (
                        prior.certificate_principal != binding.certificate_principal
                        or prior.body_sha256 != body_sha256
                    ):
                        raise PublicationReceiptIngestError(
                            ErrorCode.IDEMPOTENCY_CONFLICT
                        )
                    return

                await self._verify_publication_authority(session, binding, receipt)
                sequence = await session.get(
                    RulePublicationReceiptSequenceRecord,
                    (binding.certificate_principal, receipt.process_epoch),
                )
                if sequence is None:
                    sequence = RulePublicationReceiptSequenceRecord(
                        certificate_principal=binding.certificate_principal,
                        process_epoch=receipt.process_epoch,
                        last_sequence=0,
                    )
                    session.add(sequence)
                    await session.flush()
                if receipt.sequence <= sequence.last_sequence:
                    raise PublicationReceiptIngestError(ErrorCode.STALE_SEQUENCE)

                session.add(
                    RulePublicationReceiptInboxRecord(
                        receipt_id=receipt.receipt_id,
                        certificate_principal=binding.certificate_principal,
                        environment_id=binding.environment_id,
                        app_id=binding.app_id,
                        instance_id=binding.instance_id,
                        process_id=binding.process_id,
                        process_epoch=receipt.process_epoch,
                        sequence=receipt.sequence,
                        binding_id=receipt.binding_id,
                        publication_id=receipt.publication_id,
                        target_version_id=receipt.target_version_id,
                        target_payload_sha256=receipt.target_payload_sha256,
                        state=receipt.state.value,
                        reason=None if receipt.reason is None else receipt.reason.value,
                        source_revision=receipt.source_revision,
                        observed_at=receipt.observed_at,
                        received_at=received_at,
                        body_sha256=body_sha256,
                        body=body,
                    )
                )
                session.add(
                    RulePublicationReceiptOutboxRecord(
                        receipt_id=receipt.receipt_id,
                        state="pending",
                        available_at=received_at,
                        lease_token=None,
                        lease_until=None,
                        attempt_count=0,
                        rejection_code=None,
                        updated_at=received_at,
                    )
                )
                sequence.last_sequence = receipt.sequence
                await session.flush()
        except PublicationReceiptIngestError:
            raise
        except IntegrityError as error:
            message = str(error.orig).lower()
            if "uq_console_receipt_principal_epoch_sequence" in message:
                raise PublicationReceiptIngestError(ErrorCode.STALE_SEQUENCE) from None
            raise PublicationReceiptIngestError(ErrorCode.STORAGE_UNAVAILABLE) from None
        except SQLAlchemyError:
            raise PublicationReceiptIngestError(ErrorCode.STORAGE_UNAVAILABLE) from None

    async def _lock_enrollment(
        self, session: AsyncSession, peer: VerifiedMetricsPeer
    ) -> MetricsReporterBindingRecord | None:
        """Serialize receipt acceptance with enrollment revocation and rotation."""
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

    async def _verify_publication_authority(
        self,
        session: AsyncSession,
        reporter: MetricsReporterBindingRecord,
        receipt: RulePublicationReceiptV1,
    ) -> None:
        """Require the exact registered binding, publication, target, and digest."""
        binding = await session.get(RuleBindingRecord, receipt.binding_id)
        if binding is None:
            raise PublicationReceiptIngestError(ErrorCode.PUBLICATION_NOT_FOUND)
        if (
            binding.environment_id != reporter.environment_id
            or binding.app_id != reporter.app_id
        ):
            raise PublicationReceiptIngestError(ErrorCode.SCOPE_MISMATCH)
        publication = await session.get(RulePublicationRecord, receipt.publication_id)
        if publication is None or publication.binding_id != binding.binding_id:
            raise PublicationReceiptIngestError(ErrorCode.PUBLICATION_NOT_FOUND)
        if publication.target_version_id != receipt.target_version_id:
            raise PublicationReceiptIngestError(ErrorCode.TARGET_MISMATCH)
        if publication.target_payload_checksum is None:
            raise PublicationReceiptIngestError(ErrorCode.TARGET_MISMATCH)
        if publication.target_payload_checksum != receipt.target_payload_sha256:
            raise PublicationReceiptIngestError(ErrorCode.DIGEST_MISMATCH)


def _is_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


__all__ = ["SQLAlchemyRulePublicationReceiptInbox"]
