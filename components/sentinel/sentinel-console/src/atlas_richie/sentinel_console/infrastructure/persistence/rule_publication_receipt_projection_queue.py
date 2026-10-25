"""SQL outbox lease and idempotent projection adapter for Receipt V1."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atlas_richie.contracts.rules.publication_receipt import (
    decode_rule_publication_receipt,
)
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.publication_receipt_projection_ports import (
    PublicationReceiptProjectionClaim,
    PublicationReceiptProjectionQueue,
    PublicationReceiptProjectionRejected,
    PublicationReceiptProjectionUnavailable,
)
from ...domain.rule_publications import PublicationReceiptState, RulePublicationReceipt
from .models import (
    MetricsReporterBindingRecord,
    RuleBindingRecord,
    RulePublicationReceiptInboxRecord,
    RulePublicationReceiptOutboxRecord,
    RulePublicationReceiptRecord,
    RulePublicationRecord,
)
from .rule_publication_receipt_mapping import publication_receipt_values

_MAX_BATCH_SIZE = 100


class SqlAlchemyRulePublicationReceiptProjectionQueue(
    PublicationReceiptProjectionQueue
):
    """Claim bounded outbox batches and project trusted facts with sequence fencing."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim_ready(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> tuple[PublicationReceiptProjectionClaim, ...]:
        _validate_claim_window(now, lease_expires_at, limit)
        outbox = RulePublicationReceiptOutboxRecord
        inbox = RulePublicationReceiptInboxRecord
        ready = or_(
            and_(outbox.state == "pending", outbox.available_at <= now),
            and_(outbox.state == "claimed", outbox.lease_until <= now),
        )
        try:
            async with self._engine.begin() as connection:
                rows = (
                    (
                        await connection.execute(
                            select(
                                outbox.receipt_id,
                                inbox.body,
                                inbox.body_sha256,
                                inbox.received_at,
                                outbox.attempt_count,
                            )
                            .join(inbox, inbox.receipt_id == outbox.receipt_id)
                            .where(ready)
                            .order_by(outbox.available_at, outbox.receipt_id)
                            .limit(limit)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .mappings()
                    .all()
                )
                claims: list[PublicationReceiptProjectionClaim] = []
                for row in rows:
                    body = bytes(row["body"])
                    body_sha256 = hashlib.sha256(body).hexdigest()
                    try:
                        receipt = decode_rule_publication_receipt(body)
                    except (TypeError, ValueError):
                        await _park_invalid_inbox(connection, row["receipt_id"], now)
                        continue
                    if body_sha256 != row["body_sha256"]:
                        await _park_invalid_inbox(connection, row["receipt_id"], now)
                        continue
                    claim_token = str(uuid4())
                    attempt = int(row["attempt_count"] or 0) + 1
                    changed = await connection.execute(
                        update(outbox)
                        .where(outbox.receipt_id == row["receipt_id"], ready)
                        .values(
                            state="claimed",
                            lease_token=claim_token,
                            lease_until=lease_expires_at,
                            attempt_count=attempt,
                            updated_at=now,
                        )
                    )
                    if changed.rowcount != 1:
                        continue
                    claims.append(
                        PublicationReceiptProjectionClaim(
                            receipt=receipt,
                            received_at=_as_utc(row["received_at"]),
                            body_sha256=body_sha256,
                            lease_token=claim_token,
                            attempt=attempt,
                        )
                    )
                return tuple(claims)
        except PublicationReceiptProjectionUnavailable:
            raise
        except SQLAlchemyError:
            raise PublicationReceiptProjectionUnavailable() from None
        except (KeyError, TypeError, ValueError):
            raise PublicationReceiptProjectionUnavailable() from None

    async def project(
        self, claim: PublicationReceiptProjectionClaim, *, now: datetime
    ) -> None:
        _validate_now(now)
        receipt = claim.receipt
        try:
            async with self._engine.begin() as connection:
                outbox = (
                    (
                        await connection.execute(
                            select(RulePublicationReceiptOutboxRecord.__table__)
                            .where(
                                RulePublicationReceiptOutboxRecord.receipt_id
                                == receipt.receipt_id,
                                RulePublicationReceiptOutboxRecord.state == "claimed",
                                RulePublicationReceiptOutboxRecord.lease_token
                                == claim.lease_token,
                                RulePublicationReceiptOutboxRecord.lease_until > now,
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if outbox is None:
                    raise PublicationReceiptProjectionUnavailable()

                inbox = (
                    (
                        await connection.execute(
                            select(RulePublicationReceiptInboxRecord.__table__).where(
                                RulePublicationReceiptInboxRecord.receipt_id
                                == receipt.receipt_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if inbox is None or inbox["body_sha256"] != claim.body_sha256:
                    raise PublicationReceiptProjectionRejected("idempotency_conflict")
                body = bytes(inbox["body"])
                try:
                    stored_receipt = decode_rule_publication_receipt(body)
                    inbox_matches = _inbox_matches_receipt(
                        inbox, receipt, claim.received_at
                    )
                except (KeyError, TypeError, ValueError):
                    inbox_matches = False
                if (
                    hashlib.sha256(body).hexdigest() != claim.body_sha256
                    or not inbox_matches
                    or stored_receipt != receipt
                ):
                    raise PublicationReceiptProjectionRejected("invalid_inbox")

                reporter = (
                    (
                        await connection.execute(
                            select(MetricsReporterBindingRecord.__table__)
                            .where(
                                MetricsReporterBindingRecord.certificate_principal
                                == inbox["certificate_principal"]
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if reporter is None or reporter["revoked_at"] is not None:
                    raise PublicationReceiptProjectionRejected("identity_revoked")
                if reporter["current_epoch"] != receipt.process_epoch:
                    raise PublicationReceiptProjectionRejected("stale_epoch")

                binding = (
                    (
                        await connection.execute(
                            select(RuleBindingRecord.__table__).where(
                                RuleBindingRecord.binding_id == receipt.binding_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                publication = (
                    (
                        await connection.execute(
                            select(RulePublicationRecord.__table__).where(
                                RulePublicationRecord.publication_id
                                == receipt.publication_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if binding is None or publication is None:
                    raise PublicationReceiptProjectionRejected("publication_not_found")
                if (
                    inbox["environment_id"] != reporter["environment_id"]
                    or inbox["app_id"] != reporter["app_id"]
                    or inbox["instance_id"] != reporter["instance_id"]
                    or inbox["process_id"] != reporter["process_id"]
                    or inbox["process_epoch"] != reporter["current_epoch"]
                    or binding["environment_id"] != reporter["environment_id"]
                    or binding["app_id"] != reporter["app_id"]
                ):
                    raise PublicationReceiptProjectionRejected("scope_mismatch")
                if (
                    publication["binding_id"] != binding["binding_id"]
                    or publication["target_version_id"] != receipt.target_version_id
                ):
                    raise PublicationReceiptProjectionRejected("target_mismatch")
                if (
                    publication["target_payload_checksum"] is None
                    or publication["target_payload_checksum"]
                    != receipt.target_payload_sha256
                ):
                    raise PublicationReceiptProjectionRejected("digest_mismatch")

                projection = (
                    (
                        await connection.execute(
                            select(RulePublicationReceiptRecord.__table__)
                            .where(
                                RulePublicationReceiptRecord.publication_id
                                == receipt.publication_id,
                                RulePublicationReceiptRecord.instance_id
                                == inbox["instance_id"],
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if projection is not None:
                    if projection["receipt_id"] == receipt.receipt_id:
                        return
                    if (
                        projection["process_epoch"] == receipt.process_epoch
                        and projection["receipt_sequence"] is not None
                        and projection["receipt_sequence"] >= receipt.sequence
                    ):
                        raise PublicationReceiptProjectionRejected("stale_sequence")

                domain_receipt = _domain_receipt(
                    receipt,
                    inbox["instance_id"],
                    inbox["received_at"],
                    publication,
                )
                values = publication_receipt_values(
                    receipt.binding_id, receipt.publication_id, domain_receipt
                )
                values["receipt_id"] = receipt.receipt_id
                values["receipt_sequence"] = receipt.sequence
                if projection is None:
                    await connection.execute(
                        RulePublicationReceiptRecord.__table__.insert().values(**values)
                    )
                else:
                    await connection.execute(
                        update(RulePublicationReceiptRecord)
                        .where(
                            RulePublicationReceiptRecord.publication_id
                            == receipt.publication_id,
                            RulePublicationReceiptRecord.instance_id
                            == inbox["instance_id"],
                        )
                        .values(**values)
                    )
        except PublicationReceiptProjectionRejected:
            raise
        except PublicationReceiptProjectionUnavailable:
            raise
        except SQLAlchemyError:
            raise PublicationReceiptProjectionUnavailable() from None
        except (KeyError, TypeError, ValueError):
            raise PublicationReceiptProjectionUnavailable() from None

    async def mark_delivered(
        self, claim: PublicationReceiptProjectionClaim, *, now: datetime
    ) -> None:
        await self._advance_outbox(
            claim,
            now=now,
            values={
                "state": "delivered",
                "lease_token": None,
                "lease_until": None,
                "rejection_code": None,
                "updated_at": now,
            },
        )

    async def park(
        self,
        claim: PublicationReceiptProjectionClaim,
        *,
        rejection_code: str,
        now: datetime,
    ) -> None:
        await self._advance_outbox(
            claim,
            now=now,
            values={
                "state": "parked",
                "lease_token": None,
                "lease_until": None,
                "rejection_code": rejection_code,
                "updated_at": now,
            },
        )

    async def release(
        self,
        claim: PublicationReceiptProjectionClaim,
        *,
        available_at: datetime,
        now: datetime,
    ) -> None:
        await self._advance_outbox(
            claim,
            now=now,
            values={
                "state": "pending",
                "available_at": available_at,
                "lease_token": None,
                "lease_until": None,
                "updated_at": now,
            },
        )

    async def _advance_outbox(
        self,
        claim: PublicationReceiptProjectionClaim,
        *,
        now: datetime,
        values: dict[str, object],
    ) -> None:
        try:
            async with self._engine.begin() as connection:
                changed = await connection.execute(
                    update(RulePublicationReceiptOutboxRecord)
                    .where(
                        RulePublicationReceiptOutboxRecord.receipt_id
                        == claim.receipt.receipt_id,
                        RulePublicationReceiptOutboxRecord.state == "claimed",
                        RulePublicationReceiptOutboxRecord.lease_token
                        == claim.lease_token,
                    )
                    .values(**values)
                )
                if changed.rowcount == 0 and values.get("state") == "delivered":
                    state = await connection.scalar(
                        select(RulePublicationReceiptOutboxRecord.state).where(
                            RulePublicationReceiptOutboxRecord.receipt_id
                            == claim.receipt.receipt_id
                        )
                    )
                    if state == "delivered":
                        return
                if changed.rowcount == 0:
                    raise PublicationReceiptProjectionUnavailable()
        except SQLAlchemyError:
            raise PublicationReceiptProjectionUnavailable() from None


def _domain_receipt(
    receipt, instance_id: str, received_at: datetime, publication
) -> RulePublicationReceipt:
    applied = receipt.state.value == PublicationReceiptState.APPLIED.value
    return RulePublicationReceipt(
        instance_id=instance_id,
        process_epoch=receipt.process_epoch,
        loaded_process_epoch=receipt.process_epoch if applied else None,
        target_version_id=receipt.target_version_id,
        loaded_version_id=receipt.target_version_id if applied else None,
        loaded_checksum=publication["target_checksum"] if applied else None,
        applied_at=receipt.observed_at if applied else None,
        last_report_at=_millisecond(received_at),
        state=PublicationReceiptState(receipt.state.value),
    )


def _validate_claim_window(
    now: datetime, lease_expires_at: datetime, limit: int
) -> None:
    _validate_now(now)
    _validate_now(lease_expires_at)
    if lease_expires_at <= now or lease_expires_at - now > _MAX_CLAIM_LEASE:
        raise ValueError("receipt projection lease window is invalid")
    if type(limit) is not int or not 1 <= limit <= _MAX_BATCH_SIZE:
        raise ValueError("receipt projection batch size is invalid")


def _validate_now(now: datetime) -> None:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() != UTC.utcoffset(now)
    ):
        raise ValueError("receipt projection time must be UTC-aware")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _millisecond(value: datetime) -> datetime:
    normalized = _as_utc(value)
    return normalized.replace(microsecond=(normalized.microsecond // 1000) * 1000)


def _inbox_matches_receipt(inbox, receipt, claimed_received_at: datetime) -> bool:
    """Reject a denormalized inbox projection that diverged from its wire fact."""
    return (
        inbox["receipt_id"] == receipt.receipt_id
        and inbox["process_epoch"] == receipt.process_epoch
        and inbox["sequence"] == receipt.sequence
        and inbox["binding_id"] == receipt.binding_id
        and inbox["publication_id"] == receipt.publication_id
        and inbox["target_version_id"] == receipt.target_version_id
        and inbox["target_payload_sha256"] == receipt.target_payload_sha256
        and inbox["state"] == receipt.state.value
        and inbox["reason"]
        == (None if receipt.reason is None else receipt.reason.value)
        and inbox["source_revision"] == receipt.source_revision
        and _millisecond(inbox["observed_at"]) == receipt.observed_at
        and _as_utc(inbox["received_at"]) == _as_utc(claimed_received_at)
    )


async def _park_invalid_inbox(connection, receipt_id: str, now: datetime) -> None:
    """Keep corrupt durable bytes from retrying forever or reaching the read model."""
    await connection.execute(
        update(RulePublicationReceiptOutboxRecord)
        .where(
            RulePublicationReceiptOutboxRecord.receipt_id == receipt_id,
            or_(
                RulePublicationReceiptOutboxRecord.state == "pending",
                and_(
                    RulePublicationReceiptOutboxRecord.state == "claimed",
                    RulePublicationReceiptOutboxRecord.lease_until <= now,
                ),
            ),
        )
        .values(
            state="parked",
            lease_token=None,
            lease_until=None,
            rejection_code="invalid_inbox",
            updated_at=now,
        )
    )


_MAX_CLAIM_LEASE = timedelta(minutes=5)


__all__ = ["SqlAlchemyRulePublicationReceiptProjectionQueue"]
