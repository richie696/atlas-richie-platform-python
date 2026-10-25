"""Concurrent-safe SQL claims for durable, secret-free publish commands."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from sqlalchemy import insert, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.mutate_rule_set import (
    RuleMutationKind,
    RuleMutationOperation,
    RuleOperationRejection,
    RuleOperationStatus,
)
from ...application.rule_publication_ports import RulePublishWorkClaim
from ...domain.configuration_source import ConfigurationSourceProvider
from ...domain.rule_activation_plans import RuleActivationPlanPhase
from ...domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationStage,
    RulePublication,
    advance_publication_phase,
    publication_phase_transition_allowed,
)
from ...domain.utc_time import is_wire_utc_millisecond_instant
from ...api.rule_publication_serializers import rule_publication_body
from .models import (
    AuditEventRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
)
from .rule_publication_mapping import publication_from_row
from .rule_publication_target_mapping import target_from_body

_MAX_CLAIM_BATCH = 100
_MAX_LEASE_MILLISECONDS = 300_000
_PUBLISH_WORK_FIELDS = frozenset(
    {
        "schemaVersion",
        "bindingId",
        "publicationId",
        "versionId",
        "versionChecksum",
        "expectedVersionId",
        "expectedChecksum",
        "expectedSourceRevision",
        "targetRevision",
        "sourceRevision",
        "target",
    }
)


class RulePublishOutboxCorrupt(RuntimeError):
    """Durable publish work no longer matches its finite stored schema."""


class RulePublishOutboxUnavailable(RuntimeError):
    """The durable publish queue could not safely claim work."""


class RulePublishClaimConflict(RuntimeError):
    """The worker claim is stale or the publication phase has moved."""


class SqlAlchemyRulePublishOutbox:
    """Claim pending publish operations using expiring, compare-and-set leases."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def claim_ready(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        supported_providers: frozenset[ConfigurationSourceProvider],
        limit: int = 1,
    ) -> tuple[RulePublishWorkClaim, ...]:
        """Claim oldest eligible commands; expired leases are fenced on takeover."""
        if (
            not is_wire_utc_millisecond_instant(now)
            or not is_wire_utc_millisecond_instant(lease_expires_at)
            or not 0 < (lease_expires_at - now).total_seconds() * 1000
            <= _MAX_LEASE_MILLISECONDS
            or type(limit) is not int
            or not 1 <= limit <= _MAX_CLAIM_BATCH
            or not isinstance(supported_providers, frozenset)
            or not supported_providers
            or any(
                not isinstance(provider, ConfigurationSourceProvider)
                for provider in supported_providers
            )
        ):
            raise ValueError("publish work claim bounds are invalid")

        try:
            async with self._engine.begin() as connection:
                eligible_lease = or_(
                    RuleMutationOperationRecord.work_claim_token.is_(None),
                    RuleMutationOperationRecord.work_lease_expires_at <= now,
                )
                selected = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.mutation_kind == "publish",
                        RuleMutationOperationRecord.work_payload.is_not(None),
                        RuleMutationOperationRecord.work_payload[
                            "target"
                        ]["provider"].as_string().in_(
                            tuple(provider.value for provider in supported_providers)
                        ),
                        eligible_lease,
                    )
                    .order_by(
                        RuleMutationOperationRecord.created_at,
                        RuleMutationOperationRecord.request_key,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                claims: list[RulePublishWorkClaim] = []
                for row in selected.mappings():
                    payload = row["work_payload"]
                    if not _valid_payload(payload, row["binding_id"]):
                        raise RulePublishOutboxCorrupt(
                            "durable publish work has an invalid schema"
                        )
                    token = str(uuid4())
                    claim_update = await connection.execute(
                        update(RuleMutationOperationRecord)
                        .where(
                            RuleMutationOperationRecord.request_key
                            == row["request_key"],
                            RuleMutationOperationRecord.status == "pending",
                            RuleMutationOperationRecord.mutation_kind == "publish",
                            eligible_lease,
                        )
                        .values(
                            work_claim_token=token,
                            work_lease_expires_at=lease_expires_at,
                            work_attempt_count=(
                                RuleMutationOperationRecord.work_attempt_count + 1
                            ),
                        )
                    )
                    if claim_update.rowcount != 1:
                        continue
                    claims.append(
                        RulePublishWorkClaim(
                            request_key=row["request_key"],
                            operation_id=row["operation_id"],
                            binding_id=row["binding_id"],
                            publication_id=payload["publicationId"],
                            version_id=payload["versionId"],
                            version_checksum=payload["versionChecksum"],
                            expected_version_id=payload["expectedVersionId"],
                            expected_checksum=payload["expectedChecksum"],
                            expected_source_revision=payload[
                                "expectedSourceRevision"
                            ],
                            target_revision=payload["targetRevision"],
                            source_revision=payload["sourceRevision"],
                            target=target_from_body(payload["target"]),
                            claim_token=token,
                            lease_expires_at=lease_expires_at,
                            attempt=row["work_attempt_count"] + 1,
                            origin_plan_id=row["origin_plan_id"],
                            origin_phase=(
                                RuleActivationPlanPhase(row["origin_phase"])
                                if row["origin_phase"] is not None
                                else None
                            ),
                        )
                    )
                return tuple(claims)
        except (RulePublishOutboxCorrupt, ValueError):
            raise
        except SQLAlchemyError:
            raise RulePublishOutboxUnavailable(
                "publish work could not be claimed"
            ) from None

    async def renew_claim(
        self,
        claim: RulePublishWorkClaim,
        *,
        now: datetime,
        lease_expires_at: datetime,
    ) -> RulePublishWorkClaim:
        """Extend one live claim only if both its token and lease revision match."""
        if (
            not isinstance(claim, RulePublishWorkClaim)
            or not is_wire_utc_millisecond_instant(now)
            or not is_wire_utc_millisecond_instant(lease_expires_at)
            or now >= claim.lease_expires_at
            or lease_expires_at <= claim.lease_expires_at
            or not 0 < (lease_expires_at - now).total_seconds() * 1000
            <= _MAX_LEASE_MILLISECONDS
        ):
            raise ValueError("publish work lease renewal bounds are invalid")
        try:
            async with self._engine.begin() as connection:
                renewed = await connection.execute(
                    update(RuleMutationOperationRecord)
                    .where(
                        RuleMutationOperationRecord.request_key == claim.request_key,
                        RuleMutationOperationRecord.operation_id == claim.operation_id,
                        RuleMutationOperationRecord.binding_id == claim.binding_id,
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.mutation_kind == "publish",
                        RuleMutationOperationRecord.work_claim_token
                        == claim.claim_token,
                        RuleMutationOperationRecord.work_lease_expires_at
                        == claim.lease_expires_at,
                    )
                    .values(work_lease_expires_at=lease_expires_at)
                )
                if renewed.rowcount != 1:
                    raise RulePublishClaimConflict(
                        "publish work claim is no longer current"
                    )
                return replace(claim, lease_expires_at=lease_expires_at)
        except RulePublishClaimConflict:
            raise
        except SQLAlchemyError:
            raise RulePublishOutboxUnavailable(
                "publish work lease could not be renewed"
            ) from None

    async def advance_claimed_phase(
        self,
        claim: RulePublishWorkClaim,
        phase_name: PublicationPhaseName,
        *,
        expected_state: PublicationStage,
        next_phase: PublicationPhase,
    ) -> RulePublication:
        """CAS a publication phase only while the exact claim lease is current."""
        if (
            not isinstance(claim, RulePublishWorkClaim)
            or not isinstance(phase_name, PublicationPhaseName)
            or not isinstance(expected_state, PublicationStage)
            or not isinstance(next_phase, PublicationPhase)
            or next_phase.observed_at is None
            or next_phase.observed_at >= claim.lease_expires_at
        ):
            raise ValueError("claimed publication transition is invalid")
        try:
            async with self._engine.begin() as connection:
                operation_result = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.request_key == claim.request_key,
                        RuleMutationOperationRecord.operation_id == claim.operation_id,
                        RuleMutationOperationRecord.binding_id == claim.binding_id,
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.mutation_kind == "publish",
                        RuleMutationOperationRecord.work_claim_token
                        == claim.claim_token,
                        RuleMutationOperationRecord.work_lease_expires_at
                        > next_phase.observed_at,
                    )
                    .with_for_update()
                )
                operation = operation_result.mappings().one_or_none()
                if operation is None or not _valid_payload(
                    operation["work_payload"], claim.binding_id
                ) or operation["work_payload"]["publicationId"] != claim.publication_id:
                    raise RulePublishClaimConflict(
                        "publish work claim is no longer current"
                    )

                publication_result = await connection.execute(
                    select(RulePublicationRecord.__table__)
                    .where(
                        RulePublicationRecord.binding_id == claim.binding_id,
                        RulePublicationRecord.publication_id == claim.publication_id,
                    )
                    .with_for_update()
                )
                row = publication_result.mappings().one_or_none()
                if row is None:
                    raise RulePublishClaimConflict(
                        "claimed publication no longer exists"
                    )
                current = publication_from_row(row)
                if (
                    getattr(current, phase_name.value) == next_phase
                    and publication_phase_transition_allowed(
                        expected_state, next_phase.state
                    )
                ):
                    return current
                updated = advance_publication_phase(
                    current,
                    phase_name,
                    expected_state=expected_state,
                    next_phase=next_phase,
                )
                state_column, observed_column, reason_column = _phase_columns(
                    phase_name
                )
                changed = await connection.execute(
                    update(RulePublicationRecord)
                    .where(
                        RulePublicationRecord.binding_id == claim.binding_id,
                        RulePublicationRecord.publication_id == claim.publication_id,
                        state_column == expected_state.value,
                    )
                    .values(
                        **{
                            state_column.key: next_phase.state.value,
                            observed_column.key: next_phase.observed_at,
                            reason_column.key: (
                                next_phase.reason.value
                                if next_phase.reason is not None
                                else None
                            ),
                        }
                    )
                )
                if changed.rowcount != 1:
                    raise RulePublishClaimConflict("publication phase has changed")
                return updated
        except RulePublishClaimConflict:
            raise
        except ValueError:
            raise RulePublishClaimConflict(
                "publication phase transition is invalid"
            ) from None
        except SQLAlchemyError:
            raise RulePublishOutboxUnavailable(
                "publication phase could not be persisted"
            ) from None

    async def complete_claimed_publication(
        self,
        claim: RulePublishWorkClaim,
        *,
        completed_at: datetime,
    ) -> RuleMutationOperation:
        """Commit a successful publication, original receipt and audit exactly once."""
        if (
            not isinstance(claim, RulePublishWorkClaim)
            or not is_wire_utc_millisecond_instant(completed_at)
            or completed_at >= claim.lease_expires_at
        ):
            raise ValueError("publish completion claim or time is invalid")
        try:
            async with self._engine.begin() as connection:
                operation_result = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.request_key == claim.request_key,
                        RuleMutationOperationRecord.operation_id == claim.operation_id,
                        RuleMutationOperationRecord.binding_id == claim.binding_id,
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.mutation_kind == "publish",
                        RuleMutationOperationRecord.work_claim_token
                        == claim.claim_token,
                        RuleMutationOperationRecord.work_lease_expires_at
                        > completed_at,
                    )
                    .with_for_update()
                )
                operation_row = operation_result.mappings().one_or_none()
                if operation_row is None or not _valid_payload(
                    operation_row["work_payload"], claim.binding_id
                ) or (
                    operation_row["work_payload"]["publicationId"]
                    != claim.publication_id
                ):
                    raise RulePublishClaimConflict(
                        "publish completion claim is no longer current"
                    )

                publication_result = await connection.execute(
                    select(RulePublicationRecord.__table__)
                    .where(
                        RulePublicationRecord.binding_id == claim.binding_id,
                        RulePublicationRecord.publication_id == claim.publication_id,
                    )
                    .with_for_update()
                )
                publication_row = publication_result.mappings().one_or_none()
                if publication_row is None:
                    raise RulePublishClaimConflict(
                        "publication facts are unavailable for completion"
                    )
                publication = publication_from_row(publication_row)
                if any(
                    phase.state is not PublicationStage.SUCCEEDED
                    or phase.observed_at is None
                    or phase.observed_at > completed_at
                    for phase in (
                        publication.validation,
                        publication.configuration_write,
                        publication.read_back,
                    )
                ):
                    raise RulePublishClaimConflict(
                        "publication is not fully verified for completion"
                    )

                completed = RuleMutationOperation(
                    claim.binding_id,
                    claim.request_key,
                    RuleOperationStatus.COMPLETED,
                    mutation_kind=RuleMutationKind.PUBLISH,
                    result=publication,
                )
                updated = await connection.execute(
                    update(RuleMutationOperationRecord)
                    .where(
                        RuleMutationOperationRecord.request_key == claim.request_key,
                        RuleMutationOperationRecord.operation_id == claim.operation_id,
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.work_claim_token
                        == claim.claim_token,
                        RuleMutationOperationRecord.work_lease_expires_at
                        > completed_at,
                    )
                    .values(
                        status=RuleOperationStatus.COMPLETED.value,
                        reason=None,
                        result={"publication": rule_publication_body(publication)},
                        work_payload=None,
                        work_claim_token=None,
                        work_lease_expires_at=None,
                    )
                )
                if updated.rowcount != 1:
                    raise RulePublishClaimConflict(
                        "publish operation changed before completion"
                    )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=str(uuid4()),
                        request_id=claim.operation_id,
                        actor_account_id=operation_row["actor_account_id"],
                        action=_publish_audit_action(claim),
                        outcome="completed",
                        target_kind=(
                            "rule_activation_plan"
                            if claim.origin_plan_id is not None
                            else "rule_binding"
                        ),
                        target_id=claim.origin_plan_id or claim.binding_id,
                        created_at=completed_at,
                    )
                )
                return completed
        except RulePublishClaimConflict:
            raise
        except SQLAlchemyError:
            raise RulePublishOutboxUnavailable(
                "publish operation could not be completed"
            ) from None

    async def reject_claimed_publication(
        self,
        claim: RulePublishWorkClaim,
        *,
        rejected_at: datetime,
        reason: RuleOperationRejection,
    ) -> RuleMutationOperation:
        """Terminally reject known failures without erasing publication evidence."""
        if (
            not isinstance(claim, RulePublishWorkClaim)
            or not is_wire_utc_millisecond_instant(rejected_at)
            or rejected_at >= claim.lease_expires_at
            or not isinstance(reason, RuleOperationRejection)
        ):
            raise ValueError("publish rejection claim or reason is invalid")
        try:
            async with self._engine.begin() as connection:
                operation_result = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.request_key == claim.request_key,
                        RuleMutationOperationRecord.operation_id == claim.operation_id,
                        RuleMutationOperationRecord.binding_id == claim.binding_id,
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.mutation_kind == "publish",
                        RuleMutationOperationRecord.work_claim_token
                        == claim.claim_token,
                        RuleMutationOperationRecord.work_lease_expires_at > rejected_at,
                    )
                    .with_for_update()
                )
                operation_row = operation_result.mappings().one_or_none()
                if operation_row is None or not _valid_payload(
                    operation_row["work_payload"], claim.binding_id
                ) or (
                    operation_row["work_payload"]["publicationId"]
                    != claim.publication_id
                ):
                    raise RulePublishClaimConflict(
                        "publish work claim is no longer current"
                    )

                publication_result = await connection.execute(
                    select(RulePublicationRecord.__table__)
                    .where(
                        RulePublicationRecord.binding_id == claim.binding_id,
                        RulePublicationRecord.publication_id == claim.publication_id,
                    )
                    .with_for_update()
                )
                publication_row = publication_result.mappings().one_or_none()
                if publication_row is None:
                    raise RulePublishClaimConflict(
                        "claimed publication no longer exists"
                    )
                publication = publication_from_row(publication_row)
                phases = (
                    publication.validation,
                    publication.configuration_write,
                    publication.read_back,
                )
                if (
                    not any(phase.state is PublicationStage.FAILED for phase in phases)
                    or any(
                        phase.state is PublicationStage.UNKNOWN
                        or (
                            phase.observed_at is not None
                            and phase.observed_at > rejected_at
                        )
                        for phase in phases
                    )
                ):
                    raise RulePublishClaimConflict(
                        "publication has no safely rejectable failed phase"
                    )

                rejected = RuleMutationOperation(
                    claim.binding_id,
                    claim.request_key,
                    RuleOperationStatus.REJECTED,
                    reason=reason,
                )
                changed = await connection.execute(
                    update(RuleMutationOperationRecord)
                    .where(
                        RuleMutationOperationRecord.request_key == claim.request_key,
                        RuleMutationOperationRecord.operation_id == claim.operation_id,
                        RuleMutationOperationRecord.status == "pending",
                        RuleMutationOperationRecord.work_claim_token
                        == claim.claim_token,
                        RuleMutationOperationRecord.work_lease_expires_at > rejected_at,
                    )
                    .values(
                        status=RuleOperationStatus.REJECTED.value,
                        reason=reason.value,
                        result=None,
                        work_payload=None,
                        work_claim_token=None,
                        work_lease_expires_at=None,
                    )
                )
                if changed.rowcount != 1:
                    raise RulePublishClaimConflict(
                        "publish operation changed before rejection"
                    )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=str(uuid4()),
                        request_id=claim.operation_id,
                        actor_account_id=operation_row["actor_account_id"],
                        action=_publish_audit_action(claim),
                        outcome="rejected",
                        target_kind=(
                            "rule_activation_plan"
                            if claim.origin_plan_id is not None
                            else "rule_binding"
                        ),
                        target_id=claim.origin_plan_id or claim.binding_id,
                        created_at=rejected_at,
                    )
                )
                return rejected
        except RulePublishClaimConflict:
            raise
        except SQLAlchemyError:
            raise RulePublishOutboxUnavailable(
                "publish operation could not be rejected"
            ) from None


