"""SQL authority for idempotent rule drafts and exact original receipts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
import hashlib
import hmac
import json
from types import MappingProxyType
from typing import Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.mutate_rule_set import (
    CancelRuleActivationPlan,
    ConfigureRulePublicationTarget,
    CreateRuleActivationPlan,
    DeleteRuleDraft,
    FreezeRuleVersion,
    FrozenRuleVersionResult,
    PublishRuleVersion,
    RuleMutation,
    RuleMutationAuthority,
    RuleMutationAuthorityUnavailable,
    RuleMutationBindingReader,
    RuleMutationCommand,
    RuleMutationForbidden,
    RuleMutationIdempotencyConflict,
    RuleMutationKind,
    RuleMutationOperation,
    RuleMutationResult,
    RuleMutationUnauthenticated,
    RuleOperationRejection,
    RuleOperationStatus,
    SaveRuleDraft,
)
from ...application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationTargetReader,
)
from ...application.rule_activation_plan_ports import (
    RuleActivationPlanClaim,
    RuleActivationPlanClaimConflict,
    ScheduledPublicationEnqueue,
    ScheduledPublicationState,
)
from ...api.rule_draft_serializers import stored_rule_draft_body
from ...api.rule_snapshot_serializers import rule_record_body
from ...api.rule_version_serializers import rule_set_version_body
from ...domain.rule_candidates import (
    CandidateRule,
    RuleSetCandidate,
    candidate_checksum,
)
from ...domain.rule_drafts import StoredRuleDraft
from ...domain.rule_bindings import RuleBinding
from ...domain.rule_snapshots import RuleRecord
from ...domain.rule_versions import RuleSetVersion
from ...domain.rule_publications import (
    PublicationPhase,
    PublicationStage,
    RulePublication,
)
from ...domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from ...domain.rule_activation_plans import (
    RuleActivationPlan,
    RuleActivationPlanPhase,
    RuleActivationPlanState,
)
from .rule_draft_mapping import draft_body_from_row, draft_from_body
from .rule_version_mapping import version_from_body
from .rule_activation_plan_mapping import (
    activation_plan_body_from_row,
    activation_plan_from_body,
    activation_plan_result_body,
)
from .rule_publication_mapping import publication_from_body
from .rule_publication_target_mapping import target_body, target_from_body
from .models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RuleDraftRecord,
    RuleActivationPlanRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
    RegisteredConfigurationSourceRecord,
    RulePublicationTargetRecord,
)

_FINGERPRINT_DOMAIN = b"atlas-richie-sentinel-rule-command:v1\x00"
_PUBLISH_WORK_SCHEMA_VERSION = 2
_CANCELLABLE_ACTIVATION_PLAN_STATES = tuple(
    state.value
    for state in (
        RuleActivationPlanState.PENDING,
        RuleActivationPlanState.BLOCKED,
    )
)


class SqlAlchemyRuleMutationStore(RuleMutationAuthority):
    """Atomically persist draft changes, original receipts, and bounded audit facts."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        fingerprint_keys: Mapping[str, bytes],
        active_fingerprint_key_id: str,
        binding_reader: RuleMutationBindingReader,
        publication_target_reader: RulePublicationTargetReader | None = None,
    ) -> None:
        copied_keys = dict(fingerprint_keys)
        if (
            not copied_keys
            or active_fingerprint_key_id not in copied_keys
            or any(
                not key_id
                or not isinstance(key, bytes)
                or len(key) < 32
                for key_id, key in copied_keys.items()
            )
        ):
            raise ValueError("rule-command fingerprint keys are invalid")
        self._engine = engine
        self._binding_reader = binding_reader
        self._publication_target_reader = publication_target_reader
        self._fingerprint_keys = MappingProxyType(copied_keys)
        self._active_fingerprint_key_id = active_fingerprint_key_id

    async def enqueue_scheduled_publication(
        self, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> ScheduledPublicationEnqueue:
        """Create or recover a plan-phase publish without inventing a user session."""
        if not isinstance(claim, RuleActivationPlanClaim):
            raise ValueError("activation plan claim is required")
        instant = _millisecond_utc(now)
        phase, target_version_id, baseline_version_id = _scheduled_phase(claim)
        request_key = _scheduled_request_key(claim.plan.id, phase)
        publication_id = _scheduled_publication_id(claim.plan.id, phase)

        existing = await self._read_scheduled_operation(
            claim, phase=phase, request_key=request_key, now=instant
        )
        if existing is not None:
            return existing

        binding = await self._read_binding(claim.plan.binding_id)
        publication_target = await self._read_publication_target(
            claim.plan.binding_id
        )
        version_rows = await self._read_scheduled_versions(
            claim.plan.binding_id,
            target_version_id=target_version_id,
            baseline_version_id=baseline_version_id,
        )
        target_version = version_rows.get(target_version_id)
        baseline_version = version_rows.get(baseline_version_id)
        mutation = PublishRuleVersion(
            version_id=target_version_id,
            version_checksum=target_version["checksum"] if target_version else "missing",
            expected_version_id=baseline_version_id,
            expected_checksum=baseline_version["checksum"] if baseline_version else "missing",
            expected_source_revision=(
                publication_target.source_revision
                if publication_target is not None
                else None
            ),
            reason=f"scheduled activation plan {claim.plan.id} {phase.value}",
        )
        command = RuleMutationCommand(
            binding_id=claim.plan.binding_id,
            request_key=request_key,
            mutation=mutation,
        )
        fingerprints = self._fingerprints(command)
        operation_id = str(uuid4())
        audit_event_id = str(uuid4())

        try:
            async with self._engine.begin() as connection:
                await self._lock_scheduled_claim(connection, claim, now=instant)
                previous = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.origin_plan_id == claim.plan.id,
                        RuleMutationOperationRecord.origin_phase == phase.value,
                    )
                    .with_for_update()
                )
                previous_row = previous.mappings().one_or_none()
                if previous_row is not None:
                    return self._recover_scheduled_operation(
                        previous_row,
                        claim=claim,
                        phase=phase,
                        request_key=request_key,
                    )

                if binding is None:
                    operation = _rejected(command, RuleOperationRejection.NOT_FOUND)
                    audit_target_id = claim.plan.id
                elif target_version is None or baseline_version is None:
                    operation = _rejected(command, RuleOperationRejection.NOT_FOUND)
                    audit_target_id = claim.plan.id
                else:
                    operation, _ = await self._accept_publish(
                        connection,
                        command=command,
                        mutation=mutation,
                        binding=binding,
                        publication_id=publication_id,
                        publication_target=publication_target,
                        now=instant,
                    )
                    audit_target_id = claim.plan.id

                await connection.execute(
                    insert(RuleMutationOperationRecord).values(
                        request_key=request_key,
                        operation_id=operation_id,
                        binding_id=claim.plan.binding_id,
                        actor_account_id=None,
                        session_hash=None,
                        origin_plan_id=claim.plan.id,
                        origin_phase=phase.value,
                        fingerprint_key_id=self._active_fingerprint_key_id,
                        fingerprint_digest=fingerprints[
                            self._active_fingerprint_key_id
                        ],
                        mutation_kind=RuleMutationKind.PUBLISH.value,
                        status=operation.status.value,
                        reason=operation.reason.value if operation.reason else None,
                        result=_operation_result(operation),
                        work_payload=_publish_work_payload(
                            command,
                            operation,
                            publication_id,
                            publication_target,
                        ),
                        created_at=instant,
                    )
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=audit_event_id,
                        request_id=request_key,
                        actor_account_id=None,
                        action=_scheduled_audit_action(phase),
                        outcome=_audit_outcome(operation.status),
                        target_kind="rule_activation_plan",
                        target_id=audit_target_id or claim.plan.id,
                        created_at=instant,
                    )
                )
                return _scheduled_publication_result(operation, publication_id)
        except RuleActivationPlanClaimConflict:
            raise
        except IntegrityError:
            recovered = await self._read_scheduled_operation(
                claim, phase=phase, request_key=request_key, now=instant
            )
            if recovered is None:
                raise RuleMutationAuthorityUnavailable(
                    "scheduled publication operation could not be confirmed"
                ) from None
            return recovered
        except (SQLAlchemyError, TypeError, ValueError):
            raise RuleMutationAuthorityUnavailable(
                "scheduled publication operation is unavailable"
            ) from None

    async def _read_scheduled_versions(
        self, binding_id: str, *, target_version_id: str, baseline_version_id: str
    ) -> dict[str, dict[str, object]]:
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(
                        RuleSetVersionRecord.version_id,
                        RuleSetVersionRecord.binding_id,
                        RuleSetVersionRecord.checksum,
                    ).where(
                        RuleSetVersionRecord.version_id.in_(
                            (target_version_id, baseline_version_id)
                        )
                    )
                )
                rows = result.mappings().all()
        except SQLAlchemyError:
            raise RuleMutationAuthorityUnavailable(
                "scheduled publication versions are unavailable"
            ) from None
        return {
            row["version_id"]: dict(row)
            for row in rows
            if row["binding_id"] == binding_id
        }

    async def _read_scheduled_operation(
        self,
        claim: RuleActivationPlanClaim,
        *,
        phase: RuleActivationPlanPhase,
        request_key: str,
        now: datetime,
    ) -> ScheduledPublicationEnqueue | None:
        try:
            async with self._engine.begin() as connection:
                await self._lock_scheduled_claim(connection, claim, now=now)
                result = await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.origin_plan_id == claim.plan.id,
                        RuleMutationOperationRecord.origin_phase == phase.value,
                    )
                )
                row = result.mappings().one_or_none()
        except RuleActivationPlanClaimConflict:
            raise
        except SQLAlchemyError:
            raise RuleMutationAuthorityUnavailable(
                "scheduled publication history is unavailable"
            ) from None
        if row is None:
            return None
        return self._recover_scheduled_operation(
            row, claim=claim, phase=phase, request_key=request_key
        )

    def _recover_scheduled_operation(
        self,
        row,
        *,
        claim: RuleActivationPlanClaim,
        phase: RuleActivationPlanPhase,
        request_key: str,
    ) -> ScheduledPublicationEnqueue:
        if (
            row["request_key"] != request_key
            or row["binding_id"] != claim.plan.binding_id
            or row["origin_plan_id"] != claim.plan.id
            or row["origin_phase"] != phase.value
            or row["actor_account_id"] is not None
            or row["session_hash"] is not None
            or row["mutation_kind"] != RuleMutationKind.PUBLISH.value
        ):
            raise RuleMutationAuthorityUnavailable(
                "scheduled publication history is inconsistent"
            )
        try:
            publication_id = _scheduled_publication_id(
                claim.plan.id, phase
            )
            operation = _operation_from_row(row)
            if operation.status is RuleOperationStatus.PENDING:
                publication_id = row["work_payload"]["publicationId"]
            elif operation.status is RuleOperationStatus.COMPLETED:
                if not isinstance(operation.result, RulePublication):
                    raise ValueError("scheduled publish receipt is invalid")
                publication_id = operation.result.id
            if publication_id != _scheduled_publication_id(claim.plan.id, phase):
                raise ValueError("scheduled publication identity is inconsistent")
            return _scheduled_publication_result(
                operation,
                publication_id,
            )
        except (KeyError, TypeError, ValueError):
            raise RuleMutationAuthorityUnavailable(
                "scheduled publication history is invalid"
            ) from None

    @staticmethod
    async def _lock_scheduled_claim(
        connection, claim: RuleActivationPlanClaim, *, now: datetime
    ) -> None:
        result = await connection.execute(
            select(RuleActivationPlanRecord.__table__)
            .where(
                RuleActivationPlanRecord.plan_id == claim.plan.id,
                RuleActivationPlanRecord.revision == claim.plan.revision,
                RuleActivationPlanRecord.binding_id == claim.plan.binding_id,
                RuleActivationPlanRecord.version_id == claim.plan.version_id,
                RuleActivationPlanRecord.restore_version_id
                == claim.plan.restore_version_id,
                RuleActivationPlanRecord.state == claim.plan.state.value,
                RuleActivationPlanRecord.claim_token == claim.claim_token,
                RuleActivationPlanRecord.claim_lease_expires_at > now,
            )
            .with_for_update()
        )
        if result.mappings().one_or_none() is None:
            raise RuleActivationPlanClaimConflict(
                "activation plan claim is no longer current"
            )

    async def mutate(
        self,
        command: RuleMutationCommand,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RuleMutationOperation:
        """Reauthorize each write and commit its state, receipt and audit together."""
        instant = _millisecond_utc(now)
        fingerprints = self._fingerprints(command)
        operation_id = str(uuid4())
        publication_id = (
            str(uuid4()) if isinstance(command.mutation, PublishRuleVersion) else None
        )
        audit_event_id = str(uuid4())
        try:
            # Replays do not depend on the current state or availability of the
            # external binding directory. Keep this authorization/read short.
            async with self._engine.begin() as connection:
                await self._authorize_write(
                    connection,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    csrf_digest=csrf_digest,
                    now=instant,
                )
                previous = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.request_key
                        == command.request_key
                    )
                    .with_for_update()
                )
                previous_row = previous.mappings().one_or_none()
                if previous_row is not None:
                    return self._recover(
                        previous_row,
                        command=command,
                        actor_id=actor_id,
                        session_digest=session_digest,
                        fingerprints=fingerprints,
                    )

            binding = await self._read_binding(command.binding_id)
            publication_target = (
                await self._read_publication_target(command.binding_id)
                if isinstance(command.mutation, PublishRuleVersion)
                else None
            )

            # Reauthorize and recheck idempotency after the external read: the
            # session may have been revoked, or a concurrent request may have
            # committed the same request key while the directory was queried.
            async with self._engine.begin() as connection:
                await self._authorize_write(
                    connection,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    csrf_digest=csrf_digest,
                    now=instant,
                )
                previous = await connection.execute(
                    select(RuleMutationOperationRecord.__table__)
                    .where(
                        RuleMutationOperationRecord.request_key
                        == command.request_key
                    )
                    .with_for_update()
                )
                previous_row = previous.mappings().one_or_none()
                if previous_row is not None:
                    return self._recover(
                        previous_row,
                        command=command,
                        actor_id=actor_id,
                        session_digest=session_digest,
                        fingerprints=fingerprints,
                    )

                operation, target_id = await self._apply(
                    connection,
                    command=command,
                    actor_id=actor_id,
                    binding=binding,
                    now=instant,
                    publication_id=publication_id,
                    publication_target=publication_target,
                )
                active_fingerprint = fingerprints[self._active_fingerprint_key_id]
                await connection.execute(
                    insert(RuleMutationOperationRecord).values(
                        request_key=command.request_key,
                        operation_id=operation_id,
                        binding_id=command.binding_id,
                        actor_account_id=actor_id,
                        session_hash=session_digest,
                        fingerprint_key_id=self._active_fingerprint_key_id,
                        fingerprint_digest=active_fingerprint,
                        mutation_kind=_mutation_kind(command.mutation).value,
                        status=operation.status.value,
                        reason=operation.reason.value if operation.reason else None,
                        result=_operation_result(operation),
                        work_payload=_publish_work_payload(
                            command, operation, publication_id, publication_target
                        ),
                        created_at=instant,
                    )
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=audit_event_id,
                        request_id=request_id,
                        actor_account_id=actor_id,
                        action=f"rules.{_mutation_kind(command.mutation).value}",
                        outcome=_audit_outcome(operation.status),
                        target_kind="rule_binding",
                        target_id=target_id or command.binding_id,
                        created_at=instant,
                    )
                )
                return operation
        except (
            RuleMutationForbidden,
            RuleMutationIdempotencyConflict,
            RuleMutationUnauthenticated,
            RuleMutationAuthorityUnavailable,
        ):
            raise
        except IntegrityError:
            return await self._recover_race(
                command,
                actor_id=actor_id,
                session_digest=session_digest,
                csrf_digest=csrf_digest,
                now=instant,
                fingerprints=fingerprints,
            )
        except (SQLAlchemyError, TypeError, ValueError):
            raise RuleMutationAuthorityUnavailable(
                "rule mutation authority is unavailable"
            ) from None

    async def read_operation(
        self,
        binding_id: str,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
    ) -> RuleMutationOperation | None:
        """Read a command receipt only within its original actor and session."""
        try:
            async with self._engine.begin() as connection:
                await self._authorize_read(
                    connection, actor_id=actor_id, session_digest=session_digest
                )
                result = await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key == request_key,
                        RuleMutationOperationRecord.binding_id == binding_id,
                        RuleMutationOperationRecord.actor_account_id == actor_id,
                        RuleMutationOperationRecord.session_hash == session_digest,
                    )
                )
                row = result.mappings().one_or_none()
        except (RuleMutationForbidden, RuleMutationUnauthenticated):
            raise
        except SQLAlchemyError:
            raise RuleMutationAuthorityUnavailable(
                "rule operation history is unavailable"
            ) from None
        if row is None:
            return None
        try:
            return _operation_from_row(row)
        except (KeyError, TypeError, ValueError):
            raise RuleMutationAuthorityUnavailable(
                "rule operation history is invalid"
            ) from None

    async def _authorize_write(
        self, connection, *, actor_id: str, session_digest: str,
        csrf_digest: str, now: datetime,
    ) -> None:
        result = await connection.execute(
            select(AccountRecord.role_id, AuthenticationSessionRecord.csrf_hash)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > now,
            )
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            raise RuleMutationUnauthenticated("browser session is inactive")
        if not hmac.compare_digest(row.csrf_hash, csrf_digest):
            raise RuleMutationForbidden("CSRF proof is invalid")
        if row.role_id != "admin":
            raise RuleMutationForbidden("administrator role is required")

    async def _read_binding(self, binding_id: str) -> RuleBinding | None:
        """Resolve the external binding without holding a SQL transaction."""
        try:
            binding = await self._binding_reader.read_rule_binding(binding_id)
        except Exception:
            raise RuleMutationAuthorityUnavailable(
                "rule binding authority is unavailable"
            ) from None
        if binding is not None and (
            not isinstance(binding, RuleBinding) or binding.id != binding_id
        ):
            raise RuleMutationAuthorityUnavailable(
                "rule binding authority returned an invalid identity"
            )
        return binding

    async def _read_publication_target(
        self, binding_id: str
    ) -> VersionedRulePublicationTarget | None:
        if self._publication_target_reader is None:
            return None
        try:
            target = await self._publication_target_reader.read_rule_publication_target(
                binding_id
            )
        except RulePublicationAuthorityUnavailable:
            raise RuleMutationAuthorityUnavailable(
                "rule publication target authority is unavailable"
            ) from None
        if target is not None and not isinstance(
            target, VersionedRulePublicationTarget
        ):
            raise RuleMutationAuthorityUnavailable(
                "rule publication target authority is unavailable"
            )
        return target

    async def _authorize_read(
        self, connection, *, actor_id: str, session_digest: str
    ) -> None:
        result = await connection.execute(
            select(AccountRecord.role_id)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        role_id = result.scalar_one_or_none()
        if role_id is None:
            raise RuleMutationUnauthenticated("browser session is inactive")
        if role_id != "admin":
            raise RuleMutationForbidden("administrator role is required")

    async def _apply(
        self, connection, *, command: RuleMutationCommand,
        actor_id: str, binding: RuleBinding | None, now: datetime,
        publication_id: str | None,
        publication_target: VersionedRulePublicationTarget | None,
    ) -> tuple[RuleMutationOperation, str | None]:
        mutation = command.mutation
        if binding is None:
            return (
                _rejected(command, RuleOperationRejection.NOT_FOUND),
                command.binding_id,
            )
        if isinstance(mutation, SaveRuleDraft):
            if (
                mutation.candidate.kind is not binding.kind
                or mutation.candidate.profile != binding.profile
            ):
                return (
                    _rejected(command, RuleOperationRejection.VALIDATION),
                    command.binding_id,
                )
            return await self._save_draft(
                connection, command=command, mutation=mutation,
                actor_id=actor_id, now=now,
            )
        if isinstance(mutation, DeleteRuleDraft):
            return await self._delete_draft(connection, command, mutation)
        if isinstance(mutation, FreezeRuleVersion):
            return await self._freeze_version(
                connection,
                command=command,
                mutation=mutation,
                binding=binding,
                actor_id=actor_id,
                now=now,
            )
        if isinstance(mutation, PublishRuleVersion):
            if publication_id is None:
                raise ValueError("publish command lacks its durable publication id")
            return await self._accept_publish(
                connection,
                command=command,
                mutation=mutation,
                binding=binding,
                publication_id=publication_id,
                publication_target=publication_target,
                now=now,
            )
        if isinstance(mutation, CreateRuleActivationPlan):
            return await self._create_activation_plan(
                connection,
                command=command,
                mutation=mutation,
                actor_id=actor_id,
                now=now,
            )
        if isinstance(mutation, CancelRuleActivationPlan):
            return await self._cancel_activation_plan(
                connection, command=command, mutation=mutation
            )
        if isinstance(mutation, ConfigureRulePublicationTarget):
            return await self._configure_publication_target(
                connection,
                command=command,
                mutation=mutation,
                binding=binding,
                now=now,
            )
        return (
            RuleMutationOperation(
                command.binding_id,
                command.request_key,
                RuleOperationStatus.REJECTED,
                reason=RuleOperationRejection.UNSUPPORTED,
            ),
            None,
        )

    async def _save_draft(
        self, connection, *, command: RuleMutationCommand,
        mutation: SaveRuleDraft, actor_id: str, now: datetime,
    ) -> tuple[RuleMutationOperation, str]:
        candidate = mutation.candidate
        if candidate.binding_id != command.binding_id:
            return (
                _rejected(command, RuleOperationRejection.VALIDATION),
                command.binding_id,
            )
        draft_id = mutation.draft_id or str(uuid4())
        revision = str(uuid4())
        records = tuple(
            RuleRecord(item.record_id or str(uuid4()), item.rule)
            for item in candidate.rules
        )
        draft = StoredRuleDraft(
            id=draft_id,
            binding_id=command.binding_id,
            revision=revision,
            kind=candidate.kind,
            profile=candidate.profile,
            base_version_id=candidate.base_version_id,
            base_checksum=candidate.base_checksum,
            source_revision=candidate.source_revision,
            updated_at=now,
            records=records,
        )
        values = {
            "draft_id": draft.id,
            "binding_id": draft.binding_id,
            "revision": draft.revision,
            "kind": draft.kind.value,
            "profile": draft.profile,
            "base_version_id": draft.base_version_id,
            "base_checksum": draft.base_checksum,
            "source_revision": draft.source_revision,
            "records": [rule_record_body(record) for record in draft.records],
            "updated_at": draft.updated_at,
            "updated_by_account_id": actor_id,
        }
        if mutation.draft_id is None:
            count = await connection.scalar(
                select(func.count())
                .select_from(RuleDraftRecord)
                .where(RuleDraftRecord.binding_id == command.binding_id)
            )
            if count is None or count >= 1_000:
                return _rejected(command, RuleOperationRejection.VALIDATION), draft.id
            await connection.execute(insert(RuleDraftRecord).values(**values))
        else:
            current = await connection.execute(
                select(RuleDraftRecord.revision, RuleDraftRecord.binding_id)
                .where(RuleDraftRecord.draft_id == mutation.draft_id)
                .with_for_update()
            )
            current_row = current.one_or_none()
            if current_row is None or current_row.binding_id != command.binding_id:
                return (
                    _rejected(command, RuleOperationRejection.NOT_FOUND),
                    mutation.draft_id,
                )
            if current_row.revision != mutation.expected_revision:
                return (
                    _rejected(command, RuleOperationRejection.CONFLICT),
                    mutation.draft_id,
                )
            changed = await connection.execute(
                update(RuleDraftRecord)
                .where(
                    RuleDraftRecord.draft_id == mutation.draft_id,
                    RuleDraftRecord.binding_id == command.binding_id,
                    RuleDraftRecord.revision == mutation.expected_revision,
                )
                .values(
                    **{
                        key: value
                        for key, value in values.items()
                        if key != "draft_id"
                    }
                )
            )
            if changed.rowcount != 1:
                return (
                    _rejected(command, RuleOperationRejection.CONFLICT),
                    mutation.draft_id,
                )
        operation = RuleMutationOperation(
            command.binding_id,
            command.request_key,
            RuleOperationStatus.COMPLETED,
            mutation_kind=RuleMutationKind.SAVE_DRAFT,
            result=draft,
        )
        return operation, draft.id

    async def _accept_publish(
        self,
        connection,
        *,
        command: RuleMutationCommand,
        mutation: PublishRuleVersion,
        binding: RuleBinding,
        publication_id: str,
        publication_target: VersionedRulePublicationTarget | None,
        now: datetime,
    ) -> tuple[RuleMutationOperation, str]:
        """Validate frozen identities and atomically persist awaiting work."""
        if publication_target is None:
            return (
                _rejected(command, RuleOperationRejection.UNAVAILABLE),
                command.binding_id,
            )
        resolved_target = publication_target.target
        if (
            resolved_target.binding_id != command.binding_id
            or resolved_target.source_id != binding.source_id
        ):
            raise RuleMutationAuthorityUnavailable(
                "rule publication target authority is unavailable"
            )
        target_result = await connection.execute(
            select(
                RuleSetVersionRecord.binding_id,
                RuleSetVersionRecord.kind,
                RuleSetVersionRecord.profile,
                RuleSetVersionRecord.checksum,
                RuleSetVersionRecord.validation_id,
            )
            .where(RuleSetVersionRecord.version_id == mutation.version_id)
            .with_for_update()
        )
        target = target_result.one_or_none()
        if target is None or target.binding_id != command.binding_id:
            return _rejected(command, RuleOperationRejection.NOT_FOUND), mutation.version_id
        if target.checksum != mutation.version_checksum:
            return _rejected(command, RuleOperationRejection.CONFLICT), mutation.version_id
        if target.kind != binding.kind.value or target.profile != binding.profile:
            return _rejected(command, RuleOperationRejection.VALIDATION), mutation.version_id

        validation_result = await connection.execute(
            select(
                RuleValidationReceiptRecord.binding_id,
                RuleValidationReceiptRecord.profile,
                RuleValidationReceiptRecord.candidate_checksum,
                RuleValidationReceiptRecord.is_publishable,
            )
            .where(
                RuleValidationReceiptRecord.validation_id == target.validation_id
            )
            .with_for_update()
        )
        validation = validation_result.one_or_none()
        if (
            validation is None
            or validation.binding_id != command.binding_id
            or validation.profile != binding.profile
            or validation.candidate_checksum != target.checksum
            or validation.is_publishable is not True
        ):
            return _rejected(command, RuleOperationRejection.VALIDATION), mutation.version_id

        if mutation.expected_version_id is not None:
            baseline_result = await connection.execute(
                select(
                    RuleSetVersionRecord.binding_id,
                    RuleSetVersionRecord.checksum,
                )
                .where(
                    RuleSetVersionRecord.version_id == mutation.expected_version_id
                )
                .with_for_update()
            )
            baseline = baseline_result.one_or_none()
            if (
                baseline is None
                or baseline.binding_id != command.binding_id
                or baseline.checksum != mutation.expected_checksum
            ):
                return _rejected(command, RuleOperationRejection.CONFLICT), mutation.version_id

        publication = RulePublication(
            id=publication_id,
            binding_id=command.binding_id,
            target_version_id=mutation.version_id,
            target_checksum=target.checksum,
            base_version_id=mutation.expected_version_id,
            created_at=now,
            validation=PublicationPhase(PublicationStage.AWAITING, None, None),
            configuration_write=PublicationPhase(
                PublicationStage.AWAITING, None, None
            ),
            read_back=PublicationPhase(PublicationStage.AWAITING, None, None),
        )
        await connection.execute(
            insert(RulePublicationRecord).values(
                publication_id=publication.id,
                binding_id=publication.binding_id,
                target_version_id=publication.target_version_id,
                target_checksum=publication.target_checksum,
                base_version_id=publication.base_version_id,
                created_at=publication.created_at,
                validation_state=publication.validation.state.value,
                validation_observed_at=publication.validation.observed_at,
                validation_reason=None,
                write_state=publication.configuration_write.state.value,
                write_observed_at=publication.configuration_write.observed_at,
                write_reason=None,
                read_back_state=publication.read_back.state.value,
                read_back_observed_at=publication.read_back.observed_at,
                read_back_reason=None,
            )
        )
        return (
            RuleMutationOperation(
                command.binding_id,
                command.request_key,
                RuleOperationStatus.PENDING,
            ),
            publication.id,
        )

    async def _delete_draft(
        self, connection, command: RuleMutationCommand,
        mutation: DeleteRuleDraft,
    ) -> tuple[RuleMutationOperation, str]:
        result = await connection.execute(
            select(RuleDraftRecord.revision, RuleDraftRecord.binding_id)
            .where(RuleDraftRecord.draft_id == mutation.draft_id)
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None or row.binding_id != command.binding_id:
            return (
                _rejected(command, RuleOperationRejection.NOT_FOUND),
                mutation.draft_id,
            )
        if row.revision != mutation.expected_revision:
            return (
                _rejected(command, RuleOperationRejection.CONFLICT),
                mutation.draft_id,
            )
        deleted = await connection.execute(
            delete(RuleDraftRecord).where(
                RuleDraftRecord.draft_id == mutation.draft_id,
                RuleDraftRecord.binding_id == command.binding_id,
                RuleDraftRecord.revision == mutation.expected_revision,
            )
        )
        if deleted.rowcount != 1:
            return (
                _rejected(command, RuleOperationRejection.CONFLICT),
                mutation.draft_id,
            )
        return (
            RuleMutationOperation(
                command.binding_id,
                command.request_key,
                RuleOperationStatus.COMPLETED,
                mutation_kind=RuleMutationKind.DELETE_DRAFT,
                result=mutation.draft_id,
            ),
            mutation.draft_id,
        )

    async def _freeze_version(
        self,
        connection,
        *,
        command: RuleMutationCommand,
        mutation: FreezeRuleVersion,
        binding: RuleBinding,
        actor_id: str,
        now: datetime,
    ) -> tuple[RuleMutationOperation, str]:
        draft_result = await connection.execute(
            select(RuleDraftRecord.__table__)
            .where(
                RuleDraftRecord.draft_id == mutation.draft_id,
                RuleDraftRecord.binding_id == command.binding_id,
            )
            .with_for_update()
        )
        draft_row = draft_result.mappings().one_or_none()
        if draft_row is None:
            return (
                _rejected(command, RuleOperationRejection.NOT_FOUND),
                mutation.draft_id,
            )
        if draft_row["revision"] != mutation.expected_revision:
            return (
                _rejected(command, RuleOperationRejection.CONFLICT),
                mutation.draft_id,
            )
        draft = draft_from_body(draft_body_from_row(draft_row))
        if draft.kind is not binding.kind or draft.profile != binding.profile:
            return (
                _rejected(command, RuleOperationRejection.VALIDATION),
                mutation.draft_id,
            )
        candidate = RuleSetCandidate(
            binding_id=draft.binding_id,
            profile=draft.profile,
            kind=draft.kind,
            base_version_id=draft.base_version_id,
            base_checksum=draft.base_checksum,
            source_revision=draft.source_revision,
            rules=tuple(
                CandidateRule(record.id, record.rule) for record in draft.records
            ),
        )
        computed_checksum = candidate_checksum(candidate)
        if computed_checksum != mutation.candidate_checksum:
            return (
                _rejected(command, RuleOperationRejection.VALIDATION),
                mutation.draft_id,
            )
        validation_result = await connection.execute(
            select(RuleValidationReceiptRecord.__table__)
            .where(
                RuleValidationReceiptRecord.validation_id == mutation.validation_id
            )
            .with_for_update()
        )
        receipt = validation_result.mappings().one_or_none()
        if receipt is None or any(
            (
                receipt["binding_id"] != draft.binding_id,
                receipt["profile"] != draft.profile,
                receipt["base_checksum"] != draft.base_checksum,
                receipt["candidate_checksum"] != computed_checksum,
                receipt["is_publishable"] is not True,
            )
        ):
            return (
                _rejected(command, RuleOperationRejection.VALIDATION),
                mutation.draft_id,
            )
        version_count = await connection.scalar(
            select(func.count())
            .select_from(RuleSetVersionRecord)
            .where(RuleSetVersionRecord.binding_id == command.binding_id)
        )
        if version_count is None or version_count >= 1_000:
            return (
                _rejected(command, RuleOperationRejection.VALIDATION),
                mutation.draft_id,
            )
        version = RuleSetVersion(
            id=str(uuid4()),
            binding_id=draft.binding_id,
            kind=draft.kind,
            profile=draft.profile,
            base_version_id=draft.base_version_id,
            checksum=computed_checksum,
            name=mutation.name,
            note=mutation.note,
            created_at=now,
            created_by_id=actor_id,
            records=draft.records,
        )
        await connection.execute(
            insert(RuleSetVersionRecord).values(
                version_id=version.id,
                binding_id=version.binding_id,
                kind=version.kind.value,
                profile=version.profile,
                base_version_id=version.base_version_id,
                checksum=version.checksum,
                name=version.name,
                note=version.note,
                validation_id=mutation.validation_id,
                records=[rule_record_body(record) for record in version.records],
                created_at=version.created_at,
                created_by_account_id=version.created_by_id,
            )
        )
        return (
            RuleMutationOperation(
                command.binding_id,
                command.request_key,
                RuleOperationStatus.COMPLETED,
                mutation_kind=RuleMutationKind.FREEZE_VERSION,
                result=FrozenRuleVersionResult(draft.id, draft.revision, version),
            ),
            version.id,
        )

    async def _create_activation_plan(
        self,
        connection,
        *,
        command: RuleMutationCommand,
        mutation: CreateRuleActivationPlan,
        actor_id: str,
        now: datetime,
    ) -> tuple[RuleMutationOperation, str]:
        versions_result = await connection.execute(
            select(RuleSetVersionRecord.__table__)
            .where(
                RuleSetVersionRecord.binding_id == command.binding_id,
            )
            .order_by(RuleSetVersionRecord.version_id)
            .with_for_update()
        )
        versions = versions_result.mappings().all()
        available_version_ids = {row["version_id"] for row in versions}
        if (
            mutation.version_id not in available_version_ids
            or mutation.restore_version_id not in available_version_ids
            or mutation.version_id == mutation.restore_version_id
        ):
            return _rejected(command, RuleOperationRejection.VALIDATION), command.binding_id

        plan_count = await connection.scalar(
            select(func.count())
            .select_from(RuleActivationPlanRecord)
            .where(RuleActivationPlanRecord.binding_id == command.binding_id)
        )
        if plan_count is None or plan_count >= 1_000:
            return _rejected(command, RuleOperationRejection.VALIDATION), command.binding_id

        active_states = tuple(
            state.value
            for state in (
                RuleActivationPlanState.PENDING,
                RuleActivationPlanState.ACTIVATING,
                RuleActivationPlanState.ACTIVE,
                RuleActivationPlanState.RESTORING,
            )
        )
        overlapping = await connection.scalar(
            select(func.count())
            .select_from(RuleActivationPlanRecord)
            .where(
                RuleActivationPlanRecord.binding_id == command.binding_id,
                RuleActivationPlanRecord.state.in_(active_states),
                RuleActivationPlanRecord.activate_at < mutation.deactivate_at,
                RuleActivationPlanRecord.deactivate_at > mutation.activate_at,
            )
        )
        if overlapping:
            return _rejected(command, RuleOperationRejection.CONFLICT), command.binding_id

        try:
            plan = RuleActivationPlan(
                id=str(uuid4()),
                revision=str(uuid4()),
                binding_id=command.binding_id,
                version_id=mutation.version_id,
                restore_version_id=mutation.restore_version_id,
                activate_at=mutation.activate_at,
                deactivate_at=mutation.deactivate_at,
                time_zone=mutation.time_zone,
                state=RuleActivationPlanState.PENDING,
                activation_publication_id=None,
                restore_publication_id=None,
            )
        except (TypeError, ValueError):
            return _rejected(command, RuleOperationRejection.VALIDATION), command.binding_id
        await connection.execute(
            insert(RuleActivationPlanRecord).values(
                plan_id=plan.id,
                revision=plan.revision,
                binding_id=plan.binding_id,
                version_id=plan.version_id,
                restore_version_id=plan.restore_version_id,
                activate_at=plan.activate_at,
                deactivate_at=plan.deactivate_at,
                time_zone=plan.time_zone,
                state=plan.state.value,
                activation_publication_id=None,
                restore_publication_id=None,
                created_at=now,
                created_by_account_id=actor_id,
            )
        )
        return (
            RuleMutationOperation(
                command.binding_id,
                command.request_key,
                RuleOperationStatus.COMPLETED,
                mutation_kind=RuleMutationKind.CREATE_PLAN,
                result=plan,
            ),
            plan.id,
        )

    async def _cancel_activation_plan(
        self,
        connection,
        *,
        command: RuleMutationCommand,
        mutation: CancelRuleActivationPlan,
    ) -> tuple[RuleMutationOperation, str]:
        result = await connection.execute(
            select(RuleActivationPlanRecord.__table__)
            .where(
                RuleActivationPlanRecord.plan_id == mutation.plan_id,
                RuleActivationPlanRecord.binding_id == command.binding_id,
            )
            .with_for_update()
        )
        row = result.mappings().one_or_none()
        if row is None:
            return _rejected(command, RuleOperationRejection.NOT_FOUND), mutation.plan_id
        if (
            row["revision"] != mutation.expected_revision
            or row["state"] not in _CANCELLABLE_ACTIVATION_PLAN_STATES
        ):
            return _rejected(command, RuleOperationRejection.CONFLICT), mutation.plan_id
        revision = str(uuid4())
        changed = await connection.execute(
            update(RuleActivationPlanRecord)
            .where(
                RuleActivationPlanRecord.plan_id == mutation.plan_id,
                RuleActivationPlanRecord.binding_id == command.binding_id,
                RuleActivationPlanRecord.revision == mutation.expected_revision,
                RuleActivationPlanRecord.state.in_(
                    _CANCELLABLE_ACTIVATION_PLAN_STATES
                ),
            )
            .values(revision=revision, state=RuleActivationPlanState.CANCELLED.value)
        )
        if changed.rowcount != 1:
            return _rejected(command, RuleOperationRejection.CONFLICT), mutation.plan_id
        updated = dict(row)
        updated["revision"] = revision
        updated["state"] = RuleActivationPlanState.CANCELLED.value
        plan = activation_plan_from_body(activation_plan_body_from_row(updated))
        return (
            RuleMutationOperation(
                command.binding_id,
                command.request_key,
                RuleOperationStatus.COMPLETED,
                mutation_kind=RuleMutationKind.CANCEL_PLAN,
                result=plan,
            ),
            mutation.plan_id,
        )

    async def _configure_publication_target(
        self,
        connection,
        *,
        command: RuleMutationCommand,
        mutation: ConfigureRulePublicationTarget,
        binding: RuleBinding,
        now: datetime,
    ) -> tuple[RuleMutationOperation, str]:
        """CAS one exact destination while preserving the source-owned location."""
        requested = mutation.target
        if requested.binding_id != command.binding_id or (
            requested.source_id != binding.source_id
        ):
            return _rejected(command, RuleOperationRejection.VALIDATION), command.binding_id

        source_result = await connection.execute(
            select(
                RegisteredConfigurationSourceRecord.revision,
                RegisteredConfigurationSourceRecord.provider,
                RegisteredConfigurationSourceRecord.location,
            )
            .where(
                RegisteredConfigurationSourceRecord.source_id == requested.source_id
            )
            .with_for_update()
        )
        source = source_result.one_or_none()
        if source is None:
            return _rejected(command, RuleOperationRejection.NOT_FOUND), requested.source_id
        if (
            source.revision != mutation.expected_source_revision
            or source.provider != requested.provider.value
        ):
            return _rejected(command, RuleOperationRejection.CONFLICT), requested.source_id

        if isinstance(requested, NacosRulePublicationTarget):
            if requested.namespace != source.location:
                return _rejected(command, RuleOperationRejection.VALIDATION), command.binding_id
            target = requested
        elif isinstance(requested, ConsulRulePublicationTarget):
            target = ConsulRulePublicationTarget(
                binding_id=requested.binding_id,
                source_id=requested.source_id,
                key=requested.key,
                datacenter=source.location,
            )
        else:
            return _rejected(command, RuleOperationRejection.UNSUPPORTED), command.binding_id

        current_result = await connection.execute(
            select(RulePublicationTargetRecord.target_revision)
            .where(RulePublicationTargetRecord.binding_id == command.binding_id)
            .with_for_update()
        )
        current_revision = current_result.scalar_one_or_none()
        if current_revision != mutation.expected_target_revision:
            return _rejected(command, RuleOperationRejection.CONFLICT), command.binding_id

        versioned = VersionedRulePublicationTarget(
            revision=str(uuid4()),
            source_revision=source.revision,
            target=target,
        )
        values = {
            "binding_id": command.binding_id,
            "source_id": target.source_id,
            "target_revision": versioned.revision,
            "source_revision": versioned.source_revision,
            "target_body": target_body(target),
            "updated_at": now,
        }
        if current_revision is None:
            await connection.execute(insert(RulePublicationTargetRecord).values(**values))
        else:
            changed = await connection.execute(
                update(RulePublicationTargetRecord)
                .where(
                    RulePublicationTargetRecord.binding_id == command.binding_id,
                    RulePublicationTargetRecord.target_revision == current_revision,
                )
                .values(
                    **{key: value for key, value in values.items() if key != "binding_id"}
                )
            )
            if changed.rowcount != 1:
                return _rejected(command, RuleOperationRejection.CONFLICT), command.binding_id

        operation = RuleMutationOperation(
            command.binding_id,
            command.request_key,
            RuleOperationStatus.COMPLETED,
            mutation_kind=RuleMutationKind.CONFIGURE_TARGET,
            result=versioned,
        )
        return operation, command.binding_id

    def _fingerprints(self, command: RuleMutationCommand) -> dict[str, str]:
        encoded = json.dumps(
            {
                "bindingId": command.binding_id,
                "requestKey": command.request_key,
                "mutation": _canonical_value(command.mutation),
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return {
            key_id: hmac.new(
                key, _FINGERPRINT_DOMAIN + encoded, hashlib.sha256
            ).hexdigest()
            for key_id, key in self._fingerprint_keys.items()
        }

    def _recover(
        self, row, *, command: RuleMutationCommand, actor_id: str,
        session_digest: str, fingerprints: Mapping[str, str],
    ) -> RuleMutationOperation:
        if (
            row["binding_id"] != command.binding_id
            or row["actor_account_id"] != actor_id
            or row["session_hash"] != session_digest
        ):
            raise RuleMutationIdempotencyConflict(
                "request key belongs to another operation"
            )
        stored = fingerprints.get(row["fingerprint_key_id"])
        if stored is None:
            raise RuleMutationAuthorityUnavailable(
                "rule fingerprint key is unavailable"
            )
        if not hmac.compare_digest(row["fingerprint_digest"], stored):
            raise RuleMutationIdempotencyConflict(
                "request key was reused for another command"
            )
        return _operation_from_row(row)

    async def _recover_race(
        self, command, *, actor_id, session_digest, csrf_digest,
        now, fingerprints,
    ) -> RuleMutationOperation:
        try:
            async with self._engine.begin() as connection:
                await self._authorize_write(
                    connection, actor_id=actor_id, session_digest=session_digest,
                    csrf_digest=csrf_digest, now=now,
                )
                result = await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key == command.request_key
                    )
                )
                row = result.mappings().one_or_none()
                if row is None:
                    raise RuleMutationAuthorityUnavailable(
                        "rule mutation transaction could not be confirmed"
                    )
                return self._recover(
                    row, command=command, actor_id=actor_id,
                    session_digest=session_digest, fingerprints=fingerprints,
                )
        except (RuleMutationForbidden, RuleMutationIdempotencyConflict,
                RuleMutationUnauthenticated, RuleMutationAuthorityUnavailable):
            raise
        except SQLAlchemyError:
            raise RuleMutationAuthorityUnavailable(
                "rule mutation authority is unavailable"
            ) from None


def _rejected(
    command: RuleMutationCommand, reason: RuleOperationRejection
) -> RuleMutationOperation:
    return RuleMutationOperation(
        command.binding_id,
        command.request_key,
        RuleOperationStatus.REJECTED,
        reason=reason,
    )


def _scheduled_phase(
    claim: RuleActivationPlanClaim,
) -> tuple[RuleActivationPlanPhase, str, str]:
    if claim.plan.state is RuleActivationPlanState.ACTIVATING:
        return (
            RuleActivationPlanPhase.ACTIVATION,
            claim.plan.version_id,
            claim.plan.restore_version_id,
        )
    if claim.plan.state is RuleActivationPlanState.RESTORING:
        return (
            RuleActivationPlanPhase.RESTORATION,
            claim.plan.restore_version_id,
            claim.plan.version_id,
        )
    raise ValueError("activation plan claim phase is not executable")


def _scheduled_request_key(
    plan_id: str, phase: RuleActivationPlanPhase
) -> str:
    digest = hashlib.sha256(f"{plan_id}\x00{phase.value}".encode("utf-8")).hexdigest()
    return f"scheduled-rule-publish:{digest}"


def _scheduled_publication_id(
    plan_id: str, phase: RuleActivationPlanPhase
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"atlas-richie-sentinel:scheduled-rule-publication:{plan_id}:{phase.value}",
        )
    )


def _scheduled_audit_action(phase: RuleActivationPlanPhase) -> str:
    return {
        RuleActivationPlanPhase.ACTIVATION: "rules.activation_plan.activate",
        RuleActivationPlanPhase.RESTORATION: "rules.activation_plan.restore",
    }[phase]


def _scheduled_publication_result(
    operation: RuleMutationOperation, publication_id: str
) -> ScheduledPublicationEnqueue:
    if operation.status is RuleOperationStatus.PENDING:
        return ScheduledPublicationEnqueue(
            ScheduledPublicationState.PENDING, publication_id
        )
    if operation.status is RuleOperationStatus.COMPLETED:
        if not isinstance(operation.result, RulePublication):
            raise ValueError("completed scheduled publication has no publication")
        if operation.result.id != publication_id:
            raise ValueError("scheduled publication identity changed")
        return ScheduledPublicationEnqueue(
            ScheduledPublicationState.COMPLETED, publication_id
        )
    if operation.reason is None:
        raise ValueError("rejected scheduled publication has no reason")
    return ScheduledPublicationEnqueue(
        ScheduledPublicationState.REJECTED, None, operation.reason
    )


def _mutation_kind(mutation: RuleMutation) -> RuleMutationKind:
    match mutation:
        case SaveRuleDraft():
            return RuleMutationKind.SAVE_DRAFT
        case DeleteRuleDraft():
            return RuleMutationKind.DELETE_DRAFT
        case FreezeRuleVersion():
            return RuleMutationKind.FREEZE_VERSION
        case PublishRuleVersion():
            return RuleMutationKind.PUBLISH
        case CreateRuleActivationPlan():
            return RuleMutationKind.CREATE_PLAN
        case CancelRuleActivationPlan():
            return RuleMutationKind.CANCEL_PLAN
        case ConfigureRulePublicationTarget():
            return RuleMutationKind.CONFIGURE_TARGET


def _canonical_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise TypeError("rule command contains a non-canonical value")


def _operation_result(operation: RuleMutationOperation):
    if operation.status is not RuleOperationStatus.COMPLETED:
        return None
    if operation.mutation_kind is RuleMutationKind.SAVE_DRAFT:
        assert isinstance(operation.result, StoredRuleDraft)
        return {"draft": stored_rule_draft_body(operation.result)}
    if operation.mutation_kind is RuleMutationKind.DELETE_DRAFT:
        assert isinstance(operation.result, str)
        return {"draftId": operation.result}
    if operation.mutation_kind is RuleMutationKind.FREEZE_VERSION:
        assert isinstance(operation.result, FrozenRuleVersionResult)
        return {
            "draftId": operation.result.draft_id,
            "draftRevision": operation.result.draft_revision,
            "version": rule_set_version_body(operation.result.version),
        }
    if operation.mutation_kind is RuleMutationKind.PUBLISH:
        assert isinstance(operation.result, RulePublication)
        return {"publication": rule_publication_body(operation.result)}
    if operation.mutation_kind in {
        RuleMutationKind.CREATE_PLAN,
        RuleMutationKind.CANCEL_PLAN,
    }:
        assert isinstance(operation.result, RuleActivationPlan)
        return {"plan": activation_plan_result_body(operation.result)}
    if operation.mutation_kind is RuleMutationKind.CONFIGURE_TARGET:
        assert isinstance(operation.result, VersionedRulePublicationTarget)
        return {
            "targetRevision": operation.result.revision,
            "sourceRevision": operation.result.source_revision,
            "target": target_body(operation.result.target),
        }
    raise ValueError("unsupported rule operation cannot be completed")


def _operation_from_row(row) -> RuleMutationOperation:
    status = RuleOperationStatus(row["status"])
    if status is RuleOperationStatus.REJECTED:
        return RuleMutationOperation(
            row["binding_id"],
            row["request_key"],
            status,
            reason=RuleOperationRejection(row["reason"]),
        )
    kind = RuleMutationKind(row["mutation_kind"])
    if status is RuleOperationStatus.PENDING:
        if kind is not RuleMutationKind.PUBLISH or not _valid_publish_work_payload(
            row["work_payload"]
        ):
            raise ValueError("persisted publish work is invalid")
        return RuleMutationOperation(
            row["binding_id"], row["request_key"], RuleOperationStatus.PENDING
        )
    result = row["result"]
    if kind is RuleMutationKind.DELETE_DRAFT and isinstance(result, dict):
        value: RuleMutationResult = result["draftId"]
    elif kind is RuleMutationKind.SAVE_DRAFT and isinstance(result, dict):
        value = draft_from_body(result["draft"])
    elif kind is RuleMutationKind.FREEZE_VERSION and isinstance(result, dict):
        value = FrozenRuleVersionResult(
            draft_id=result["draftId"],
            draft_revision=result["draftRevision"],
            version=version_from_body(result["version"]),
        )
    elif kind is RuleMutationKind.PUBLISH and isinstance(result, dict):
        value = publication_from_body(result["publication"])
    elif kind in {
        RuleMutationKind.CREATE_PLAN,
        RuleMutationKind.CANCEL_PLAN,
    } and isinstance(result, dict):
        value = activation_plan_from_body(result["plan"])
    elif kind is RuleMutationKind.CONFIGURE_TARGET and isinstance(result, dict):
        value = VersionedRulePublicationTarget(
            revision=result["targetRevision"],
            source_revision=result["sourceRevision"],
            target=target_from_body(result["target"]),
        )
    else:
        raise ValueError("persisted rule command result is invalid")
    return RuleMutationOperation(
        row["binding_id"], row["request_key"], status,
        mutation_kind=kind, result=value,
    )


def _publish_work_payload(
    command: RuleMutationCommand,
    operation: RuleMutationOperation,
    publication_id: str | None,
    publication_target: VersionedRulePublicationTarget | None,
) -> dict[str, object] | None:
    if operation.status is not RuleOperationStatus.PENDING:
        return None
    mutation = command.mutation
    if (
        not isinstance(mutation, PublishRuleVersion)
        or publication_id is None
        or publication_target is None
    ):
        raise ValueError("pending rule work is not a publish command")
    target = publication_target.target
    return {
        "schemaVersion": _PUBLISH_WORK_SCHEMA_VERSION,
        "bindingId": command.binding_id,
        "publicationId": publication_id,
        "versionId": mutation.version_id,
        "versionChecksum": mutation.version_checksum,
        "expectedVersionId": mutation.expected_version_id,
        "expectedChecksum": mutation.expected_checksum,
        "expectedSourceRevision": mutation.expected_source_revision,
        "targetRevision": publication_target.revision,
        "sourceRevision": publication_target.source_revision,
        "target": target_body(target),
    }


def _valid_publish_work_payload(value: object) -> bool:
    expected_fields = {
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
    if not isinstance(value, dict) or set(value) != expected_fields:
        return False
    if not (
        value["schemaVersion"] == _PUBLISH_WORK_SCHEMA_VERSION
        and all(
            isinstance(value[key], str) and bool(value[key].strip())
            for key in (
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
    ):
        return False
    try:
        target = target_from_body(value["target"])
    except (TypeError, ValueError):
        return False
    return (
        value["schemaVersion"] == _PUBLISH_WORK_SCHEMA_VERSION
        and target.binding_id == value["bindingId"]
    )


def _audit_outcome(status: RuleOperationStatus) -> str:
    if status is RuleOperationStatus.PENDING:
        return "accepted"
    if status is RuleOperationStatus.COMPLETED:
        return "completed"
    return "rejected"


def _millisecond_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("rule mutation time must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=(value.microsecond // 1000) * 1000)


__all__ = ["SqlAlchemyRuleMutationStore"]
