"""SQL-backed, fenced claims for due rule activation-plan phases."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_activation_plan_ports import (
    RuleActivationPlanAuthorityUnavailable,
    RuleActivationPlanClaim,
    RuleActivationPlanClaimConflict,
    RuleActivationPlanWorkQueue,
)
from ...domain.rule_activation_plans import (
    RuleActivationPlanState,
)
from ...domain.rule_publications import PublicationStage
from ...domain.rule_bindings import is_rule_binding_identifier
from ...domain.utc_time import is_wire_utc_millisecond_instant
from .models import RuleActivationPlanRecord, RulePublicationRecord
from .rule_activation_plan_mapping import (
    activation_plan_body_from_row,
    activation_plan_from_body,
)

_MAX_CLAIM_BATCH = 100
_MAX_LEASE = timedelta(minutes=5)
_EXECUTABLE_STATES = (
    RuleActivationPlanState.ACTIVATING.value,
    RuleActivationPlanState.RESTORING.value,
)


class SqlAlchemyRuleActivationPlanWorkQueue(RuleActivationPlanWorkQueue):
    """Claim due plans transactionally and reject stale lease holders."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim_due(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int = 1,
    ) -> tuple[RuleActivationPlanClaim, ...]:
        """Claim due phases, resuming expired in-flight work with a fresh token."""
        _validate_window(now, lease_expires_at)
        if type(limit) is not int or not 1 <= limit <= _MAX_CLAIM_BATCH:
            raise ValueError("activation plan claim limit is invalid")
        try:
            async with self._engine.begin() as connection:
                due = or_(
                    and_(
                        RuleActivationPlanRecord.state
                        == RuleActivationPlanState.PENDING.value,
                        RuleActivationPlanRecord.activate_at <= now,
                    ),
                    and_(
                        RuleActivationPlanRecord.state
                        == RuleActivationPlanState.ACTIVE.value,
                        RuleActivationPlanRecord.deactivate_at <= now,
                    ),
                    and_(
                        RuleActivationPlanRecord.state.in_(_EXECUTABLE_STATES),
                        or_(
                            RuleActivationPlanRecord.claim_lease_expires_at.is_(None),
                            RuleActivationPlanRecord.claim_lease_expires_at <= now,
                        ),
                    ),
                )
                result = await connection.execute(
                    select(RuleActivationPlanRecord.__table__)
                    .where(due)
                    .order_by(
                        RuleActivationPlanRecord.activate_at.asc(),
                        RuleActivationPlanRecord.plan_id.asc(),
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                rows = result.mappings().all()
                claims: list[RuleActivationPlanClaim] = []
                for row in rows:
                    prior_state = RuleActivationPlanState(row["state"])
                    if prior_state is RuleActivationPlanState.PENDING:
                        next_state = RuleActivationPlanState.ACTIVATING
                    elif prior_state is RuleActivationPlanState.ACTIVE:
                        next_state = RuleActivationPlanState.RESTORING
                    else:
                        next_state = prior_state
                    claim_token = str(uuid4())
                    revision = str(uuid4())
                    changed = await connection.execute(
                        update(RuleActivationPlanRecord)
                        .where(
                            RuleActivationPlanRecord.plan_id == row["plan_id"],
                            RuleActivationPlanRecord.revision == row["revision"],
                            RuleActivationPlanRecord.state == prior_state.value,
                        )
                        .values(
                            revision=revision,
                            state=next_state.value,
                            claim_token=claim_token,
                            claim_lease_expires_at=lease_expires_at,
                            claim_attempt_count=(row["claim_attempt_count"] or 0) + 1,
                        )
                    )
                    if changed.rowcount != 1:
                        continue
                    updated = dict(row)
                    updated.update(
                        revision=revision,
                        state=next_state.value,
                        claim_token=claim_token,
                        claim_lease_expires_at=lease_expires_at,
                        claim_attempt_count=(row["claim_attempt_count"] or 0) + 1,
                    )
                    claims.append(
                        RuleActivationPlanClaim(
                            plan=activation_plan_from_body(
                                activation_plan_body_from_row(updated)
                            ),
                            claim_token=claim_token,
                            lease_expires_at=lease_expires_at,
                            attempt=updated["claim_attempt_count"],
                        )
                    )
                return tuple(claims)
        except SQLAlchemyError:
            raise RuleActivationPlanAuthorityUnavailable(
                "activation plan queue is unavailable"
            ) from None
        except (KeyError, TypeError, ValueError):
            raise RuleActivationPlanAuthorityUnavailable(
                "activation plan queue contains invalid facts"
            ) from None

    async def renew_claim(
        self,
        claim: RuleActivationPlanClaim,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RuleActivationPlanClaim:
        """Extend a still-live exact claim without changing its phase identity."""
        if not isinstance(claim, RuleActivationPlanClaim):
            raise ValueError("activation plan claim is required")
        _validate_window(now, lease_expires_at)
        try:
            async with self._engine.begin() as connection:
                changed = await connection.execute(
                    update(RuleActivationPlanRecord)
                    .where(
                        RuleActivationPlanRecord.plan_id == claim.plan.id,
                        RuleActivationPlanRecord.revision == claim.plan.revision,
                        RuleActivationPlanRecord.state == claim.plan.state.value,
                        RuleActivationPlanRecord.claim_token == claim.claim_token,
                        RuleActivationPlanRecord.claim_lease_expires_at > now,
                    )
                    .values(claim_lease_expires_at=lease_expires_at)
                )
                if changed.rowcount != 1:
                    raise RuleActivationPlanClaimConflict(
                        "activation plan claim is no longer current"
                    )
                return RuleActivationPlanClaim(
                    plan=claim.plan,
                    claim_token=claim.claim_token,
                    lease_expires_at=lease_expires_at,
                    attempt=claim.attempt,
                )
        except RuleActivationPlanClaimConflict:
            raise
        except SQLAlchemyError:
            raise RuleActivationPlanAuthorityUnavailable(
                "activation plan lease authority is unavailable"
            ) from None

    async def associate_publication(
        self,
        claim: RuleActivationPlanClaim,
        publication_id: str,
        *,
        now: datetime,
    ) -> RuleActivationPlanClaim:
        """Bind a plan phase to one exact same-binding publication idempotently."""
        if (
            not isinstance(claim, RuleActivationPlanClaim)
            or not is_rule_binding_identifier(publication_id)
        ):
            raise ValueError("activation plan publication association is invalid")
        if not is_wire_utc_millisecond_instant(now):
            raise ValueError("activation plan association time is invalid")
        column = _publication_column(claim.plan.state)
        expected_version_id = (
            claim.plan.version_id
            if claim.plan.state is RuleActivationPlanState.ACTIVATING
            else claim.plan.restore_version_id
        )
        try:
            async with self._engine.begin() as connection:
                row_result = await connection.execute(
                    select(
                        RuleActivationPlanRecord.__table__,
                        RulePublicationRecord.target_version_id,
                    )
                    .join(
                        RulePublicationRecord,
                        and_(
                            RulePublicationRecord.publication_id == publication_id,
                            RulePublicationRecord.binding_id
                            == RuleActivationPlanRecord.binding_id,
                        ),
                    )
                    .where(
                        RuleActivationPlanRecord.plan_id == claim.plan.id,
                        RuleActivationPlanRecord.revision == claim.plan.revision,
                        RuleActivationPlanRecord.state == claim.plan.state.value,
                        RuleActivationPlanRecord.claim_token == claim.claim_token,
                        RuleActivationPlanRecord.claim_lease_expires_at > now,
                    )
                    .with_for_update()
                )
                row = row_result.mappings().one_or_none()
                if row is None or row["target_version_id"] != expected_version_id:
                    raise RuleActivationPlanClaimConflict(
                        "activation plan publication association is not current"
                    )
                associated = row[column.key]
                if associated is not None and associated != publication_id:
                    raise RuleActivationPlanClaimConflict(
                        "activation plan phase already has another publication"
                    )
                if associated is None:
                    changed = await connection.execute(
                        update(RuleActivationPlanRecord)
                        .where(
                            RuleActivationPlanRecord.plan_id == claim.plan.id,
                            RuleActivationPlanRecord.revision == claim.plan.revision,
                            RuleActivationPlanRecord.state == claim.plan.state.value,
                            RuleActivationPlanRecord.claim_token == claim.claim_token,
                            RuleActivationPlanRecord.claim_lease_expires_at > now,
                            column.is_(None),
                        )
                        .values({column.key: publication_id})
                    )
                    if changed.rowcount != 1:
                        raise RuleActivationPlanClaimConflict(
                            "activation plan publication association was superseded"
                        )
                plan = (
                    replace(claim.plan, activation_publication_id=publication_id)
                    if claim.plan.state is RuleActivationPlanState.ACTIVATING
                    else replace(claim.plan, restore_publication_id=publication_id)
                )
                return RuleActivationPlanClaim(
                    plan=plan,
                    claim_token=claim.claim_token,
                    lease_expires_at=claim.lease_expires_at,
                    attempt=claim.attempt,
                )
        except RuleActivationPlanClaimConflict:
            raise
        except SQLAlchemyError:
            raise RuleActivationPlanAuthorityUnavailable(
                "activation plan publication association is unavailable"
            ) from None

    async def complete_phase(
        self, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> RuleActivationPlan:
        """Complete activation/restoration only after exact publication read-back."""
        if not isinstance(claim, RuleActivationPlanClaim):
            raise ValueError("activation plan claim is required")
        if not is_wire_utc_millisecond_instant(now):
            raise ValueError("activation plan completion time is invalid")
        column = _publication_column(claim.plan.state)
        publication_id = getattr(claim.plan, column.key)
        if publication_id is None:
            raise RuleActivationPlanClaimConflict(
                "activation plan phase has no associated publication"
            )
        expected_version_id = (
            claim.plan.version_id
            if claim.plan.state is RuleActivationPlanState.ACTIVATING
            else claim.plan.restore_version_id
        )
        next_state = (
            RuleActivationPlanState.ACTIVE
            if claim.plan.state is RuleActivationPlanState.ACTIVATING
            else RuleActivationPlanState.COMPLETED
        )
        revision = str(uuid4())
        try:
            async with self._engine.begin() as connection:
                publication = await connection.execute(
                    select(
                        RulePublicationRecord.target_version_id,
                        RulePublicationRecord.validation_state,
                        RulePublicationRecord.write_state,
                        RulePublicationRecord.read_back_state,
                    )
                    .where(
                        RulePublicationRecord.publication_id == publication_id,
                        RulePublicationRecord.binding_id == claim.plan.binding_id,
                    )
                    .with_for_update()
                )
                phase = publication.one_or_none()
                if phase is None or any(
                    (
                        phase.target_version_id != expected_version_id,
                        phase.validation_state != PublicationStage.SUCCEEDED.value,
                        phase.write_state != PublicationStage.SUCCEEDED.value,
                        phase.read_back_state != PublicationStage.SUCCEEDED.value,
                    )
                ):
                    raise RuleActivationPlanClaimConflict(
                        "activation plan publication is not fully verified"
                    )
                changed = await connection.execute(
                    update(RuleActivationPlanRecord)
                    .where(
                        RuleActivationPlanRecord.plan_id == claim.plan.id,
                        RuleActivationPlanRecord.revision == claim.plan.revision,
                        RuleActivationPlanRecord.state == claim.plan.state.value,
                        RuleActivationPlanRecord.claim_token == claim.claim_token,
                        RuleActivationPlanRecord.claim_lease_expires_at > now,
                        column == publication_id,
                    )
                    .values(
                        revision=revision,
                        state=next_state.value,
                        claim_token=None,
                        claim_lease_expires_at=None,
                    )
                )
                if changed.rowcount != 1:
                    raise RuleActivationPlanClaimConflict(
                        "activation plan completion claim is no longer current"
                    )
                updated = {
                    "plan_id": claim.plan.id,
                    "revision": revision,
                    "binding_id": claim.plan.binding_id,
                    "version_id": claim.plan.version_id,
                    "restore_version_id": claim.plan.restore_version_id,
                    "activate_at": claim.plan.activate_at,
                    "deactivate_at": claim.plan.deactivate_at,
                    "time_zone": claim.plan.time_zone,
                    "state": next_state.value,
                    "activation_publication_id": claim.plan.activation_publication_id,
                    "restore_publication_id": claim.plan.restore_publication_id,
                }
                return activation_plan_from_body(
                    activation_plan_body_from_row(updated)
                )
        except RuleActivationPlanClaimConflict:
            raise
        except SQLAlchemyError:
            raise RuleActivationPlanAuthorityUnavailable(
                "activation plan completion authority is unavailable"
            ) from None

    async def block_claim(
        self, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> RuleActivationPlan:
        """Persist a terminal blocked decision and release the exact live lease."""
        if not isinstance(claim, RuleActivationPlanClaim):
            raise ValueError("activation plan claim is required")
        if not is_wire_utc_millisecond_instant(now):
            raise ValueError("activation plan block time is invalid")
        revision = str(uuid4())
        try:
            async with self._engine.begin() as connection:
                changed = await connection.execute(
                    update(RuleActivationPlanRecord)
                    .where(
                        RuleActivationPlanRecord.plan_id == claim.plan.id,
                        RuleActivationPlanRecord.revision == claim.plan.revision,
                        RuleActivationPlanRecord.state == claim.plan.state.value,
                        RuleActivationPlanRecord.claim_token == claim.claim_token,
                        RuleActivationPlanRecord.claim_lease_expires_at > now,
                    )
                    .values(
                        revision=revision,
                        state=RuleActivationPlanState.BLOCKED.value,
                        claim_token=None,
                        claim_lease_expires_at=None,
                    )
                )
                if changed.rowcount != 1:
                    raise RuleActivationPlanClaimConflict(
                        "activation plan block claim is no longer current"
                    )
                updated = {
                    "plan_id": claim.plan.id,
                    "revision": revision,
                    "binding_id": claim.plan.binding_id,
                    "version_id": claim.plan.version_id,
                    "restore_version_id": claim.plan.restore_version_id,
                    "activate_at": claim.plan.activate_at,
                    "deactivate_at": claim.plan.deactivate_at,
                    "time_zone": claim.plan.time_zone,
                    "state": RuleActivationPlanState.BLOCKED.value,
                    "activation_publication_id": claim.plan.activation_publication_id,
                    "restore_publication_id": claim.plan.restore_publication_id,
                }
                return activation_plan_from_body(
                    activation_plan_body_from_row(updated)
                )
        except RuleActivationPlanClaimConflict:
            raise
        except SQLAlchemyError:
            raise RuleActivationPlanAuthorityUnavailable(
                "activation plan block authority is unavailable"
            ) from None


def _validate_window(now: datetime, lease_expires_at: datetime) -> None:
    if (
        not is_wire_utc_millisecond_instant(now)
        or not is_wire_utc_millisecond_instant(lease_expires_at)
        or not timedelta(milliseconds=1) <= lease_expires_at - now <= _MAX_LEASE
    ):
        raise ValueError("activation plan lease window is invalid")


def _publication_column(state: RuleActivationPlanState):
    if state is RuleActivationPlanState.ACTIVATING:
        return RuleActivationPlanRecord.activation_publication_id
    if state is RuleActivationPlanState.RESTORING:
        return RuleActivationPlanRecord.restore_publication_id
    raise ValueError("activation plan is not executing a publication phase")


__all__ = ["SqlAlchemyRuleActivationPlanWorkQueue"]