def _publish_audit_action(claim: RulePublishWorkClaim) -> str:
    """Identify system-owned phases without attributing them to a browser user."""
    if claim.origin_phase is RuleActivationPlanPhase.ACTIVATION:
        return "rules.activation_plan.activate"
    if claim.origin_phase is RuleActivationPlanPhase.RESTORATION:
        return "rules.activation_plan.restore"
    return "rules.publish"


def _phase_columns(phase_name: PublicationPhaseName):
    return {
        PublicationPhaseName.VALIDATION: (
            RulePublicationRecord.validation_state,
            RulePublicationRecord.validation_observed_at,
            RulePublicationRecord.validation_reason,
        ),
        PublicationPhaseName.CONFIGURATION_WRITE: (
            RulePublicationRecord.write_state,
            RulePublicationRecord.write_observed_at,
            RulePublicationRecord.write_reason,
        ),
        PublicationPhaseName.READ_BACK: (
            RulePublicationRecord.read_back_state,
            RulePublicationRecord.read_back_observed_at,
            RulePublicationRecord.read_back_reason,
        ),
    }[phase_name]


def _valid_payload(value: object, binding_id: str) -> bool:
    if not isinstance(value, dict) or set(value) != _PUBLISH_WORK_FIELDS:
        return False
    return (
        type(value["schemaVersion"]) is int
        and value["schemaVersion"] == 2
        and value["bindingId"] == binding_id
        and all(
            isinstance(value[field], str) and bool(value[field].strip())
            for field in (
                "bindingId",
                "publicationId",
                "versionId",
                "versionChecksum",
                "expectedChecksum",
                "targetRevision",
                "sourceRevision",
            )
        )
        and (
            value["expectedVersionId"] is None
            or (
                isinstance(value["expectedVersionId"], str)
                and bool(value["expectedVersionId"].strip())
            )
        )
        and (
            value["expectedSourceRevision"] is None
            or (
                isinstance(value["expectedSourceRevision"], str)
                and bool(value["expectedSourceRevision"].strip())
            )
        )
        and _payload_target_matches(value)
    )


def _payload_target_matches(value: dict[str, object]) -> bool:
    try:
        target = target_from_body(value["target"])
    except (KeyError, TypeError, ValueError):
        return False
    return target.binding_id == value["bindingId"]


__all__ = [
    "RulePublishOutboxCorrupt",
    "RulePublishClaimConflict",
    "RulePublishOutboxUnavailable",
    "RulePublishWorkClaim",
    "SqlAlchemyRulePublishOutbox",
]
