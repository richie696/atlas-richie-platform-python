"""Durable rule-draft commands against the isolated SQLite adapter."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
import unittest
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.api.rule_candidate_parsing import (
    parse_rule_candidate,
)
from atlas_richie.sentinel_console.api.rule_snapshot_serializers import rule_record_body
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    CancelRuleActivationPlan,
    ConfigureRulePublicationTarget,
    CreateRuleActivationPlan,
    DeleteRuleDraft,
    FreezeRuleVersion,
    PublishRuleVersion,
    RuleMutationCommand,
    RuleMutationForbidden,
    RuleMutationIdempotencyConflict,
    RuleMutationKind,
    RuleMutationUnauthenticated,
    RuleOperationRejection,
    RuleOperationStatus,
    SaveRuleDraft,
)
from atlas_richie.sentinel_console.application.read_rule_publication import (
    ReadRulePublication,
)
from atlas_richie.sentinel_console.application.read_rule_version import ReadRuleVersion
from atlas_richie.sentinel_console.application.resolve_registered_source_connection import (
    ResolveRegisteredSourceConnection,
)
from atlas_richie.sentinel_console.application.rule_activation_plan_ports import (
    RuleActivationPlanClaimConflict,
)
from atlas_richie.sentinel_console.application.rule_draft_detail_ports import (
    RuleDraftDetailNotFound,
)
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationProviderConflict,
    RulePublicationProviderOutcomeUnknown,
)
from atlas_richie.sentinel_console.application.run_rule_activation_plan_worker import (
    RuleActivationPlanWorkerOutcome,
    RunRuleActivationPlanWorker,
)
from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RulePublicationWorkerOutcome,
    RunRulePublicationWorker,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.domain.rule_drafts import StoredRuleDraft
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationReason,
    PublicationStage,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.domain.rule_validation import (
    RuleCandidateValidationReceipt,
    RuleValidationIssue,
    RuleValidationIssueCode,
)
from atlas_richie.sentinel_console.infrastructure.persistence.account_directory_reader import (
    SqlAlchemyAccountDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_reader import (
    SqlAlchemyCurrentSessionReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.current_session_revoker import (
    SqlAlchemyCurrentSessionRevoker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RuleActivationPlanRecord,
    RuleDraftRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RulePublicationTargetRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_reader import (
    SqlAlchemyRuleActivationPlanReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_work_queue import (
    SqlAlchemyRuleActivationPlanWorkQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_draft_reader import (
    SqlAlchemyRuleDraftReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_store import (
    SqlAlchemyRuleMutationStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_reader import (
    SqlAlchemyRulePublicationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publish_outbox import (
    RulePublishClaimConflict,
    SqlAlchemyRulePublishOutbox,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_validation_receipt_store import (
    SqlAlchemyRuleValidationReceiptStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_version_reader import (
    SqlAlchemyRuleVersionReader,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_worker_composition import (
    create_consul_rule_publication_worker,
    create_nacos_rule_publication_worker,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)

_NOW = datetime(2026, 10, 9, 8, 0, 0, 123000, tzinfo=UTC)
_ADMIN_COOKIE = "synthetic-rule-admin-session-00000001"
_ADMIN_CSRF = "synthetic-rule-admin-csrf-000000001"
_VIEW_COOKIE = "synthetic-rule-view-session-000000001"
_VIEW_CSRF = "synthetic-rule-view-csrf-0000000001"
_KEY = b"synthetic-rule-command-fingerprint-key-00000000001"
_CONSUL_IMAGE = "hashicorp/consul:1.21.1"
_NACOS_IMAGE = "nacos/nacos-server:v3.2.4"
_NACOS_TEST_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI="


class RuleMutationStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(self.engine)
        self.publication_target_reader = _TestPublicationTargetReader()
        self.store = SqlAlchemyRuleMutationStore(
            self.engine,
            fingerprint_keys={"key-1": _KEY},
            active_fingerprint_key_id="key-1",
            binding_reader=_TestBindingReader(),
            publication_target_reader=self.publication_target_reader,
        )
        await self._seed_account("admin-1", "admin", _ADMIN_COOKIE, _ADMIN_CSRF)
        await self._seed_account("view-1", "view", _VIEW_COOKIE, _VIEW_CSRF)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _seed_account(self, account_id, role, cookie, csrf) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=account_id,
                    username_key=hashlib.sha256(account_id.encode()).hexdigest(),
                    password_hash="$argon2id$synthetic-hash",
                    role_id=role,
                    status="active",
                    built_in=role == "admin",
                    revision=1,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=_digest(cookie),
                    account_id=account_id,
                    session_epoch=f"epoch-{account_id}",
                    csrf_hash=_digest(csrf),
                    created_at=_NOW,
                    # Authorization checks use the real UTC clock; keep this
                    # fixture valid independently of when the suite is run.
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                    revoked_at=None,
                )
            )

    async def _mutate(self, command, *, actor="admin-1", cookie=_ADMIN_COOKIE,
                      csrf=_ADMIN_CSRF, request_id="request-1"):
        return await self.store.mutate(
            command,
            actor_id=actor,
            session_digest=_digest(cookie),
            csrf_digest=_digest(csrf),
            request_id=request_id,
            now=_NOW,
        )

    async def test_all_rule_kinds_round_trip_and_preserve_original_receipt(
        self,
    ) -> None:
        fixtures = (
            ("flow", [{"resource": "/orders", "limitApp": "default", "grade": 1,
                       "count": 5, "strategy": 0, "controlBehavior": 0,
                       "clusterMode": False}]),
            ("degrade", [{"resource": "/orders", "grade": 2, "count": 3,
                          "timeWindow": 10, "minRequestAmount": 1,
                          "statIntervalMs": 1000}]),
            ("system", [{"highestSystemLoad": -1, "avgRt": 10, "maxThread": -1,
                         "qps": -1, "highestCpuUsage": -1}]),
            ("authority", [{"resource": "/orders", "limitApp": "web", "strategy": 0}]),
            ("param", [{"resource": "/orders", "grade": 1, "count": 10,
                        "durationInSec": 1, "paramIdx": 0, "paramFlowItemList": []}]),
        )
        results = []
        for kind, values in fixtures:
            binding_id = f"binding-{kind}"
            candidate = parse_rule_candidate({
                "bindingId": binding_id,
                "profile": "sentinel-profile-v1",
                "kind": kind,
                "baseVersionId": None,
                "baseChecksum": "sha256:empty",
                "sourceRevision": None,
                "rules": [
                    {
                        "recordId": f"record-{kind}",
                        "rule": {"kind": kind, "value": value},
                    }
                    for value in values
                ],
            })
            command = RuleMutationCommand(
                binding_id, f"save-{kind}", SaveRuleDraft(None, None, candidate)
            )
            operation = await self._mutate(command, request_id=f"request-{kind}")
            self.assertEqual(operation.status, RuleOperationStatus.COMPLETED)
            self.assertEqual(operation.mutation_kind, RuleMutationKind.SAVE_DRAFT)
            self.assertIsInstance(operation.result, StoredRuleDraft)
            self.assertEqual(operation.result.kind.value, kind)
            self.assertEqual(operation.result.records[0].id, f"record-{kind}")
            results.append((command, operation))

        for command, original in results:
            replay = await self._mutate(command, request_id="replay-request")
            persisted = await self.store.read_operation(
                command.binding_id,
                command.request_key,
                actor_id="admin-1",
                session_digest=_digest(_ADMIN_COOKIE),
            )
            self.assertEqual(replay, original)
            self.assertEqual(persisted, original)

        async with self.engine.connect() as connection:
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleDraftRecord)
                ),
                5,
            )
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleMutationOperationRecord)
                ),
                5,
            )
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(AuditEventRecord)
                    .where(AuditEventRecord.action == "rules.save_draft")
                ),
                5,
            )

    async def test_configure_publication_target_is_admin_idempotent_and_audited(self):
        await self._seed_registered_source()
        command = RuleMutationCommand(
            "binding-flow",
            "target-command-1",
            ConfigureRulePublicationTarget(
                expected_source_revision="source-rev-3",
                expected_target_revision=None,
                target=NacosRulePublicationTarget(
                    binding_id="binding-flow",
                    source_id="test-source",
                    namespace="test-namespace",
                    group="SENTINEL_RULES",
                    data_id="test-app.flow.json",
                ),
            ),
        )

        completed = await self._mutate(command, request_id="target-request-1")
        replay = await self._mutate(command, request_id="target-request-2")

        self.assertEqual(completed.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(completed.mutation_kind, RuleMutationKind.CONFIGURE_TARGET)
        self.assertEqual(replay, completed)
        self.assertIsInstance(completed.result, VersionedRulePublicationTarget)
        self.assertEqual(completed.result.target, command.mutation.target)
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(RulePublicationTargetRecord.__table__).where(
                        RulePublicationTargetRecord.binding_id == "binding-flow"
                    )
                )
            ).mappings().one()
            audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.action == "rules.configure_target")
            )
        self.assertEqual(row["target_revision"], completed.result.revision)
        self.assertEqual(row["source_revision"], "source-rev-3")
        self.assertEqual(audit_count, 1)

    async def test_configure_target_rejects_stale_source_without_writing(self):
        await self._seed_registered_source()
        operation = await self._mutate(
            RuleMutationCommand(
                "binding-flow",
                "target-command-stale-source",
                ConfigureRulePublicationTarget(
                    expected_source_revision="source-rev-old",
                    expected_target_revision=None,
                    target=NacosRulePublicationTarget(
                        binding_id="binding-flow",
                        source_id="test-source",
                        namespace="test-namespace",
                        group="SENTINEL_RULES",
                        data_id="test-app.flow.json",
                    ),
                ),
            )
        )
        self.assertEqual(operation.status, RuleOperationStatus.REJECTED)
        self.assertEqual(operation.reason, RuleOperationRejection.CONFLICT)
        async with self.engine.connect() as connection:
            target_count = await connection.scalar(
                select(func.count()).select_from(RulePublicationTargetRecord)
            )
        self.assertEqual(target_count, 0)

    async def _seed_registered_source(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id="test-source",
                    revision="source-rev-3",
                    name="Test Source",
                    endpoint="https://config.test",
                    provider="nacos",
                    location="test-namespace",
                    authentication_mode="none",
                    credential_configured=False,
                    credential_cipher_format=None,
                    credential_key_id=None,
                    credential_payload=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id="admin-1",
                )
            )

    async def test_revision_conflict_delete_and_idempotent_delete(self) -> None:
        candidate = _flow_candidate("binding-flow", count=5)
        created = await self._mutate(
            RuleMutationCommand(
                "binding-flow", "create-1", SaveRuleDraft(None, None, candidate)
            )
        )
        draft = created.result
        self.assertIsInstance(draft, StoredRuleDraft)

        updated_candidate = _flow_candidate(
            "binding-flow", count=8, record_id=draft.records[0].id
        )
        updated = await self._mutate(
            RuleMutationCommand(
                "binding-flow", "update-1",
                SaveRuleDraft(draft.id, draft.revision, updated_candidate),
            )
        )
        self.assertEqual(updated.status, RuleOperationStatus.COMPLETED)
        revised = updated.result
        self.assertNotEqual(revised.revision, draft.revision)

        stale = await self._mutate(
            RuleMutationCommand(
                "binding-flow", "stale-1",
                SaveRuleDraft(draft.id, draft.revision, candidate),
            )
        )
        self.assertEqual(stale.reason, RuleOperationRejection.CONFLICT)

        delete_command = RuleMutationCommand(
            "binding-flow", "delete-1", DeleteRuleDraft(draft.id, revised.revision)
        )
        deleted = await self._mutate(delete_command)
        replay = await self._mutate(delete_command, request_id="delete-replay")
        self.assertEqual(deleted.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(deleted.result, draft.id)
        self.assertEqual(replay, deleted)
        async with self.engine.connect() as connection:
            self.assertIsNone(await connection.scalar(
                select(RuleDraftRecord.draft_id).where(
                    RuleDraftRecord.draft_id == draft.id
                )
            ))

    async def test_reused_key_conflicts_and_viewer_or_wrong_csrf_cannot_write(
        self,
    ) -> None:
        first = RuleMutationCommand(
            "binding-flow",
            "same-key",
            SaveRuleDraft(None, None, _flow_candidate("binding-flow", 5)),
        )
        await self._mutate(first)
        changed = RuleMutationCommand(
            "binding-flow",
            "same-key",
            SaveRuleDraft(None, None, _flow_candidate("binding-flow", 6)),
        )
        with self.assertRaises(RuleMutationIdempotencyConflict):
            await self._mutate(changed)
        with self.assertRaises(RuleMutationForbidden):
            await self._mutate(
                RuleMutationCommand(
                    "binding-view",
                    "viewer-key",
                    SaveRuleDraft(None, None, _flow_candidate("binding-view", 1)),
                ),
                actor="view-1", cookie=_VIEW_COOKIE, csrf=_VIEW_CSRF,
            )
        with self.assertRaises(RuleMutationForbidden):
            await self._mutate(
                RuleMutationCommand(
                    "binding-csrf",
                    "csrf-key",
                    SaveRuleDraft(None, None, _flow_candidate("binding-csrf", 1)),
                ),
                csrf="incorrect-csrf-value",
            )
        async with self.engine.connect() as connection:
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleDraftRecord)
                ),
                1,
            )

    async def test_publish_without_exact_target_is_rejected_closed(self) -> None:
        command = RuleMutationCommand(
            "missing-target-binding",
            "publish-without-target",
            PublishRuleVersion(
                "version-unreachable",
                "sha256:version-checksum",
                None,
                "sha256:source-checksum",
                None,
                "operator reason",
            ),
        )

        operation = await self._mutate(command)

        self.assertEqual(operation.status, RuleOperationStatus.REJECTED)
        self.assertEqual(operation.reason, RuleOperationRejection.UNAVAILABLE)
        async with self.engine.connect() as connection:
            stored = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key
                        == "publish-without-target"
                    )
                )
            ).mappings().one()
            self.assertIsNone(stored["work_payload"])

    async def test_publish_is_atomically_queued_with_exact_original_baseline(
        self,
    ) -> None:
        await self._seed_plan_versions("binding-flow")
        target_checksum = candidate_checksum(
            _flow_candidate("binding-flow", count=17, record_id="plan-record")
        )
        command = RuleMutationCommand(
            "binding-flow",
            "publish-durable",
            PublishRuleVersion(
                "version-promo",
                target_checksum,
                None,
                "sha256:source-baseline",
                "provider-revision-42",
                "operator reason",
            ),
        )
        operation = await self._mutate(command)
        replay = await self._mutate(command, request_id="publish-replay")
        self.assertEqual(operation.status, RuleOperationStatus.PENDING)
        self.assertEqual(replay.status, RuleOperationStatus.PENDING)
        self.assertEqual(operation, replay)
        async with self.engine.connect() as connection:
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleDraftRecord)
                ),
                0,
            )
            work = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key == "publish-durable"
                    )
                )
            ).mappings().one()
            publication_id = work["work_payload"]["publicationId"]
            self.assertEqual(work["status"], "pending")
            self.assertIsNone(work["result"])
            self.assertEqual(
                work["work_payload"]["expectedSourceRevision"],
                "provider-revision-42",
            )
            self.assertEqual(work["work_payload"]["schemaVersion"], 2)
            self.assertEqual(
                work["work_payload"]["targetRevision"], "mapping-rev-7"
            )
            self.assertEqual(
                work["work_payload"]["sourceRevision"], "source-rev-3"
            )
            self.assertEqual(
                work["work_payload"]["target"],
                {
                    "schemaVersion": 1,
                    "provider": "nacos",
                    "bindingId": "binding-flow",
                    "sourceId": "test-source",
                    "namespace": "test-namespace",
                    "group": "SENTINEL_RULES",
                    "dataId": "test-app.flow.json",
                },
            )
            self.assertNotIn("operator reason", str(work["work_payload"]))
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RulePublicationRecord).where(
                        RulePublicationRecord.publication_id == publication_id,
                        RulePublicationRecord.binding_id == "binding-flow",
                        RulePublicationRecord.target_version_id == "version-promo",
                    )
                ),
                1,
            )
        original = await self.store.read_operation(
            "binding-flow",
            "publish-durable",
            actor_id="admin-1",
            session_digest=_digest(_ADMIN_COOKIE),
        )
        self.assertEqual(original, operation)

        outbox = SqlAlchemyRulePublishOutbox(self.engine)
        # A later mapping edit must not retarget already accepted publish work.
        self.publication_target_reader.current_revision = "mapping-rev-8"
        self.publication_target_reader.current_source_revision = "source-rev-4"
        self.publication_target_reader.current_data_id = "changed.flow.json"
        unsupported_provider_claim = await outbox.claim_ready(
            now=_NOW,
            lease_expires_at=_NOW + timedelta(seconds=30),
            supported_providers=frozenset({ConfigurationSourceProvider.CONSUL}),
        )
        self.assertEqual(unsupported_provider_claim, ())
        first_claim = await outbox.claim_ready(
            now=_NOW,
            lease_expires_at=_NOW + timedelta(seconds=30),
            supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
        )
        self.assertEqual(len(first_claim), 1)
        self.assertEqual(first_claim[0].request_key, "publish-durable")
        self.assertEqual(first_claim[0].publication_id, publication_id)
        self.assertEqual(first_claim[0].target_revision, "mapping-rev-7")
        self.assertEqual(first_claim[0].source_revision, "source-rev-3")
        self.assertEqual(first_claim[0].target.data_id, "test-app.flow.json")
        self.assertEqual(first_claim[0].attempt, 1)
        competing_worker = SqlAlchemyRulePublishOutbox(self.engine)
        validation_started = PublicationPhase(
            PublicationStage.RUNNING, _NOW + timedelta(seconds=1), None
        )
        running = await outbox.advance_claimed_phase(
            first_claim[0],
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.AWAITING,
            next_phase=validation_started,
        )
        self.assertEqual(running.validation.state, PublicationStage.RUNNING)
        replayed = await outbox.advance_claimed_phase(
            first_claim[0],
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.AWAITING,
            next_phase=validation_started,
        )
        self.assertEqual(replayed, running)
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.advance_claimed_phase(
                first_claim[0],
                PublicationPhaseName.VALIDATION,
                expected_state=PublicationStage.RUNNING,
                next_phase=validation_started,
            )
        renewed_claim = await outbox.renew_claim(
            first_claim[0],
            now=_NOW + timedelta(seconds=20),
            lease_expires_at=_NOW + timedelta(seconds=50),
        )
        self.assertEqual(renewed_claim.claim_token, first_claim[0].claim_token)
        self.assertEqual(
            renewed_claim.lease_expires_at, _NOW + timedelta(seconds=50)
        )
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.renew_claim(
                first_claim[0],
                now=_NOW + timedelta(seconds=21),
                lease_expires_at=_NOW + timedelta(seconds=40),
            )
        self.assertEqual(
            await competing_worker.claim_ready(
                now=_NOW + timedelta(seconds=49),
                lease_expires_at=_NOW + timedelta(seconds=79),
                supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
            ),
            (),
        )
        recovered_claim = await outbox.claim_ready(
            now=_NOW + timedelta(seconds=50),
            lease_expires_at=_NOW + timedelta(seconds=80),
            supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
        )
        self.assertEqual(len(recovered_claim), 1)
        self.assertEqual(recovered_claim[0].attempt, 2)
        self.assertNotEqual(first_claim[0].claim_token, recovered_claim[0].claim_token)
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.advance_claimed_phase(
                first_claim[0],
                PublicationPhaseName.VALIDATION,
                expected_state=PublicationStage.RUNNING,
                next_phase=PublicationPhase(
                    PublicationStage.UNKNOWN,
                    _NOW + timedelta(seconds=2),
                    PublicationReason.UNKNOWN,
                ),
            )
        reconciled = await outbox.advance_claimed_phase(
            recovered_claim[0],
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.RUNNING,
            next_phase=PublicationPhase(
                PublicationStage.UNKNOWN,
                _NOW + timedelta(seconds=51),
                PublicationReason.UNKNOWN,
            ),
        )
        self.assertEqual(reconciled.validation.state, PublicationStage.UNKNOWN)
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.complete_claimed_publication(
                recovered_claim[0], completed_at=_NOW + timedelta(seconds=52)
            )
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.reject_claimed_publication(
                recovered_claim[0],
                rejected_at=_NOW + timedelta(seconds=52),
                reason=RuleOperationRejection.UNAVAILABLE,
            )

        with self.assertRaises(ValueError):
            await outbox.claim_ready(
                now=_NOW,
                lease_expires_at=_NOW + timedelta(minutes=6),
                supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
            )

    async def test_consul_worker_claims_consul_target(self) -> None:
        await self._seed_plan_versions("binding-consul")
        self.publication_target_reader.provider = ConfigurationSourceProvider.CONSUL
        checksum = candidate_checksum(
            _flow_candidate("binding-consul", count=17, record_id="plan-record")
        )
        operation = await self._mutate(
            RuleMutationCommand(
                "binding-consul",
                "publish-consul",
                PublishRuleVersion(
                    "version-promo",
                    checksum,
                    None,
                    "sha256:source-baseline",
                    "provider-revision-42",
                    "operator reason",
                ),
            )
        )
        self.assertEqual(operation.status, RuleOperationStatus.PENDING)

        claims = await SqlAlchemyRulePublishOutbox(self.engine).claim_ready(
            now=_NOW,
            lease_expires_at=_NOW + timedelta(seconds=30),
            supported_providers=frozenset({ConfigurationSourceProvider.CONSUL}),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(
            claims[0].target.provider, ConfigurationSourceProvider.CONSUL
        )
        self.assertEqual(claims[0].target.key, "sentinel/prod/rules")

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_consul_worker_publishes_sql_outbox_to_real_consul(self) -> None:
        """Prove SQL acceptance, worker execution and provider read-back together."""
        container_name = f"sentinel-consul-worker-{uuid4().hex[:12]}"
        started = False
        try:
            started = True
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    container_name,
                    "--publish",
                    "127.0.0.1::8500/tcp",
                    _CONSUL_IMAGE,
                    "agent",
                    "-dev",
                    "-client=0.0.0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            published_port = subprocess.run(
                ["docker", "port", container_name, "8500/tcp"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            endpoint = f"http://127.0.0.1:{int(published_port.rsplit(':', 1)[1])}"
            _wait_for_consul(endpoint)

            key = f"sentinel/acceptance/{uuid4().hex}/rules.json"
            await self._seed_plan_versions("binding-consul")
            self.publication_target_reader.provider = (
                ConfigurationSourceProvider.CONSUL
            )
            self.publication_target_reader.consul_key = key
            candidate = _flow_candidate(
                "binding-consul", count=17, record_id="plan-record"
            )
            checksum = candidate_checksum(candidate)
            command = RuleMutationCommand(
                "binding-consul",
                "publish-consul-real-worker",
                PublishRuleVersion(
                    "version-promo",
                    checksum,
                    None,
                    "sha256:source-baseline",
                    "provider-revision-42",
                    "synthetic acceptance reason",
                ),
            )
            accepted = await self._mutate(command)
            self.assertEqual(accepted.status, RuleOperationStatus.PENDING)

            port = int(published_port.rsplit(":", 1)[1])
            policy = RegisteredSourceTargetPolicy(
                [
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.CONSUL,
                        "127.0.0.1",
                        ["127.0.0.1/32"],
                        frozenset({port}),
                    )
                ]
            )
            worker = create_consul_rule_publication_worker(
                self.engine,
                target_policy=policy,
                credential_resolver=_LocalConsulCredentialResolver(endpoint),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: _NOW,
            )

            outcomes = await worker.run_once()

            self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
            connection = await _LocalConsulCredentialResolver(endpoint).resolve_credentials(
                "test-source",
                "source-rev-3",
                ConfigurationSourceProvider.CONSUL,
            )
            stored = await ConsulRuleSourceReader(policy).read(connection, key)
            version = await ReadRuleVersion(
                SqlAlchemyRuleVersionReader(self.engine)
            ).execute("binding-consul", "version-promo")
            expected_bytes = SentinelRuleVersionJsonEncoder(
                "sentinel-profile-v1"
            ).encode_rule_version(version)
            self.assertEqual(stored.value, expected_bytes)
            self.assertIsNotNone(stored.modify_index)

            completed = await self.store.read_operation(
                "binding-consul",
                "publish-consul-real-worker",
                actor_id="admin-1",
                session_digest=_digest(_ADMIN_COOKIE),
            )
            self.assertEqual(completed.status, RuleOperationStatus.COMPLETED)
            self.assertEqual(
                completed.result.read_back.state, PublicationStage.SUCCEEDED
            )
            self.assertEqual(
                completed.result.configuration_write.state,
                PublicationStage.SUCCEEDED,
            )
            self.assertNotIn("synthetic acceptance reason", repr(completed))

            self.assertEqual(await worker.run_once(), ())
            unchanged = await ConsulRuleSourceReader(policy).read(connection, key)
            self.assertEqual(unchanged.modify_index, stored.modify_index)
        finally:
            if started:
                subprocess.run(
                    ["docker", "rm", "--force", container_name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 to start disposable Nacos",
    )
    async def test_nacos_worker_publishes_sql_outbox_to_real_nacos(self) -> None:
        """Prove SQL acceptance, Nacos gRPC CAS, read-back, and dedup together."""
        token = uuid4().hex
        container_name = f"sentinel-nacos-worker-{token[:12]}"
        http_port, grpc_port = _free_loopback_port_pair()
        endpoint = f"http://127.0.0.1:{http_port}/nacos"
        data_id = f"sentinel-acceptance-{token}.json"
        group = "SENTINEL_ACCEPTANCE"
        namespace = "public"
        seeded = False
        started = False
        try:
            started = True
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    container_name,
                    "--env",
                    "MODE=standalone",
                    "--env",
                    "NACOS_AUTH_ENABLE=false",
                    "--env",
                    "NACOS_AUTH_ADMIN_ENABLE=false",
                    "--env",
                    "NACOS_AUTH_CONSOLE_ENABLE=false",
                    "--env",
                    f"NACOS_AUTH_TOKEN={_NACOS_TEST_TOKEN}",
                    "--env",
                    "NACOS_AUTH_IDENTITY_KEY=sentinel-local-test",
                    "--env",
                    "NACOS_AUTH_IDENTITY_VALUE=sentinel-local-test-only",
                    "--publish",
                    f"127.0.0.1:{http_port}:8848/tcp",
                    "--publish",
                    f"127.0.0.1:{grpc_port}:9848/tcp",
                    _NACOS_IMAGE,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            _wait_for_nacos(endpoint)
            self.publication_target_reader.nacos_namespace = namespace
            self.publication_target_reader.nacos_group = group
            self.publication_target_reader.current_data_id = data_id
            policy = RegisteredSourceTargetPolicy(
                [
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.NACOS,
                        "127.0.0.1",
                        ["127.0.0.1/32"],
                        frozenset({http_port, grpc_port}),
                    )
                ]
            )
            credential_resolver = _LocalNacosCredentialResolver(endpoint)
            connection = await credential_resolver.resolve_credentials(
                "test-source",
                "source-rev-3",
                ConfigurationSourceProvider.NACOS,
            )
            baseline_checksum = await self._seed_nacos_baseline_version(
                "binding-nacos"
            )
            baseline_version = await ReadRuleVersion(
                SqlAlchemyRuleVersionReader(self.engine)
            ).execute("binding-nacos", "version-nacos-baseline")
            seed_value = SentinelRuleVersionJsonEncoder(
                "sentinel-profile-v1"
            ).encode_rule_version(baseline_version).decode("utf-8")
            _nacos_admin_request(
                endpoint,
                "POST",
                {
                    "namespaceId": namespace,
                    "groupName": group,
                    "dataId": data_id,
                    "content": seed_value,
                    "type": "json",
                },
            )
            seeded = True
            reader = NacosRuleSourceReader(policy)
            baseline = await reader.read(
                connection,
                NacosRulePublicationTarget(
                    binding_id="binding-nacos",
                    source_id="test-source",
                    namespace=namespace,
                    group=group,
                    data_id=data_id,
                ),
            )

            await self._seed_plan_versions("binding-nacos")
            candidate = _flow_candidate(
                "binding-nacos", count=17, record_id="plan-record"
            )
            checksum = candidate_checksum(candidate)
            request_key = f"publish-nacos-real-worker-{token}"
            accepted = await self._mutate(
                RuleMutationCommand(
                    "binding-nacos",
                    request_key,
                    PublishRuleVersion(
                        "version-promo",
                        checksum,
                        "version-nacos-baseline",
                        baseline_checksum,
                        baseline.md5,
                        "synthetic Nacos acceptance reason",
                    ),
                )
            )
            self.assertEqual(accepted.status, RuleOperationStatus.PENDING)

            worker = create_nacos_rule_publication_worker(
                self.engine,
                target_policy=policy,
                credential_resolver=credential_resolver,
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: _NOW,
            )
            outcomes = await worker.run_once()
            if outcomes != (RulePublicationWorkerOutcome.COMPLETED,):
                rejected = await self.store.read_operation(
                    "binding-nacos",
                    request_key,
                    actor_id="admin-1",
                    session_digest=_digest(_ADMIN_COOKIE),
                )
                self.fail(
                    f"Nacos publication did not complete: outcomes={outcomes!r}, "
                    f"operation={rejected!r}"
                )

            stored = await reader.read(
                connection,
                NacosRulePublicationTarget(
                    binding_id="binding-nacos",
                    source_id="test-source",
                    namespace=namespace,
                    group=group,
                    data_id=data_id,
                ),
            )
            version = await ReadRuleVersion(
                SqlAlchemyRuleVersionReader(self.engine)
            ).execute("binding-nacos", "version-promo")
            expected_bytes = SentinelRuleVersionJsonEncoder(
                "sentinel-profile-v1"
            ).encode_rule_version(version)
            self.assertEqual(stored.value, expected_bytes)
            self.assertNotEqual(stored.md5, baseline.md5)

            completed = await self.store.read_operation(
                "binding-nacos",
                request_key,
                actor_id="admin-1",
                session_digest=_digest(_ADMIN_COOKIE),
            )
            self.assertEqual(completed.status, RuleOperationStatus.COMPLETED)
            self.assertEqual(
                completed.result.read_back.state, PublicationStage.SUCCEEDED
            )
            self.assertEqual(
                completed.result.configuration_write.state,
                PublicationStage.SUCCEEDED,
            )
            self.assertNotIn("synthetic Nacos acceptance reason", repr(completed))

            self.assertEqual(await worker.run_once(), ())
            unchanged = await reader.read(
                connection,
                NacosRulePublicationTarget(
                    binding_id="binding-nacos",
                    source_id="test-source",
                    namespace=namespace,
                    group=group,
                    data_id=data_id,
                ),
            )
            self.assertEqual(unchanged.md5, stored.md5)
        finally:
            if seeded:
                try:
                    _nacos_admin_request(
                        endpoint,
                        "DELETE",
                        {
                            "namespaceId": namespace,
                            "groupName": group,
                            "dataId": data_id,
                        },
                    )
                except (OSError, ValueError, HTTPError):
                    pass
            if started:
                subprocess.run(
                    ["docker", "rm", "--force", container_name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

    async def test_known_publish_failure_rejects_once_but_keeps_publication(self) -> None:
        await self._seed_plan_versions("binding-rejected")
        checksum = candidate_checksum(
            _flow_candidate("binding-rejected", count=17, record_id="plan-record")
        )
        pending = await self._mutate(
            RuleMutationCommand(
                "binding-rejected",
                "publish-rejected",
                PublishRuleVersion(
                    "version-promo",
                    checksum,
                    None,
                    "sha256:source-baseline",
                    "provider-revision-42",
                    "private operator reason",
                ),
            )
        )
        self.assertEqual(pending.status, RuleOperationStatus.PENDING)
        outbox = SqlAlchemyRulePublishOutbox(self.engine)
        claim = (
            await outbox.claim_ready(
                now=_NOW,
                lease_expires_at=_NOW + timedelta(seconds=30),
                supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
            )
        )[0]
        await outbox.advance_claimed_phase(
            claim,
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.AWAITING,
            next_phase=PublicationPhase(
                PublicationStage.RUNNING, _NOW + timedelta(seconds=1), None
            ),
        )
        await outbox.advance_claimed_phase(
            claim,
            PublicationPhaseName.VALIDATION,
            expected_state=PublicationStage.RUNNING,
            next_phase=PublicationPhase(
                PublicationStage.FAILED,
                _NOW + timedelta(seconds=2),
                PublicationReason.UNSUPPORTED,
            ),
        )

        rejected = await outbox.reject_claimed_publication(
            claim,
            rejected_at=_NOW + timedelta(seconds=3),
            reason=RuleOperationRejection.VALIDATION,
        )
        self.assertEqual(rejected.status, RuleOperationStatus.REJECTED)
        self.assertEqual(rejected.reason, RuleOperationRejection.VALIDATION)
        self.assertNotIn("private operator reason", repr(rejected))
        self.assertEqual(
            await self.store.read_operation(
                "binding-rejected",
                "publish-rejected",
                actor_id="admin-1",
                session_digest=_digest(_ADMIN_COOKIE),
            ),
            rejected,
        )
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.reject_claimed_publication(
                claim,
                rejected_at=_NOW + timedelta(seconds=4),
                reason=RuleOperationRejection.VALIDATION,
            )
        async with self.engine.connect() as connection:
            operation = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key == "publish-rejected"
                    )
                )
            ).mappings().one()
            self.assertEqual(operation["reason"], "validation")
            self.assertIsNone(operation["work_payload"])
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(AuditEventRecord).where(
                        AuditEventRecord.request_id == claim.operation_id,
                        AuditEventRecord.action == "rules.publish",
                        AuditEventRecord.outcome == "rejected",
                    )
                ),
                1,
            )
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RulePublicationRecord).where(
                        RulePublicationRecord.publication_id == claim.publication_id,
                        RulePublicationRecord.validation_state == "failed",
                    )
                ),
                1,
            )

    async def test_publish_completion_commits_safe_receipt_and_audit_once(self) -> None:
        await self._seed_plan_versions("binding-complete")
        checksum = candidate_checksum(
            _flow_candidate("binding-complete", count=17, record_id="plan-record")
        )
        pending = await self._mutate(
            RuleMutationCommand(
                "binding-complete",
                "publish-complete",
                PublishRuleVersion(
                    "version-promo",
                    checksum,
                    None,
                    "sha256:source-baseline",
                    "provider-revision-42",
                    "private operator reason",
                ),
            )
        )
        self.assertEqual(pending.status, RuleOperationStatus.PENDING)
        outbox = SqlAlchemyRulePublishOutbox(self.engine)
        claim = (
            await outbox.claim_ready(
                now=_NOW,
                lease_expires_at=_NOW + timedelta(seconds=30),
                supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
            )
        )[0]

        for index, phase_name in enumerate(
            (
                PublicationPhaseName.VALIDATION,
                PublicationPhaseName.CONFIGURATION_WRITE,
                PublicationPhaseName.READ_BACK,
            )
        ):
            start_at = _NOW + timedelta(seconds=index * 2 + 1)
            await outbox.advance_claimed_phase(
                claim,
                phase_name,
                expected_state=PublicationStage.AWAITING,
                next_phase=PublicationPhase(PublicationStage.RUNNING, start_at, None),
            )
            await outbox.advance_claimed_phase(
                claim,
                phase_name,
                expected_state=PublicationStage.RUNNING,
                next_phase=PublicationPhase(
                    PublicationStage.SUCCEEDED,
                    start_at + timedelta(seconds=1),
                    None,
                ),
            )

        completed = await outbox.complete_claimed_publication(
            claim, completed_at=_NOW + timedelta(seconds=7)
        )
        self.assertEqual(completed.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(completed.mutation_kind, RuleMutationKind.PUBLISH)
        self.assertEqual(completed.result.id, claim.publication_id)
        self.assertEqual(completed.result.read_back.state, PublicationStage.SUCCEEDED)
        self.assertNotIn("private operator reason", repr(completed))

        replay = await self.store.read_operation(
            "binding-complete",
            "publish-complete",
            actor_id="admin-1",
            session_digest=_digest(_ADMIN_COOKIE),
        )
        self.assertEqual(replay, completed)
        with self.assertRaises(RulePublishClaimConflict):
            await outbox.complete_claimed_publication(
                claim, completed_at=_NOW + timedelta(seconds=8)
            )
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key == "publish-complete"
                    )
                )
            ).mappings().one()
            self.assertEqual(row["status"], "completed")
            self.assertIsNone(row["work_payload"])
            self.assertIsNone(row["work_claim_token"])
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(AuditEventRecord).where(
                        AuditEventRecord.request_id == row["operation_id"],
                        AuditEventRecord.action == "rules.publish",
                        AuditEventRecord.outcome == "completed",
                    )
                ),
                1,
            )

    async def test_binding_must_exist_and_match_candidate_kind_and_profile(
        self,
    ) -> None:
        missing = await self._mutate(
            RuleMutationCommand(
                "missing-binding",
                "missing-binding-key",
                SaveRuleDraft(None, None, _flow_candidate("missing-binding", 1)),
            )
        )
        self.assertEqual(missing.reason, RuleOperationRejection.NOT_FOUND)

        candidate = parse_rule_candidate({
            "bindingId": "binding-flow",
            "profile": "sentinel-profile-v1",
            "kind": "degrade",
            "baseVersionId": None,
            "baseChecksum": "sha256:empty",
            "sourceRevision": None,
            "rules": [],
        })
        mismatch = await self._mutate(
            RuleMutationCommand(
                "binding-flow", "binding-kind-mismatch",
                SaveRuleDraft(None, None, candidate),
            )
        )
        self.assertEqual(mismatch.reason, RuleOperationRejection.VALIDATION)
        async with self.engine.connect() as connection:
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleDraftRecord)
                ),
                0,
            )

    async def test_binding_lookup_runs_outside_sql_and_session_is_reauthorized(
        self,
    ) -> None:
        transaction_state = {"active": False}

        def mark_active(_connection):
            transaction_state["active"] = True

        def mark_inactive(_connection):
            transaction_state["active"] = False

        engine = self.engine.sync_engine
        event.listen(engine, "begin", mark_active)
        event.listen(engine, "commit", mark_inactive)
        event.listen(engine, "rollback", mark_inactive)
        try:
            store = SqlAlchemyRuleMutationStore(
                self.engine,
                fingerprint_keys={"key-1": _KEY},
                active_fingerprint_key_id="key-1",
                binding_reader=_SessionRevokingBindingReader(
                    self.engine, transaction_state
                ),
            )
            with self.assertRaises(RuleMutationUnauthenticated):
                await store.mutate(
                    RuleMutationCommand(
                        "binding-flow",
                        "revoked-during-binding-read",
                        SaveRuleDraft(
                            None, None, _flow_candidate("binding-flow", count=12)
                        ),
                    ),
                    actor_id="admin-1",
                    session_digest=_digest(_ADMIN_COOKIE),
                    csrf_digest=_digest(_ADMIN_CSRF),
                    request_id="request-revoked-during-binding-read",
                    now=_NOW,
                )
        finally:
            event.remove(engine, "begin", mark_active)
            event.remove(engine, "commit", mark_inactive)
            event.remove(engine, "rollback", mark_inactive)

        async with self.engine.connect() as connection:
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleDraftRecord)
                ),
                0,
            )
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleMutationOperationRecord)
                ),
                0,
            )

    async def test_sql_draft_reader_returns_complete_exact_binding_views(self) -> None:
        candidate = _flow_candidate("binding-reader", count=11)
        saved = await self._mutate(
            RuleMutationCommand(
                "binding-reader", "reader-save", SaveRuleDraft(None, None, candidate)
            )
        )
        reader = SqlAlchemyRuleDraftReader(self.engine)

        collection = await reader.read_rule_drafts("binding-reader")
        detail = await reader.read_rule_draft("binding-reader", saved.result.id)
        self.assertEqual(collection.binding_id, "binding-reader")
        self.assertEqual(collection.items, (saved.result,))
        self.assertEqual(detail, saved.result)
        with self.assertRaises(RuleDraftDetailNotFound):
            await reader.read_rule_draft("another-binding", saved.result.id)

    async def test_freeze_requires_matching_validation_and_replays_immutable_version(
        self,
    ) -> None:
        candidate = _flow_candidate(
            "binding-freeze", count=12, record_id="stable-record"
        )
        checksum = candidate_checksum(candidate)
        validation = RuleCandidateValidationReceipt(
            binding_id=candidate.binding_id,
            profile=candidate.profile,
            base_checksum=candidate.base_checksum,
            candidate_checksum=checksum,
            validation_id="validation-freeze-1",
            is_publishable=True,
            issues=(),
        )
        await SqlAlchemyRuleValidationReceiptStore(self.engine).record_validation(
            validation,
            actor_id="admin-1",
            request_id="validation-request",
            created_at=_NOW,
        )
        invalid_validation = RuleCandidateValidationReceipt(
            binding_id=candidate.binding_id,
            profile=candidate.profile,
            base_checksum=candidate.base_checksum,
            candidate_checksum=checksum,
            validation_id="validation-freeze-invalid",
            is_publishable=False,
            issues=(
                RuleValidationIssue(
                    RuleValidationIssueCode.VALIDATION,
                    0,
                    "rules[0].count",
                ),
            ),
        )
        await SqlAlchemyRuleValidationReceiptStore(self.engine).record_validation(
            invalid_validation,
            actor_id="admin-1",
            request_id="validation-invalid-request",
            created_at=_NOW,
        )
        saved = await self._mutate(
            RuleMutationCommand(
                "binding-freeze", "draft-freeze", SaveRuleDraft(None, None, candidate)
            )
        )
        stale = await self._mutate(
            RuleMutationCommand(
                "binding-freeze",
                "freeze-stale",
                FreezeRuleVersion(
                    saved.result.id,
                    "stale-revision",
                    validation.validation_id,
                    checksum,
                    "Release candidate",
                    "validated candidate",
                ),
            )
        )
        self.assertEqual(stale.reason, RuleOperationRejection.CONFLICT)
        invalid = await self._mutate(
            RuleMutationCommand(
                "binding-freeze",
                "freeze-invalid-validation",
                FreezeRuleVersion(
                    saved.result.id,
                    saved.result.revision,
                    invalid_validation.validation_id,
                    checksum,
                    "Must not freeze",
                    "non-publishable receipt",
                ),
            )
        )
        self.assertEqual(invalid.reason, RuleOperationRejection.VALIDATION)

        freeze_command = RuleMutationCommand(
            "binding-freeze",
            "freeze-success",
            FreezeRuleVersion(
                saved.result.id,
                saved.result.revision,
                validation.validation_id,
                checksum,
                "Release candidate",
                "validated candidate",
            ),
        )
        frozen = await self._mutate(freeze_command)
        replay = await self._mutate(freeze_command, request_id="freeze-replay")
        self.assertEqual(frozen.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(frozen.mutation_kind, RuleMutationKind.FREEZE_VERSION)
        self.assertEqual(frozen, replay)
        self.assertEqual(frozen.result.version.records, saved.result.records)
        version_reader = SqlAlchemyRuleVersionReader(self.engine)
        self.assertEqual(
            await version_reader.read_rule_version(
                "binding-freeze", frozen.result.version.id
            ),
            frozen.result.version,
        )
        collection = await version_reader.read_rule_versions("binding-freeze")
        self.assertEqual(collection.items, (frozen.result.version,))
        async with self.engine.connect() as connection:
            self.assertEqual(
                await connection.scalar(
                    select(func.count()).select_from(RuleSetVersionRecord)
                ),
                1,
            )

    async def test_activation_plan_create_overlap_cancel_and_replay(self) -> None:
        await self._seed_plan_versions("binding-plans")
        activate_at = _NOW + timedelta(hours=2)
        deactivate_at = _NOW + timedelta(hours=3)
        missing_version = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-missing-version",
                CreateRuleActivationPlan(
                    "unknown-version",
                    "version-daily",
                    activate_at,
                    deactivate_at,
                    "Asia/Shanghai",
                ),
            )
        )
        self.assertEqual(missing_version.reason, RuleOperationRejection.VALIDATION)
        invalid_zone = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-invalid-zone",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    activate_at,
                    deactivate_at,
                    "Mars/Olympus",
                ),
            )
        )
        self.assertEqual(invalid_zone.reason, RuleOperationRejection.VALIDATION)
        create_command = RuleMutationCommand(
            "binding-plans",
            "plan-create-1",
            CreateRuleActivationPlan(
                "version-promo",
                "version-daily",
                activate_at,
                deactivate_at,
                "Asia/Shanghai",
            ),
        )
        created = await self._mutate(create_command)
        replay = await self._mutate(create_command, request_id="plan-create-replay")
        self.assertEqual(created.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(created.mutation_kind, RuleMutationKind.CREATE_PLAN)
        self.assertEqual(created, replay)
        plan = created.result
        self.assertEqual(plan.state.value, "pending")
        self.assertEqual(plan.version_id, "version-promo")
        self.assertEqual(plan.restore_version_id, "version-daily")
        stored_create = await self.store.read_operation(
            "binding-plans",
            "plan-create-1",
            actor_id="admin-1",
            session_digest=_digest(_ADMIN_COOKIE),
        )
        self.assertEqual(stored_create, created)
        schedule = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans("binding-plans")
        self.assertEqual(schedule.items, (plan,))

        overlapping = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-overlap",
                CreateRuleActivationPlan(
                    "version-daily",
                    "version-promo",
                    activate_at + timedelta(minutes=30),
                    deactivate_at + timedelta(minutes=30),
                    "Asia/Shanghai",
                ),
            )
        )
        self.assertEqual(overlapping.status, RuleOperationStatus.REJECTED)
        self.assertEqual(overlapping.reason, RuleOperationRejection.CONFLICT)

        cancelled = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-cancel-1",
                CancelRuleActivationPlan(plan.id, plan.revision, "schedule changed"),
            )
        )
        self.assertEqual(cancelled.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(cancelled.mutation_kind, RuleMutationKind.CANCEL_PLAN)
        self.assertEqual(cancelled.result.state.value, "cancelled")
        self.assertNotEqual(cancelled.result.revision, plan.revision)
        stale_cancel = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-cancel-stale",
                CancelRuleActivationPlan(plan.id, plan.revision, "stale"),
            )
        )
        self.assertEqual(stale_cancel.reason, RuleOperationRejection.CONFLICT)
        async with self.engine.connect() as connection:
            saved = await connection.execute(
                select(RuleActivationPlanRecord.__table__).where(
                    RuleActivationPlanRecord.plan_id == plan.id
                )
            )
            row = saved.mappings().one()
            self.assertEqual(row["state"], "cancelled")
            self.assertEqual(row["revision"], cancelled.result.revision)

        blocked_created = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-create-blocked",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    activate_at + timedelta(hours=2),
                    deactivate_at + timedelta(hours=2),
                    "Asia/Shanghai",
                ),
            )
        )
        blocked_plan = blocked_created.result
        blocked_revision = "plan-blocked-revision"
        async with self.engine.begin() as connection:
            await connection.execute(
                update(RuleActivationPlanRecord)
                .where(RuleActivationPlanRecord.plan_id == blocked_plan.id)
                .values(state="blocked", revision=blocked_revision)
            )

        stale_blocked_cancel = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-cancel-blocked-stale",
                CancelRuleActivationPlan(
                    blocked_plan.id, blocked_plan.revision, "stale blocked plan"
                ),
            )
        )
        self.assertEqual(stale_blocked_cancel.reason, RuleOperationRejection.CONFLICT)
        blocked_cancel = await self._mutate(
            RuleMutationCommand(
                "binding-plans",
                "plan-cancel-blocked-current",
                CancelRuleActivationPlan(
                    blocked_plan.id, blocked_revision, "cancel blocked plan"
                ),
            )
        )
        self.assertEqual(blocked_cancel.status, RuleOperationStatus.COMPLETED)
        self.assertEqual(blocked_cancel.result.state.value, "cancelled")
        self.assertNotEqual(blocked_cancel.result.revision, blocked_revision)

    async def test_scheduled_publication_identity_does_not_require_browser_session(self) -> None:
        await self._seed_plan_versions("binding-scheduled-origin")
        created = await self._mutate(
            RuleMutationCommand(
                "binding-scheduled-origin",
                "plan-scheduled-origin",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW + timedelta(hours=2),
                    _NOW + timedelta(hours=3),
                    "Asia/Shanghai",
                ),
            )
        )
        plan = created.result
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RuleMutationOperationRecord).values(
                    request_key="system-plan-activation-test",
                    operation_id="system-operation-activation-test",
                    binding_id=plan.binding_id,
                    actor_account_id=None,
                    session_hash=None,
                    origin_plan_id=plan.id,
                    origin_phase="activation",
                    fingerprint_key_id="key-1",
                    fingerprint_digest="a" * 64,
                    mutation_kind="publish",
                    status="pending",
                    reason=None,
                    result=None,
                    work_payload={"schemaVersion": 1},
                    created_at=_NOW,
                )
            )
        async with self.engine.connect() as connection:
            stored = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key
                        == "system-plan-activation-test"
                    )
                )
            ).mappings().one()
        self.assertIsNone(stored["actor_account_id"])
        self.assertIsNone(stored["session_hash"])
        self.assertEqual(stored["origin_plan_id"], plan.id)
        self.assertEqual(stored["origin_phase"], "activation")

        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as connection:
                await connection.execute(
                    insert(RuleMutationOperationRecord).values(
                        request_key="system-plan-origin-missing",
                        operation_id="system-operation-origin-missing",
                        binding_id=plan.binding_id,
                        actor_account_id=None,
                        session_hash=None,
                        origin_plan_id=None,
                        origin_phase=None,
                        fingerprint_key_id="key-1",
                        fingerprint_digest="b" * 64,
                        mutation_kind="publish",
                        status="pending",
                        reason=None,
                        result=None,
                        work_payload={"schemaVersion": 1},
                        created_at=_NOW,
                    )
                )

    async def test_due_activation_plan_enqueues_one_durable_system_publication(self):
        await self._seed_plan_versions("binding-plan-scheduled-enqueue")
        created = await self._mutate(
            RuleMutationCommand(
                "binding-plan-scheduled-enqueue",
                "plan-scheduled-enqueue-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=2),
                    "Asia/Shanghai",
                ),
            )
        )
        self.assertEqual(created.status, RuleOperationStatus.COMPLETED)

        worker = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(self.engine),
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )
        first = await worker.run_once()
        self.assertEqual(first, (RuleActivationPlanWorkerOutcome.ENQUEUED,))
        in_flight = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans("binding-plan-scheduled-enqueue")
        self.assertEqual(in_flight.items[0].state.value, "activating")

        async with self.engine.connect() as connection:
            operation = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.origin_plan_id == created.result.id,
                        RuleMutationOperationRecord.origin_phase == "activation",
                    )
                )
            ).mappings().one()
            publication = (
                await connection.execute(
                    select(RulePublicationRecord.__table__).where(
                        RulePublicationRecord.publication_id
                        == operation["work_payload"]["publicationId"]
                    )
                )
            ).mappings().one()
            audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == created.result.id,
                )
            )
        self.assertEqual(operation["status"], "pending")
        self.assertIsNone(operation["actor_account_id"])
        self.assertIsNone(operation["session_hash"])
        self.assertEqual(operation["work_payload"]["versionId"], "version-promo")
        self.assertEqual(
            operation["work_payload"]["expectedVersionId"], "version-daily"
        )
        self.assertEqual(publication["target_version_id"], "version-promo")
        self.assertEqual(publication["base_version_id"], "version-daily")
        self.assertEqual(audit_count, 1)

        replay_worker = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(self.engine),
            publication_enqueuer=self.store,
            clock=lambda: _NOW + timedelta(minutes=2),
        )
        replay = await replay_worker.run_once()
        self.assertEqual(replay, (RuleActivationPlanWorkerOutcome.ENQUEUED,))
        async with self.engine.connect() as connection:
            operation_count = await connection.scalar(
                select(func.count()).select_from(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id == created.result.id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            audit_count_after_replay = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == created.result.id,
                )
            )
        self.assertEqual(operation_count, 1)
        self.assertEqual(audit_count_after_replay, 1)

    async def test_due_restoration_uses_activated_version_as_cas_baseline(self):
        await self._seed_plan_versions("binding-plan-scheduled-restore")
        created = await self._mutate(
            RuleMutationCommand(
                "binding-plan-scheduled-restore",
                "plan-scheduled-restore-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(hours=2),
                    _NOW - timedelta(minutes=1),
                    "Asia/Shanghai",
                ),
            )
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                update(RuleActivationPlanRecord)
                .where(RuleActivationPlanRecord.plan_id == created.result.id)
                .values(state="active")
            )

        worker = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(self.engine),
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )
        self.assertEqual(
            await worker.run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        async with self.engine.connect() as connection:
            operation = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.origin_plan_id == created.result.id,
                        RuleMutationOperationRecord.origin_phase == "restoration",
                    )
                )
            ).mappings().one()
            audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.restore",
                    AuditEventRecord.target_id == created.result.id,
                )
            )
        self.assertEqual(operation["work_payload"]["versionId"], "version-daily")
        self.assertEqual(
            operation["work_payload"]["expectedVersionId"], "version-promo"
        )
        self.assertEqual(operation["origin_phase"], "restoration")
        self.assertEqual(audit_count, 1)

    async def test_activation_unknown_provider_write_recovers_same_publication_without_rewrite(self):
        binding_id = "binding-plan-unknown-write"
        await self._seed_plan_versions(binding_id)
        created = await self._mutate(
            RuleMutationCommand(
                binding_id,
                "plan-unknown-write-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=2),
                    "Asia/Shanghai",
                ),
            )
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )
        self.assertEqual(
            await scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )

        versions = SqlAlchemyRuleVersionReader(self.engine)
        encoder = SentinelRuleVersionJsonEncoder("sentinel-profile-v1")
        daily_baseline = encoder.encode_rule_version(
            await ReadRuleVersion(versions).execute(binding_id, "version-daily")
        )
        provider = _UnknownOnceAfterCasProvider(daily_baseline)
        publication_reader = ReadRulePublication(
            SqlAlchemyRulePublicationReader(self.engine)
        )
        publish_worker = RunRulePublicationWorker(
            outbox=SqlAlchemyRulePublishOutbox(self.engine),
            publication_reader=publication_reader,
            version_reader=ReadRuleVersion(versions),
            source_connection_resolver=ResolveRegisteredSourceConnection(
                _TestCredentialResolver()
            ),
            payload_encoder=encoder,
            provider=provider,
            clock=lambda: _NOW + timedelta(seconds=5),
        )
        self.assertEqual(
            await publish_worker.run_once(),
            (RulePublicationWorkerOutcome.UNKNOWN,),
        )
        in_flight = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(in_flight.items[0].state.value, "activating")
        activation_publication_id = in_flight.items[0].activation_publication_id
        self.assertIsNotNone(activation_publication_id)
        self.assertEqual(provider.write_calls, 1)

        async with self.engine.connect() as connection:
            unknown_publication = (
                await connection.execute(
                    select(RulePublicationRecord.__table__).where(
                        RulePublicationRecord.publication_id
                        == activation_publication_id
                    )
                )
            ).mappings().one()
        self.assertEqual(unknown_publication["write_state"], "unknown")
        self.assertEqual(unknown_publication["read_back_state"], "awaiting")

        # Reclaiming the plan must reuse the pending operation and publication;
        # it may not turn an unknown write into a new external attempt.
        recovered_scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW + timedelta(seconds=61),
        )
        self.assertEqual(
            await recovered_scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        recovered_publish_worker = RunRulePublicationWorker(
            outbox=SqlAlchemyRulePublishOutbox(self.engine),
            publication_reader=publication_reader,
            version_reader=ReadRuleVersion(versions),
            source_connection_resolver=ResolveRegisteredSourceConnection(
                _TestCredentialResolver()
            ),
            payload_encoder=encoder,
            provider=provider,
            clock=lambda: _NOW + timedelta(minutes=2),
        )
        self.assertEqual(
            await recovered_publish_worker.run_once(),
            (RulePublicationWorkerOutcome.COMPLETED,),
        )
        self.assertEqual(provider.write_calls, 1)

        completed_scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW + timedelta(minutes=3),
        )
        self.assertEqual(
            await completed_scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )
        completed_plan = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(completed_plan.items[0].state.value, "active")
        self.assertEqual(
            completed_plan.items[0].activation_publication_id,
            activation_publication_id,
        )
        async with self.engine.connect() as connection:
            operation_count = await connection.scalar(
                select(func.count()).select_from(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id == created.result.id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            publication_count = await connection.scalar(
                select(func.count()).select_from(RulePublicationRecord).where(
                    RulePublicationRecord.publication_id == activation_publication_id
                )
            )
            completed_audits = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == created.result.id,
                    AuditEventRecord.outcome == "completed",
                )
            )
        self.assertEqual(operation_count, 1)
        self.assertEqual(publication_count, 1)
        self.assertEqual(completed_audits, 1)

    async def test_provider_cas_conflict_blocks_plan_without_restoration_publication(self):
        binding_id = "binding-plan-provider-conflict"
        await self._seed_plan_versions(binding_id)
        created = await self._mutate(
            RuleMutationCommand(
                binding_id,
                "plan-provider-conflict-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=1),
                    "Asia/Shanghai",
                ),
            )
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )
        self.assertEqual(
            await scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )

        versions = SqlAlchemyRuleVersionReader(self.engine)
        encoder = SentinelRuleVersionJsonEncoder("sentinel-profile-v1")
        baseline = encoder.encode_rule_version(
            await ReadRuleVersion(versions).execute(binding_id, "version-daily")
        )
        provider = _ExternalChangeBeforeCasProvider(baseline)
        publish_worker = RunRulePublicationWorker(
            outbox=SqlAlchemyRulePublishOutbox(self.engine),
            publication_reader=ReadRulePublication(
                SqlAlchemyRulePublicationReader(self.engine)
            ),
            version_reader=ReadRuleVersion(versions),
            source_connection_resolver=ResolveRegisteredSourceConnection(
                _TestCredentialResolver()
            ),
            payload_encoder=encoder,
            provider=provider,
            clock=lambda: _NOW + timedelta(seconds=5),
        )
        self.assertEqual(
            await publish_worker.run_once(),
            (RulePublicationWorkerOutcome.REJECTED,),
        )
        self.assertEqual(provider.write_calls, 1)
        self.assertEqual(
            provider.snapshot,
            RuleConfigurationSnapshot("external-revision", b"external rules"),
        )

        resumed_scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW + timedelta(seconds=61),
        )
        self.assertEqual(
            await resumed_scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.BLOCKED,),
        )
        blocked = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(blocked.items[0].state.value, "blocked")

        after_restore_window = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW + timedelta(minutes=3),
        )
        self.assertEqual(await after_restore_window.run_once(), ())
        async with self.engine.connect() as connection:
            restoration_count = await connection.scalar(
                select(func.count()).select_from(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id == created.result.id,
                    RuleMutationOperationRecord.origin_phase == "restoration",
                )
            )
            publication = (
                await connection.execute(
                    select(RulePublicationRecord.__table__).where(
                        RulePublicationRecord.binding_id == binding_id
                    )
                )
            ).mappings().one()
        self.assertEqual(restoration_count, 0)
        self.assertEqual(publication["write_state"], "failed")
        self.assertEqual(publication["write_reason"], "conflict")

    async def test_external_change_after_activation_blocks_restore_without_overwrite(self):
        binding_id = "binding-plan-external-before-restore"
        await self._seed_plan_versions(binding_id)
        created = await self._mutate(
            RuleMutationCommand(
                binding_id,
                "plan-external-before-restore-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=2),
                    "Asia/Shanghai",
                ),
            )
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )
        self.assertEqual(
            await scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )

        outbox = SqlAlchemyRulePublishOutbox(self.engine)
        activation_claim = (
            await outbox.claim_ready(
                now=_NOW + timedelta(seconds=1),
                lease_expires_at=_NOW + timedelta(minutes=1),
                supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
            )
        )[0]
        for phase_index, phase_name in enumerate((
            PublicationPhaseName.VALIDATION,
            PublicationPhaseName.CONFIGURATION_WRITE,
            PublicationPhaseName.READ_BACK,
        )):
            started_at = _NOW + timedelta(seconds=2 + phase_index * 2)
            await outbox.advance_claimed_phase(
                activation_claim,
                phase_name,
                expected_state=PublicationStage.AWAITING,
                next_phase=PublicationPhase(
                    PublicationStage.RUNNING, started_at, None
                ),
            )
            await outbox.advance_claimed_phase(
                activation_claim,
                phase_name,
                expected_state=PublicationStage.RUNNING,
                next_phase=PublicationPhase(
                    PublicationStage.SUCCEEDED,
                    started_at + timedelta(seconds=1),
                    None,
                ),
            )
        await outbox.complete_claimed_publication(
            activation_claim, completed_at=_NOW + timedelta(seconds=8)
        )
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=self.store,
                clock=lambda: _NOW + timedelta(seconds=61),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )
        active = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(active.items[0].state.value, "active")

        versions = SqlAlchemyRuleVersionReader(self.engine)
        encoder = SentinelRuleVersionJsonEncoder("sentinel-profile-v1")
        baseline = encoder.encode_rule_version(
            await ReadRuleVersion(versions).execute(binding_id, "version-promo")
        )
        provider = _ExternalChangeBeforeCasProvider(baseline)
        provider.snapshot = RuleConfigurationSnapshot(
            "external-revision", b"external rules after activation"
        )
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=self.store,
                clock=lambda: _NOW + timedelta(minutes=3),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        restore_worker = RunRulePublicationWorker(
            outbox=outbox,
            publication_reader=ReadRulePublication(
                SqlAlchemyRulePublicationReader(self.engine)
            ),
            version_reader=ReadRuleVersion(versions),
            source_connection_resolver=ResolveRegisteredSourceConnection(
                _TestCredentialResolver()
            ),
            payload_encoder=encoder,
            provider=provider,
            clock=lambda: _NOW + timedelta(minutes=3, seconds=1),
        )
        self.assertEqual(
            await restore_worker.run_once(),
            (RulePublicationWorkerOutcome.REJECTED,),
        )
        self.assertEqual(provider.write_calls, 0)
        self.assertEqual(
            provider.snapshot,
            RuleConfigurationSnapshot(
                "external-revision", b"external rules after activation"
            ),
        )

        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=self.store,
                clock=lambda: _NOW + timedelta(minutes=4, seconds=1),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.BLOCKED,),
        )
        blocked = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(blocked.items[0].state.value, "blocked")
        self.assertEqual(
            blocked.items[0].activation_publication_id,
            activation_claim.publication_id,
        )
        async with self.engine.connect() as connection:
            restoration_operations = await connection.scalar(
                select(func.count()).select_from(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id == created.result.id,
                    RuleMutationOperationRecord.origin_phase == "restoration",
                )
            )
            restoration = (
                await connection.execute(
                    select(RulePublicationRecord.__table__).where(
                        RulePublicationRecord.binding_id == binding_id,
                        RulePublicationRecord.publication_id
                        == blocked.items[0].restore_publication_id,
                    )
                )
            ).mappings().one()
        self.assertEqual(restoration_operations, 1)
        self.assertEqual(restoration["validation_reason"], "conflict")
        self.assertEqual(restoration["validation_state"], "failed")
        self.assertEqual(restoration["write_state"], "awaiting")

    async def test_missing_scheduled_publication_target_rejects_and_blocks_plan(self):
        binding_id = "missing-target-binding"
        await self._seed_plan_versions(binding_id)
        created = await self._mutate(
            RuleMutationCommand(
                binding_id,
                "plan-missing-target-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=2),
                    "Asia/Shanghai",
                ),
            )
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(self.engine),
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )

        self.assertEqual(
            await worker.run_once(), (RuleActivationPlanWorkerOutcome.BLOCKED,)
        )
        async with self.engine.connect() as connection:
            operation = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.origin_plan_id == created.result.id,
                        RuleMutationOperationRecord.origin_phase == "activation",
                    )
                )
            ).mappings().one()
            audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == created.result.id,
                    AuditEventRecord.outcome == "rejected",
                )
            )
        self.assertEqual(operation["status"], "rejected")
        self.assertEqual(operation["reason"], "unavailable")
        self.assertIsNone(operation["actor_account_id"])
        blocked = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(blocked.items[0].state.value, "blocked")
        self.assertEqual(audit_count, 1)

    async def test_plan_advances_only_after_activation_and_restoration_readback(self):
        binding_id = "binding-plan-scheduled-full-flow"
        await self._seed_plan_versions(binding_id)
        await self._mutate(
            RuleMutationCommand(
                binding_id,
                "plan-scheduled-full-flow-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=2),
                    "Asia/Shanghai",
                ),
            )
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=self.store,
            clock=lambda: _NOW,
        )
        outbox = SqlAlchemyRulePublishOutbox(self.engine)

        async def complete_next_publication(now):
            claims = await outbox.claim_ready(
                now=now,
                lease_expires_at=now + timedelta(minutes=1),
                supported_providers=frozenset({ConfigurationSourceProvider.NACOS}),
            )
            self.assertEqual(len(claims), 1)
            claim = claims[0]
            for index, name in enumerate((
                PublicationPhaseName.VALIDATION,
                PublicationPhaseName.CONFIGURATION_WRITE,
                PublicationPhaseName.READ_BACK,
            )):
                phase_started_at = now + timedelta(seconds=index * 2)
                phase_succeeded_at = phase_started_at + timedelta(seconds=1)
                await outbox.advance_claimed_phase(
                    claim,
                    name,
                    expected_state=PublicationStage.AWAITING,
                    next_phase=PublicationPhase(
                        PublicationStage.RUNNING, phase_started_at, None
                    ),
                )
                await outbox.advance_claimed_phase(
                    claim,
                    name,
                    expected_state=PublicationStage.RUNNING,
                    next_phase=PublicationPhase(
                        PublicationStage.SUCCEEDED, phase_succeeded_at, None
                    ),
                )
            return await outbox.complete_claimed_publication(
                claim, completed_at=now + timedelta(seconds=6)
            )

        self.assertEqual(
            await scheduler.run_once(), (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        )
        await complete_next_publication(_NOW + timedelta(seconds=1))
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=self.store,
                clock=lambda: _NOW + timedelta(seconds=61),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )

        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=self.store,
                clock=lambda: _NOW + timedelta(minutes=3),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        await complete_next_publication(_NOW + timedelta(minutes=3, seconds=1))
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=self.store,
                clock=lambda: _NOW + timedelta(minutes=4),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )

        final = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(final.items[0].state.value, "completed")
        self.assertIsNotNone(final.items[0].activation_publication_id)
        self.assertIsNotNone(final.items[0].restore_publication_id)

    async def test_activation_recovers_completed_publication_after_lost_plan_association(self):
        binding_id = "binding-plan-lost-association"
        await self._seed_plan_versions(binding_id)
        created = await self._mutate(
            RuleMutationCommand(
                binding_id,
                "plan-lost-association-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(minutes=2),
                    _NOW + timedelta(minutes=2),
                    "Asia/Shanghai",
                ),
            )
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        first_claim = (
            await queue.claim_due(
                now=_NOW,
                lease_expires_at=_NOW + timedelta(seconds=60),
            )
        )[0]

        # Simulate a worker that durably enqueued the operation and then exited
        # before associating it with the plan. A later process has no memory of
        # this claim; only the database operation/outbox can recover it.
        scheduled = await self.store.enqueue_scheduled_publication(
            first_claim, now=_NOW
        )
        self.assertEqual(scheduled.state.value, "pending")
        self.assertIsNotNone(scheduled.publication_id)

        outbox = SqlAlchemyRulePublishOutbox(self.engine)
        publication_claim = (
            await outbox.claim_ready(
                now=_NOW + timedelta(seconds=1),
                lease_expires_at=_NOW + timedelta(minutes=1),
                supported_providers=frozenset(
                    {ConfigurationSourceProvider.NACOS}
                ),
            )
        )[0]
        phase_names = (
            PublicationPhaseName.VALIDATION,
            PublicationPhaseName.CONFIGURATION_WRITE,
            PublicationPhaseName.READ_BACK,
        )
        for index, phase_name in enumerate(phase_names):
            phase_started_at = _NOW + timedelta(seconds=2 + index * 2)
            await outbox.advance_claimed_phase(
                publication_claim,
                phase_name,
                expected_state=PublicationStage.AWAITING,
                next_phase=PublicationPhase(
                    PublicationStage.RUNNING, phase_started_at, None
                ),
            )
            await outbox.advance_claimed_phase(
                publication_claim,
                phase_name,
                expected_state=PublicationStage.RUNNING,
                next_phase=PublicationPhase(
                    PublicationStage.SUCCEEDED,
                    phase_started_at + timedelta(seconds=1),
                    None,
                ),
            )
        completed_publication = await outbox.complete_claimed_publication(
            publication_claim, completed_at=_NOW + timedelta(seconds=8)
        )
        self.assertEqual(completed_publication.result.id, scheduled.publication_id)

        restarted_queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        restarted_store = SqlAlchemyRuleMutationStore(
            self.engine,
            fingerprint_keys={"key-1": _KEY},
            active_fingerprint_key_id="key-1",
            binding_reader=_TestBindingReader(),
            publication_target_reader=self.publication_target_reader,
        )
        restarted_scheduler = RunRuleActivationPlanWorker(
            work_queue=restarted_queue,
            publication_enqueuer=restarted_store,
            clock=lambda: _NOW + timedelta(seconds=61),
        )
        self.assertEqual(
            await restarted_scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )

        plans = await SqlAlchemyRuleActivationPlanReader(
            self.engine
        ).read_rule_activation_plans(binding_id)
        self.assertEqual(plans.items[0].state.value, "active")
        self.assertEqual(
            plans.items[0].activation_publication_id, scheduled.publication_id
        )
        async with self.engine.connect() as connection:
            operation_count = await connection.scalar(
                select(func.count()).select_from(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id == created.result.id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            publication_count = await connection.scalar(
                select(func.count()).select_from(RulePublicationRecord).where(
                    RulePublicationRecord.publication_id == scheduled.publication_id
                )
            )
            accepted_audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == created.result.id,
                    AuditEventRecord.outcome == "accepted",
                )
            )
            completed_audit_count = await connection.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == created.result.id,
                    AuditEventRecord.outcome == "completed",
                )
            )
        self.assertEqual(operation_count, 1)
        self.assertEqual(publication_count, 1)
        self.assertEqual(accepted_audit_count, 1)
        self.assertEqual(completed_audit_count, 1)

    async def test_activation_plan_work_queue_fences_claims_and_recovers_expired_lease(self) -> None:
        await self._seed_plan_versions("binding-plan-queue")
        created = await self._mutate(
            RuleMutationCommand(
                "binding-plan-queue",
                "plan-queue-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(hours=2),
                    _NOW + timedelta(hours=2),
                    "Asia/Shanghai",
                ),
            )
        )
        self.assertEqual(created.status, RuleOperationStatus.COMPLETED)
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        first = await queue.claim_due(
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=1),
        )
        self.assertEqual(len(first), 1)
        first_claim = first[0]
        self.assertEqual(first_claim.plan.state.value, "activating")
        self.assertEqual(first_claim.attempt, 1)
        self.assertEqual(await queue.claim_due(
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=1),
        ), ())

        renewed = await queue.renew_claim(
            first_claim,
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=2),
        )
        self.assertEqual(renewed.claim_token, first_claim.claim_token)
        self.assertEqual(renewed.lease_expires_at, _NOW + timedelta(minutes=2))

        recovered = await queue.claim_due(
            now=_NOW + timedelta(minutes=2, milliseconds=1),
            lease_expires_at=_NOW + timedelta(minutes=3),
        )
        self.assertEqual(len(recovered), 1)
        recovery_claim = recovered[0]
        self.assertEqual(recovery_claim.plan.state.value, "activating")
        self.assertEqual(recovery_claim.attempt, 2)
        self.assertNotEqual(recovery_claim.claim_token, first_claim.claim_token)
        with self.assertRaises(RuleActivationPlanClaimConflict):
            await queue.renew_claim(
                first_claim,
                now=_NOW + timedelta(minutes=2, milliseconds=1),
                lease_expires_at=_NOW + timedelta(minutes=3),
            )
        blocked = await queue.block_claim(
            recovery_claim,
            now=_NOW + timedelta(minutes=2, milliseconds=1),
        )
        self.assertEqual(blocked.state.value, "blocked")
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(RuleActivationPlanRecord.__table__).where(
                        RuleActivationPlanRecord.plan_id == created.result.id
                    )
                )
            ).mappings().one()
        self.assertIsNone(row["claim_token"])
        self.assertIsNone(row["claim_lease_expires_at"])

    async def test_activation_plan_work_queue_claims_due_restoration_phase(self) -> None:
        await self._seed_plan_versions("binding-plan-restore")
        created = await self._mutate(
            RuleMutationCommand(
                "binding-plan-restore",
                "plan-restore-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(hours=3),
                    _NOW - timedelta(hours=1),
                    "Asia/Shanghai",
                ),
            )
        )
        plan = created.result
        async with self.engine.begin() as connection:
            await connection.execute(
                update(RuleActivationPlanRecord)
                .where(RuleActivationPlanRecord.plan_id == plan.id)
                .values(state="active")
            )
        claimed = await SqlAlchemyRuleActivationPlanWorkQueue(
            self.engine
        ).claim_due(
            now=_NOW,
            lease_expires_at=_NOW + timedelta(minutes=1),
        )
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].plan.state.value, "restoring")

    async def test_activation_plan_work_queue_requires_verified_publication_before_transition(self) -> None:
        await self._seed_plan_versions("binding-plan-verified")
        created = await self._mutate(
            RuleMutationCommand(
                "binding-plan-verified",
                "plan-verified-create",
                CreateRuleActivationPlan(
                    "version-promo",
                    "version-daily",
                    _NOW - timedelta(hours=1),
                    _NOW + timedelta(hours=1),
                    "Asia/Shanghai",
                ),
            )
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(self.engine)
        claim = (
            await queue.claim_due(
                now=_NOW,
                lease_expires_at=_NOW + timedelta(minutes=1),
            )
        )[0]
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationRecord).values(
                    publication_id="publication-plan-activation",
                    binding_id="binding-plan-verified",
                    target_version_id="version-promo",
                    target_checksum="sha256:plan",
                    base_version_id=None,
                    created_at=_NOW,
                    validation_state="succeeded",
                    validation_observed_at=_NOW,
                    validation_reason=None,
                    write_state="succeeded",
                    write_observed_at=_NOW,
                    write_reason=None,
                    read_back_state="unknown",
                    read_back_observed_at=_NOW,
                    read_back_reason="unknown",
                )
            )
        associated = await queue.associate_publication(
            claim,
            "publication-plan-activation",
            now=_NOW,
        )
        self.assertEqual(
            associated.plan.activation_publication_id,
            "publication-plan-activation",
        )
        with self.assertRaises(RuleActivationPlanClaimConflict):
            await queue.complete_phase(associated, now=_NOW)

        async with self.engine.begin() as connection:
            await connection.execute(
                update(RulePublicationRecord)
                .where(
                    RulePublicationRecord.publication_id
                    == "publication-plan-activation"
                )
                .values(
                    read_back_state="succeeded",
                    read_back_reason=None,
                    read_back_observed_at=_NOW,
                )
            )
        activated = await queue.complete_phase(associated, now=_NOW)
        self.assertEqual(activated.state.value, "active")
        self.assertEqual(activated.activation_publication_id, "publication-plan-activation")

        async with self.engine.begin() as connection:
            await connection.execute(
                update(RuleActivationPlanRecord)
                .where(RuleActivationPlanRecord.plan_id == created.result.id)
                .values(deactivate_at=_NOW - timedelta(milliseconds=1))
            )
        restoration = (
            await queue.claim_due(
                now=_NOW,
                lease_expires_at=_NOW + timedelta(minutes=1),
            )
        )[0]
        self.assertEqual(restoration.plan.state.value, "restoring")
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RulePublicationRecord).values(
                    publication_id="publication-plan-restoration",
                    binding_id="binding-plan-verified",
                    target_version_id="version-daily",
                    target_checksum="sha256:plan",
                    base_version_id="version-promo",
                    created_at=_NOW,
                    validation_state="succeeded",
                    validation_observed_at=_NOW,
                    validation_reason=None,
                    write_state="succeeded",
                    write_observed_at=_NOW,
                    write_reason=None,
                    read_back_state="succeeded",
                    read_back_observed_at=_NOW,
                    read_back_reason=None,
                )
            )
        restoration = await queue.associate_publication(
            restoration,
            "publication-plan-restoration",
            now=_NOW,
        )
        completed = await queue.complete_phase(restoration, now=_NOW)
        self.assertEqual(completed.state.value, "completed")
        self.assertEqual(completed.restore_publication_id, "publication-plan-restoration")

    async def test_rule_command_http_route_uses_the_sql_authority(self) -> None:
        app = build_app(
            bootstrap_initialization_reader=_Initialized(),
            setup_window_reader=_SetupWindow(),
            bootstrap_operator_verifier=_OperatorVerifier(),
            current_session_reader=SqlAlchemyCurrentSessionReader(self.engine),
            current_session_revoker=SqlAlchemyCurrentSessionRevoker(self.engine),
            account_directory_reader=SqlAlchemyAccountDirectoryReader(self.engine),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_mutation_authority=self.store,
        )
        candidate = {
            "bindingId": "binding-http",
            "profile": "sentinel-profile-v1",
            "kind": "flow",
            "baseVersionId": None,
            "baseChecksum": "sha256:empty",
            "sourceRevision": None,
            "rules": [{"recordId": None, "rule": {"kind": "flow", "value": {
                "resource": "/orders", "limitApp": "default", "grade": 1,
                "count": 3, "strategy": 0, "controlBehavior": 0,
                "clusterMode": False,
            }}}],
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            client.cookies.set("sentinel_session", _ADMIN_COOKIE)
            client.cookies.set("__Host-sentinel_csrf", _ADMIN_CSRF)
            response = await client.post(
                "/api/v1/rulesets/binding-http/commands",
                headers={
                    "origin": "https://console.test",
                    "x-request-id": "http-rule-request",
                    "x-sentinel-csrf": _ADMIN_CSRF,
                    "idempotency-key": "http-rule-save",
                },
                json={"requestKey": "http-rule-save", "mutation": {
                    "kind": "save_draft", "draftId": None,
                    "expectedRevision": None, "candidate": candidate,
                }},
            )
            receipt = await client.get(
                "/api/v1/rulesets/binding-http/operations/http-rule-save",
                headers={"x-request-id": "http-rule-read"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(response.json()["result"]["kind"], "save_draft")
        self.assertEqual(receipt.json(), response.json())

    async def _seed_plan_versions(self, binding_id: str) -> None:
        candidate = _flow_candidate(binding_id, count=17, record_id="plan-record")
        checksum = candidate_checksum(candidate)
        records = [
            rule_record_body(RuleRecord("plan-record", candidate.rules[0].rule))
        ]
        async with self.engine.begin() as connection:
            for version_id in ("version-promo", "version-daily"):
                validation_id = f"validation-{version_id}"
                await connection.execute(
                    insert(RuleValidationReceiptRecord).values(
                        validation_id=validation_id,
                        binding_id=binding_id,
                        profile=candidate.profile,
                        base_checksum=candidate.base_checksum,
                        candidate_checksum=checksum,
                        is_publishable=True,
                        issues=[],
                        actor_account_id="admin-1",
                        request_id=f"request-{version_id}",
                        created_at=_NOW,
                    )
                )
                await connection.execute(
                    insert(RuleSetVersionRecord).values(
                        version_id=version_id,
                        binding_id=binding_id,
                        kind=candidate.kind.value,
                        profile=candidate.profile,
                        base_version_id=None,
                        checksum=checksum,
                        name=version_id,
                        note="fixture",
                        validation_id=validation_id,
                        records=records,
                        created_at=_NOW,
                        created_by_account_id="admin-1",
                    )
                )

    async def _seed_nacos_baseline_version(self, binding_id: str) -> str:
        """Persist the exact rule version used as the live Nacos CAS baseline."""
        candidate = _flow_candidate(
            binding_id, count=9, record_id="nacos-baseline-record"
        )
        checksum = candidate_checksum(candidate)
        validation_id = "validation-nacos-baseline"
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(RuleValidationReceiptRecord).values(
                    validation_id=validation_id,
                    binding_id=binding_id,
                    profile=candidate.profile,
                    base_checksum=candidate.base_checksum,
                    candidate_checksum=checksum,
                    is_publishable=True,
                    issues=[],
                    actor_account_id="admin-1",
                    request_id="request-nacos-baseline",
                    created_at=_NOW,
                )
            )
            await connection.execute(
                insert(RuleSetVersionRecord).values(
                    version_id="version-nacos-baseline",
                    binding_id=binding_id,
                    kind=candidate.kind.value,
                    profile=candidate.profile,
                    base_version_id=None,
                    checksum=checksum,
                    name="Nacos acceptance baseline",
                    note="synthetic baseline for isolated acceptance",
                    validation_id=validation_id,
                    records=[
                        rule_record_body(
                            RuleRecord(
                                "nacos-baseline-record",
                                candidate.rules[0].rule,
                            )
                        )
                    ],
                    created_at=_NOW,
                    created_by_account_id="admin-1",
                )
            )
        return checksum


def _flow_candidate(binding_id: str, count: int, record_id: str | None = None):
    return parse_rule_candidate({
        "bindingId": binding_id,
        "profile": "sentinel-profile-v1",
        "kind": "flow",
        "baseVersionId": None,
        "baseChecksum": "sha256:empty",
        "sourceRevision": None,
        "rules": [{
            "recordId": record_id,
            "rule": {"kind": "flow", "value": {
                "resource": "/orders", "limitApp": "default", "grade": 1,
                "count": count, "strategy": 0, "controlBehavior": 0,
                "clusterMode": False,
            }},
        }],
    })


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _SetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _TestBindingReader:
    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        if binding_id == "missing-binding":
            return None
        suffix = binding_id.rsplit("-", 1)[-1]
        kind = {
            "flow": RuleKind.FLOW,
            "degrade": RuleKind.DEGRADE,
            "system": RuleKind.SYSTEM,
            "authority": RuleKind.AUTHORITY,
            "param": RuleKind.PARAM,
        }.get(suffix, RuleKind.FLOW)
        return RuleBinding(
            id=binding_id,
            environment_id="test",
            app_id="test-app",
            kind=kind,
            profile="sentinel-profile-v1",
            source_id="test-source",
            source_label="Test Source",
            location="https://config.test/rules",
        )


class _TestPublicationTargetReader:
    def __init__(self) -> None:
        self.current_revision = "mapping-rev-7"
        self.current_source_revision = "source-rev-3"
        self.current_data_id = "test-app.flow.json"
        self.nacos_namespace = "test-namespace"
        self.nacos_group = "SENTINEL_RULES"
        self.consul_key = "sentinel/prod/rules"
        self.provider = ConfigurationSourceProvider.NACOS

    async def read_rule_publication_target(self, binding_id: str):
        if binding_id == "missing-target-binding":
            return None
        target = (
            ConsulRulePublicationTarget(
                binding_id=binding_id,
                source_id="test-source",
                key=self.consul_key,
            )
            if self.provider is ConfigurationSourceProvider.CONSUL
            else NacosRulePublicationTarget(
                binding_id=binding_id,
                source_id="test-source",
                namespace=self.nacos_namespace,
                group=self.nacos_group,
                data_id=self.current_data_id,
            )
        )
        return VersionedRulePublicationTarget(
            revision=self.current_revision,
            source_revision=self.current_source_revision,
            target=target,
        )


class _TestCredentialResolver:
    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint="https://config.example.test",
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )


class _LocalConsulCredentialResolver:
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint

    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint=self._endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )


class _LocalNacosCredentialResolver:
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint

    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint=self._endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )


def _wait_for_consul(endpoint: str) -> None:
    deadline = time.monotonic() + 45
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{endpoint}/v1/status/leader", timeout=1) as response:
                if response.status == 200 and response.read().strip() != b'""':
                    return
        except OSError as error:
            last_error = error
        time.sleep(0.2)
    raise AssertionError(f"disposable Consul did not become ready: {last_error!r}")


def _free_loopback_port_pair() -> tuple[int, int]:
    """Find two currently unused loopback ports that preserve Nacos +1000."""
    for _ in range(64):
        with socket.socket() as http_socket:
            http_socket.bind(("127.0.0.1", 0))
            http_port = int(http_socket.getsockname()[1])
            grpc_port = http_port + 1000
            if grpc_port > 65535:
                continue
            with socket.socket() as grpc_socket:
                try:
                    grpc_socket.bind(("127.0.0.1", grpc_port))
                except OSError:
                    continue
                return http_port, grpc_port
    raise AssertionError("could not reserve an available Nacos loopback port pair")


def _wait_for_nacos(endpoint: str) -> None:
    """Wait until the Nacos Admin route validates requests instead of 404ing."""
    deadline = time.monotonic() + 60
    last_error: OSError | None = None
    probe_url = f"{endpoint}/v3/admin/cs/config"
    while time.monotonic() < deadline:
        try:
            with urlopen(probe_url, timeout=1) as response:
                if response.status == 400:
                    return
        except HTTPError as error:
            if error.code == 400:
                return
            if error.code != 404:
                last_error = error
        except OSError as error:
            last_error = error
        time.sleep(0.25)
    raise AssertionError(f"disposable Nacos Admin API did not become ready: {last_error!r}")


def _nacos_admin_request(
    endpoint: str, method: str, parameters: dict[str, str]
) -> dict[str, object]:
    """Make one form-encoded request to this test's disposable Nacos Admin API."""
    encoded = urlencode(parameters).encode("utf-8")
    url = f"{endpoint}/v3/admin/cs/config"
    if method != "POST":
        url = f"{url}?{encoded.decode('ascii')}"
    request = Request(
        url,
        data=encoded if method == "POST" else None,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method=method,
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise AssertionError("Nacos Admin API request was not accepted")
    return payload


class _ExternalChangeBeforeCasProvider:
    supported_providers = frozenset({ConfigurationSourceProvider.NACOS})

    def __init__(self, baseline: bytes) -> None:
        self.snapshot = RuleConfigurationSnapshot("baseline-revision", baseline)
        self.write_calls = 0

    async def read_configuration(self, connection, target):
        return self.snapshot

    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        if expected_revision != self.snapshot.revision:
            raise AssertionError("provider write did not use the observed revision")
        self.snapshot = RuleConfigurationSnapshot(
            "external-revision", b"external rules"
        )
        raise RulePublicationProviderConflict


class _UnknownOnceAfterCasProvider:
    supported_providers = frozenset({ConfigurationSourceProvider.NACOS})

    def __init__(self, baseline: bytes) -> None:
        self.snapshot = RuleConfigurationSnapshot("baseline-revision", baseline)
        self.write_calls = 0
        self._lose_reply = True

    async def read_configuration(self, connection, target):
        return self.snapshot

    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        if expected_revision != self.snapshot.revision:
            raise AssertionError("provider write did not use the observed revision")
        self.snapshot = RuleConfigurationSnapshot("promoted-revision", value)
        if self._lose_reply:
            self._lose_reply = False
            raise RulePublicationProviderOutcomeUnknown
        return "promoted-revision"


class _SessionRevokingBindingReader:
    def __init__(self, engine, transaction_state) -> None:
        self._engine = engine
        self._transaction_state = transaction_state

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        if self._transaction_state["active"]:
            raise AssertionError("binding authority called inside SQL transaction")
        async with self._engine.begin() as connection:
            await connection.execute(
                update(AuthenticationSessionRecord)
                .where(
                    AuthenticationSessionRecord.session_hash == _digest(_ADMIN_COOKIE)
                )
                .values(revoked_at=_NOW)
            )
        return await _TestBindingReader().read_rule_binding(binding_id)


if __name__ == "__main__":
    unittest.main()
