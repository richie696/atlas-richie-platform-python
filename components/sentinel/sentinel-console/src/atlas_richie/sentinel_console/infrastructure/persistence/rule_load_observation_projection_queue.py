"""Leased SQL projection queue for Rule Load Observation V1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleLoadEventKind,
    RuleLoadObservationV1,
    decode_rule_load_observation,
)
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_load_observation_projection_ports import (
    RuleLoadObservationProjectionClaim,
    RuleLoadObservationProjectionQueue,
    RuleLoadObservationProjectionRejected,
    RuleLoadObservationProjectionUnavailable,
)
from .models import (
    MetricsReporterBindingRecord,
    RuleBindingRecord,
    RuleLoadObservationCurrentRecord,
    RuleLoadObservationInboxRecord,
    RuleLoadObservationOutboxRecord,
)

_MAX_BATCH_SIZE = 100


class SqlAlchemyRuleLoadObservationProjectionQueue(
    RuleLoadObservationProjectionQueue
):
    """Claim the durable outbox, enforce authority, and project current state."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim_ready(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> tuple[RuleLoadObservationProjectionClaim, ...]:
        _validate_claim(now, lease_expires_at, limit)
        outbox = RuleLoadObservationOutboxRecord
        inbox = RuleLoadObservationInboxRecord
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
                                outbox.observation_id,
                                inbox.body,
                                inbox.body_sha256,
                                inbox.received_at,
                                outbox.attempt_count,
                            )
                            .join(
                                inbox,
                                inbox.observation_id == outbox.observation_id,
                            )
                            .where(ready)
                            .order_by(outbox.available_at, outbox.observation_id)
                            .limit(limit)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .mappings()
                    .all()
                )
                claims: list[RuleLoadObservationProjectionClaim] = []
                for row in rows:
                    body = bytes(row["body"])
                    digest = hashlib.sha256(body).hexdigest()
                    try:
                        observation = decode_rule_load_observation(body)
                    except (TypeError, ValueError):
                        await _park_invalid(connection, row["observation_id"], now)
                        continue
                    if digest != row["body_sha256"]:
                        await _park_invalid(connection, row["observation_id"], now)
                        continue
                    token = str(uuid4())
                    attempt = int(row["attempt_count"] or 0) + 1
                    changed = await connection.execute(
                        update(outbox)
                        .where(outbox.observation_id == row["observation_id"], ready)
                        .values(
                            state="claimed",
                            lease_token=token,
                            lease_until=lease_expires_at,
                            attempt_count=attempt,
                            updated_at=now,
                        )
                    )
                    if changed.rowcount != 1:
                        continue
                    claims.append(
                        RuleLoadObservationProjectionClaim(
                            observation=observation,
                            received_at=_as_utc(row["received_at"]),
                            body_sha256=digest,
                            lease_token=token,
                            attempt=attempt,
                        )
                    )
                return tuple(claims)
        except RuleLoadObservationProjectionUnavailable:
            raise
        except SQLAlchemyError:
            raise RuleLoadObservationProjectionUnavailable() from None
        except (KeyError, TypeError, ValueError):
            raise RuleLoadObservationProjectionUnavailable() from None

    async def project(
        self, claim: RuleLoadObservationProjectionClaim, *, now: datetime
    ) -> None:
        _validate_now(now)
        observation = claim.observation
        try:
            async with self._engine.begin() as connection:
                lease = (
                    (
                        await connection.execute(
                            select(RuleLoadObservationOutboxRecord.observation_id)
                            .where(
                                RuleLoadObservationOutboxRecord.observation_id
                                == observation.observation_id,
                                RuleLoadObservationOutboxRecord.state == "claimed",
                                RuleLoadObservationOutboxRecord.lease_token
                                == claim.lease_token,
                                RuleLoadObservationOutboxRecord.lease_until > now,
                            )
                            .with_for_update()
                        )
                    )
                    .scalar_one_or_none()
                )
                if lease is None:
                    raise RuleLoadObservationProjectionUnavailable()
                inbox = (
                    (
                        await connection.execute(
                            select(RuleLoadObservationInboxRecord.__table__).where(
                                RuleLoadObservationInboxRecord.observation_id
                                == observation.observation_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if inbox is None:
                    raise RuleLoadObservationProjectionRejected("invalid_inbox")
                body = bytes(inbox["body"])
                try:
                    stored = decode_rule_load_observation(body)
                    body_fields = json.loads(body.decode("utf-8"))
                except (KeyError, TypeError, ValueError):
                    raise RuleLoadObservationProjectionRejected("invalid_inbox") from None
                if (
                    hashlib.sha256(body).hexdigest() != claim.body_sha256
                    or inbox["body_sha256"] != claim.body_sha256
                    or stored != observation
                    or not _inbox_matches(inbox, observation, claim.received_at)
                ):
                    raise RuleLoadObservationProjectionRejected("invalid_inbox")

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
                    raise RuleLoadObservationProjectionRejected("identity_revoked")
                if reporter["current_epoch"] != observation.process_epoch:
                    raise RuleLoadObservationProjectionRejected("stale_epoch")

                binding = (
                    (
                        await connection.execute(
                            select(RuleBindingRecord.__table__).where(
                                RuleBindingRecord.binding_id == observation.binding_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if binding is None:
                    raise RuleLoadObservationProjectionRejected("binding_unavailable")
                if (
                    binding["environment_id"] != reporter["environment_id"]
                    or binding["app_id"] != reporter["app_id"]
                    or binding["environment_id"] != inbox["environment_id"]
                    or binding["app_id"] != inbox["app_id"]
                    or inbox["instance_id"] != reporter["instance_id"]
                    or inbox["process_id"] != reporter["process_id"]
                ):
                    raise RuleLoadObservationProjectionRejected("scope_mismatch")
                if binding["profile"] != observation.profile_id:
                    raise RuleLoadObservationProjectionRejected("profile_mismatch")

                current = (
                    (
                        await connection.execute(
                            select(RuleLoadObservationCurrentRecord.__table__)
                            .where(
                                RuleLoadObservationCurrentRecord.certificate_principal
                                == inbox["certificate_principal"],
                                RuleLoadObservationCurrentRecord.binding_id
                                == observation.binding_id,
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                same_epoch = (
                    current is not None
                    and current["process_epoch"] == observation.process_epoch
                )
                if same_epoch and current["sequence"] >= observation.sequence:
                    # An earlier outbox row can be claimed after a later one;
                    # it is valid history but must never move current backwards.
                    return

                active_snapshot = body_fields["active_snapshot"]
                if active_snapshot is None and same_epoch:
                    active_snapshot = current["active_snapshot"]
                attempt = body_fields["attempt"]
                if observation.event_kind is RuleLoadEventKind.HEARTBEAT and same_epoch:
                    attempt = current["attempt"]
                values = {
                    "observation_id": observation.observation_id,
                    "environment_id": reporter["environment_id"],
                    "app_id": reporter["app_id"],
                    "instance_id": reporter["instance_id"],
                    "process_id": reporter["process_id"],
                    "process_epoch": observation.process_epoch,
                    "sequence": observation.sequence,
                    "profile_id": observation.profile_id,
                    "event_kind": observation.event_kind.value,
                    "active_snapshot": active_snapshot,
                    "attempt": attempt,
                    "observed_at": observation.observed_at,
                    "received_at": claim.received_at,
                }
                if current is None:
                    await connection.execute(
                        RuleLoadObservationCurrentRecord.__table__.insert().values(
                            certificate_principal=inbox["certificate_principal"],
                            binding_id=observation.binding_id,
                            **values,
                        )
                    )
                else:
                    await connection.execute(
                        update(RuleLoadObservationCurrentRecord)
                        .where(
                            RuleLoadObservationCurrentRecord.certificate_principal
                            == inbox["certificate_principal"],
                            RuleLoadObservationCurrentRecord.binding_id
                            == observation.binding_id,
                        )
                        .values(**values)
                    )
        except RuleLoadObservationProjectionRejected:
            raise
        except RuleLoadObservationProjectionUnavailable:
            raise
        except SQLAlchemyError:
            raise RuleLoadObservationProjectionUnavailable() from None
        except (KeyError, TypeError, ValueError):
            raise RuleLoadObservationProjectionRejected("invalid_inbox") from None

    async def mark_delivered(
        self, claim: RuleLoadObservationProjectionClaim, *, now: datetime
    ) -> None:
        await self._transition(claim, now=now, state="delivered")

    async def park(
        self,
        claim: RuleLoadObservationProjectionClaim,
        *,
        rejection_code: str,
        now: datetime,
    ) -> None:
        if not rejection_code or len(rejection_code) > 64:
            raise ValueError("rejection code is invalid")
        await self._transition(
            claim, now=now, state="parked", rejection_code=rejection_code
        )

    async def release(
        self,
        claim: RuleLoadObservationProjectionClaim,
        *,
        available_at: datetime,
        now: datetime,
    ) -> None:
        _validate_now(available_at)
        await self._transition(
            claim, now=now, state="pending", available_at=available_at
        )

    async def _transition(
        self,
        claim: RuleLoadObservationProjectionClaim,
        *,
        now: datetime,
        state: str,
        available_at: datetime | None = None,
        rejection_code: str | None = None,
    ) -> None:
        _validate_now(now)
        outbox = RuleLoadObservationOutboxRecord
        values: dict[str, object] = {
            "state": state,
            "lease_token": None,
            "lease_until": None,
            "updated_at": now,
            "rejection_code": rejection_code,
        }
        if available_at is not None:
            values["available_at"] = available_at
        try:
            async with self._engine.begin() as connection:
                result = await connection.execute(
                    update(outbox)
                    .where(
                        outbox.observation_id
                        == claim.observation.observation_id,
                        outbox.state == "claimed",
                        outbox.lease_token == claim.lease_token,
                        outbox.lease_until > now,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise RuleLoadObservationProjectionUnavailable()
        except RuleLoadObservationProjectionUnavailable:
            raise
        except SQLAlchemyError:
            raise RuleLoadObservationProjectionUnavailable() from None


async def _park_invalid(connection, observation_id: str, now: datetime) -> None:
    await connection.execute(
        update(RuleLoadObservationOutboxRecord)
        .where(RuleLoadObservationOutboxRecord.observation_id == observation_id)
        .values(
            state="parked",
            lease_token=None,
            lease_until=None,
            rejection_code="invalid_inbox",
            updated_at=now,
        )
    )


def _inbox_matches(inbox, observation: RuleLoadObservationV1, received_at: datetime) -> bool:
    return (
        inbox["observation_id"] == observation.observation_id
        and inbox["certificate_principal"]
        and inbox["process_epoch"] == observation.process_epoch
        and inbox["sequence"] == observation.sequence
        and inbox["binding_id"] == observation.binding_id
        and inbox["profile_id"] == observation.profile_id
        and inbox["event_kind"] == observation.event_kind.value
        and _millisecond(inbox["observed_at"]) == observation.observed_at
        and _as_utc(inbox["received_at"]) == _as_utc(received_at)
    )


def _validate_claim(now: datetime, lease_expires_at: datetime, limit: int) -> None:
    _validate_now(now)
    _validate_now(lease_expires_at)
    if lease_expires_at <= now:
        raise ValueError("projection lease must expire after claim time")
    if type(limit) is not int or not 1 <= limit <= _MAX_BATCH_SIZE:
        raise ValueError("projection batch limit is invalid")


def _validate_now(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError("projection timestamps must be UTC-aware")


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("projection timestamp must be datetime")
    if value.tzinfo is None:
        # SQLite returns timezone-aware SQLAlchemy values as naive datetimes;
        # every persisted timestamp is written in UTC by this adapter.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _millisecond(value: datetime) -> datetime:
    normalized = _as_utc(value)
    return normalized.replace(microsecond=(normalized.microsecond // 1000) * 1000)


__all__ = ["SqlAlchemyRuleLoadObservationProjectionQueue"]
