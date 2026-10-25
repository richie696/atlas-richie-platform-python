"""Opt-in PostgreSQL/MySQL outbox to disposable Nacos create-only acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta
from multiprocessing.queues import Queue as ProcessQueue
from multiprocessing.synchronize import Event as ProcessEvent
from typing import NoReturn
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import aiohttp
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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
    CreateRuleActivationPlan,
    RuleMutationCommand,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.application.read_rule_publication import (
    ReadRulePublication,
)
from atlas_richie.sentinel_console.application.read_rule_version import ReadRuleVersion
from atlas_richie.sentinel_console.application.run_rule_activation_plan_worker import (
    RuleActivationPlanWorkerOutcome,
    RunRuleActivationPlanWorker,
)
from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RulePublicationWorkerOutcome,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcOutcomeUnknown,
    NacosGrpcTransport,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_publication_provider import (
    NacosRulePublicationProvider,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    _NACOS_GRPC_PORT_OFFSET,
    NacosRuleSourceConflict,
    NacosRuleSourceWrite,
    NacosRuleSourceWriter,
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
    RuleActivationPlanRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_reader import (
    SqlAlchemyRuleActivationPlanReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_work_queue import (
    SqlAlchemyRuleActivationPlanWorkQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_store import (
    SqlAlchemyRuleMutationStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_reader import (
    SqlAlchemyRulePublicationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_worker_composition import (
    create_nacos_rule_publication_worker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_version_reader import (
    SqlAlchemyRuleVersionReader,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    PinnedSourceTarget,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_IMAGE = "nacos/nacos-server:v3.2.4"
_PROFILE = "sentinel-profile-v1"
_GROUP = "SENTINEL_ACCEPTANCE"
_NOW = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
_SYNTHETIC_NACOS_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI="
_FINGERPRINT_KEY = b"synthetic-nacos-sql-acceptance-key-000000000001"
_CONTAINER_OWNER_LABEL = "com.atlas-richie.sentinel-acceptance.run"


async def assert_sql_outbox_publishes_create_only_to_disposable_nacos(
    engine: AsyncEngine,
) -> None:
    """Accept SQL outbox recovery and a scheduled real-Nacos lifecycle."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"binding-{token}"
    version_id = f"version-{token}"
    validation_id = f"validation-{token}"
    promotion_version_id = f"promotion-{token}"
    promotion_validation_id = f"promotion-validation-{token}"
    request_key = f"request-{token}"
    plan_request_key = f"plan-request-{token}"
    conflict_plan_request_key = f"conflict-plan-request-{token}"
    activation_race_plan_request_key = f"activation-race-plan-request-{token}"
    plan_id: str | None = None
    conflict_plan_id: str | None = None
    activation_race_plan_id: str | None = None
    session_token = f"session-{token}"
    csrf_token = f"csrf-{token}"
    session_digest = _digest(session_token)
    csrf_digest = _digest(csrf_token)
    username = f"nacos-acceptance-{token}"
    data_id = f"sentinel-sql-acceptance-{token}.json"
    container_name = f"sentinel-sql-nacos-{token[:12]}"
    http_port, grpc_port = _free_loopback_port_pair()
    endpoint = f"http://127.0.0.1:{http_port}/nacos"
    target = NacosRulePublicationTarget(
        binding_id=binding_id,
        source_id="acceptance-source",
        namespace="public",
        group=_GROUP,
        data_id=data_id,
    )
    container_started = False
    container_id: str | None = None
    sql_seeded = False
    try:
        await upgrade_database(engine)
        candidate = _candidate(binding_id)
        checksum = candidate_checksum(candidate)
        promotion_candidate = _candidate(binding_id, count=31)
        promotion_checksum = candidate_checksum(promotion_candidate)
        await _seed_database(
            engine,
            account_id=account_id,
            username=username,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            binding_id=binding_id,
            version_id=version_id,
            validation_id=validation_id,
            candidate=candidate,
            checksum=checksum,
            promotion_version_id=promotion_version_id,
            promotion_validation_id=promotion_validation_id,
            promotion_candidate=promotion_candidate,
            promotion_checksum=promotion_checksum,
        )
        sql_seeded = True

        container_result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container_name,
                "--label",
                f"{_CONTAINER_OWNER_LABEL}={token}",
                "--env",
                "MODE=standalone",
                "--env",
                "NACOS_AUTH_ENABLE=false",
                "--env",
                "NACOS_AUTH_ADMIN_ENABLE=false",
                "--env",
                "NACOS_AUTH_CONSOLE_ENABLE=false",
                "--env",
                f"NACOS_AUTH_TOKEN={_SYNTHETIC_NACOS_TOKEN}",
                "--env",
                "NACOS_AUTH_IDENTITY_KEY=sentinel-local-test",
                "--env",
                "NACOS_AUTH_IDENTITY_VALUE=sentinel-local-test-only",
                "--publish",
                f"127.0.0.1:{http_port}:8848/tcp",
                "--publish",
                f"127.0.0.1:{grpc_port}:9848/tcp",
                _IMAGE,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        container_id = container_result.stdout.strip()
        if len(container_id) != 64 or any(
            character not in "0123456789abcdef" for character in container_id
        ):
            raise AssertionError("Docker did not return a valid Nacos container ID")
        container_started = True
        _wait_for_nacos(endpoint)

        policy = _nacos_target_policy(http_port, grpc_port)
        credential_resolver = _NacosCredentialResolver(endpoint)
        target_reader = _NacosTargetReader(target)
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_BindingReader(),
            publication_target_reader=target_reader,
            publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
        )
        app = build_app(
            bootstrap_initialization_reader=_NacosAcceptanceInitialized(),
            setup_window_reader=_NacosAcceptanceSetupWindow(),
            bootstrap_operator_verifier=_NacosAcceptanceOperatorVerifier(),
            current_session_reader=SqlAlchemyCurrentSessionReader(engine),
            current_session_revoker=SqlAlchemyCurrentSessionRevoker(engine),
            account_directory_reader=SqlAlchemyAccountDirectoryReader(engine),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_mutation_authority=store,
        )
        command_url = f"/api/v1/rulesets/{binding_id}/commands"
        command_payload = {
            "requestKey": request_key,
            "mutation": {
                "kind": "publish",
                "versionId": version_id,
                "versionChecksum": checksum,
                "expectedVersionId": None,
                "expectedChecksum": "missing",
                "expectedSourceRevision": "source-revision-1",
                "reason": "synthetic Nacos SQL create-only acceptance reason",
            },
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            client.cookies.set("sentinel_session", session_token)
            client.cookies.set("__Host-sentinel_csrf", csrf_token)
            invalid_origin = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://attacker.invalid",
                    "x-request-id": f"nacos-invalid-origin-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert invalid_origin.status_code == 403
            invalid_csrf = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"nacos-invalid-csrf-{token}",
                    "x-sentinel-csrf": f"wrong-{csrf_token}",
                    "idempotency-key": request_key,
                },
            )
            assert invalid_csrf.status_code == 403
            mismatched_key = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"nacos-mismatched-key-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": f"mismatch-{request_key}",
                },
            )
            assert mismatched_key.status_code == 409
            async with engine.connect() as sql_connection:
                assert (
                    await sql_connection.scalar(
                        select(func.count())
                        .select_from(RuleMutationOperationRecord)
                        .where(RuleMutationOperationRecord.request_key == request_key)
                    )
                    == 0
                )
            accepted = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"nacos-publish-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["status"] == RuleOperationStatus.PENDING.value
            assert accepted.json()["requestKey"] == request_key
            assert (
                "synthetic Nacos SQL create-only acceptance reason" not in accepted.text
            )
            retry = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"nacos-publish-retry-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert retry.status_code == 202
            assert retry.json() == accepted.json()
            pending_receipt = await client.get(
                f"/api/v1/rulesets/{binding_id}/operations/{request_key}",
                headers={"x-request-id": f"nacos-pending-read-{token}"},
            )
            assert pending_receipt.status_code == 200
            assert pending_receipt.json()["status"] == RuleOperationStatus.PENDING.value

        # Nacos applies the real write, but the client loses the response.
        # The worker must persist an unknown outcome and reconcile by reading
        # the exact candidate after its lease expires, never replaying the CAS.
        first_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW,
        )
        original_request_raw = PinnedAioHttpJsonClient.request_raw
        lost_import_responses = 0

        async def apply_import_then_drop_client_ack(
            client: PinnedAioHttpJsonClient,
            *,
            target: PinnedSourceTarget,
            endpoint: str,
            method: str,
            path: str,
            params: dict[str, str],
            headers: dict[str, str],
            form: dict[str, str] | aiohttp.FormData | None = None,
            body: bytes | None = None,
        ) -> tuple[int, bytes, dict[str, str]]:
            nonlocal lost_import_responses
            response = await original_request_raw(
                client,
                target=target,
                endpoint=endpoint,
                method=method,
                path=path,
                params=params,
                headers=headers,
                form=form,
                body=body,
            )
            if method == "POST" and path == "/v3/admin/cs/config/import":
                # Nacos committed the real import, but the transport adapter
                # drops its response before the provider can observe it.
                lost_import_responses += 1
                raise ConnectionResetError("synthetic lost Nacos import response")
            return response

        with patch.object(
            PinnedAioHttpJsonClient,
            "request_raw",
            new=apply_import_then_drop_client_ack,
        ):
            assert await first_worker.run_once() == (
                RulePublicationWorkerOutcome.UNKNOWN,
            )
        assert lost_import_responses == 1

        reader = NacosRuleSourceReader(policy)
        connection = await credential_resolver.resolve_credentials(
            "acceptance-source",
            "source-revision-1",
            ConfigurationSourceProvider.NACOS,
        )
        stored_after_lost_receipt = await reader.read(connection, target)
        version = await ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)).execute(
            binding_id, version_id
        )
        expected = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(version)
        assert stored_after_lost_receipt.value == expected

        pending_operation = await store.read_operation(
            binding_id,
            request_key,
            actor_id=account_id,
            session_digest=session_digest,
        )
        assert pending_operation.status is RuleOperationStatus.PENDING
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            client.cookies.set("sentinel_session", session_token)
            pending_receipt = await client.get(
                f"/api/v1/rulesets/{binding_id}/operations/{request_key}",
                headers={"x-request-id": f"nacos-reconciled-pending-{token}"},
            )
        assert pending_receipt.status_code == 200
        assert pending_receipt.json()["status"] == RuleOperationStatus.PENDING.value
        async with engine.connect() as sql_connection:
            publication_id = await sql_connection.scalar(
                select(RulePublicationRecord.publication_id).where(
                    RulePublicationRecord.binding_id == binding_id
                )
            )
        assert isinstance(publication_id, str)
        publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, publication_id)
        assert publication.configuration_write.state.value == "unknown"

        # Advancing the authoritative clock lets a new worker reclaim the
        # persisted outbox row and reconcile the lost response from Nacos.
        recovered_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=61),
        )
        recovery_write_attempts = 0
        original_request_raw = PinnedAioHttpJsonClient.request_raw

        async def count_recovery_import_attempts(
            client: PinnedAioHttpJsonClient,
            *,
            target: PinnedSourceTarget,
            endpoint: str,
            method: str,
            path: str,
            params: dict[str, str],
            headers: dict[str, str],
            form: dict[str, str] | aiohttp.FormData | None = None,
            body: bytes | None = None,
        ) -> tuple[int, bytes, dict[str, str]]:
            nonlocal recovery_write_attempts
            if method == "POST" and path == "/v3/admin/cs/config/import":
                recovery_write_attempts += 1
            return await original_request_raw(
                client,
                target=target,
                endpoint=endpoint,
                method=method,
                path=path,
                params=params,
                headers=headers,
                form=form,
                body=body,
            )

        with patch.object(
            PinnedAioHttpJsonClient,
            "request_raw",
            new=count_recovery_import_attempts,
        ):
            recovery_outcomes = await recovered_worker.run_once()
        assert recovery_outcomes == (RulePublicationWorkerOutcome.COMPLETED,)
        assert recovery_write_attempts == 0

        stored = await reader.read(connection, target)
        assert stored.value == expected

        completed = await store.read_operation(
            binding_id,
            request_key,
            actor_id=account_id,
            session_digest=session_digest,
        )
        assert completed.status is RuleOperationStatus.COMPLETED
        assert completed.result.read_back.state.value == "succeeded"
        assert "synthetic Nacos SQL create-only acceptance reason" not in repr(
            completed
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            client.cookies.set("sentinel_session", session_token)
            completed_receipt = await client.get(
                f"/api/v1/rulesets/{binding_id}/operations/{request_key}",
                headers={"x-request-id": f"nacos-completed-read-{token}"},
            )
        assert completed_receipt.status_code == 200
        assert completed_receipt.json()["status"] == RuleOperationStatus.COMPLETED.value
        assert completed_receipt.json()["requestKey"] == request_key
        assert completed_receipt.json()["result"]["kind"] == "publish"
        assert (
            "synthetic Nacos SQL create-only acceptance reason"
            not in completed_receipt.text
        )
        assert await recovered_worker.run_once() == ()

        # Drive the production scheduled-plan worker and provider worker through
        # activation and explicit restoration against the same durable SQL and
        # real Nacos target. The plan remains in-flight until its phase lease is
        # reclaimed after the provider's exact read-back has completed.
        created_plan = await store.mutate(
            RuleMutationCommand(
                binding_id,
                plan_request_key,
                CreateRuleActivationPlan(
                    promotion_version_id,
                    version_id,
                    _NOW + timedelta(seconds=62),
                    _NOW + timedelta(seconds=200),
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"plan-http-{token}",
            now=_NOW + timedelta(seconds=61),
        )
        assert created_plan.status is RuleOperationStatus.COMPLETED
        plan_id = created_plan.result.id

        activation_scheduler = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=63),
        )
        assert await activation_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        promotion_version = await ReadRuleVersion(
            SqlAlchemyRuleVersionReader(engine)
        ).execute(binding_id, promotion_version_id)
        expected_promotion = SentinelRuleVersionJsonEncoder(
            _PROFILE
        ).encode_rule_version(promotion_version)
        plan_reader = SqlAlchemyRuleActivationPlanReader(engine)
        activating = await plan_reader.read_rule_activation_plans(binding_id)
        assert activating.items[0].id == plan_id
        assert activating.items[0].state.value == "activating"
        activation_publication_id = activating.items[0].activation_publication_id
        assert isinstance(activation_publication_id, str)

        # Nacos applies the real activation CAS, but the transport response is
        # discarded before NacosRuleSourceWriter can observe its success.
        activation_ack_losses = 0
        original_activation_grpc_request = NacosGrpcTransport.request

        async def apply_activation_then_drop_grpc_ack(
            transport: NacosGrpcTransport,
            pinned_target: PinnedSourceTarget,
            *,
            request_type: str,
            body: dict[str, object],
            headers: dict[str, str],
        ) -> tuple[str, dict[str, object]]:
            nonlocal activation_ack_losses
            response = await original_activation_grpc_request(
                transport,
                pinned_target,
                request_type=request_type,
                body=body,
                headers=headers,
            )
            if request_type == "ConfigPublishRequest":
                activation_ack_losses += 1
                raise NacosGrpcOutcomeUnknown
            return response

        activation_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=64),
        )
        with patch.object(
            NacosGrpcTransport,
            "request",
            new=apply_activation_then_drop_grpc_ack,
        ):
            activation_outcomes = await activation_worker.run_once()
            activation_publication = await ReadRulePublication(
                SqlAlchemyRulePublicationReader(engine)
            ).execute(binding_id, activation_publication_id)
            assert activation_outcomes == (RulePublicationWorkerOutcome.UNKNOWN,), (
                f"activation outcomes={activation_outcomes!r}, "
                f"ack_losses={activation_ack_losses}, "
                "phases="
                f"{tuple((phase.state.value, phase.reason.value if phase.reason else None) for phase in (activation_publication.validation, activation_publication.configuration_write, activation_publication.read_back))!r}"
            )
        assert activation_ack_losses == 1
        activated_source = await reader.read(connection, target)
        assert activated_source.value == expected_promotion
        interrupted_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, activation_publication_id)
        assert interrupted_publication.configuration_write.state.value == "unknown"
        assert interrupted_publication.read_back.state.value == "awaiting"

        # The plan lease is reclaimed first and must reuse its existing
        # publication. A new publisher reconciles by exact read-back; a second
        # call to the Nacos CAS would be a safety regression.
        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=124),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        activation_recovery_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=125),
        )
        activation_recovery_write_attempts = 0
        original_write = NacosRulePublicationProvider.write_configuration_if_revision

        async def count_activation_recovery_writes(
            provider: NacosRulePublicationProvider,
            provider_connection: SourceConnectionInput,
            provider_target: NacosRulePublicationTarget,
            *,
            expected_revision: str | None,
            value: bytes,
        ) -> str:
            nonlocal activation_recovery_write_attempts
            activation_recovery_write_attempts += 1
            return await original_write(
                provider,
                provider_connection,
                provider_target,
                expected_revision=expected_revision,
                value=value,
            )

        with patch.object(
            NacosRulePublicationProvider,
            "write_configuration_if_revision",
            new=count_activation_recovery_writes,
        ):
            assert await activation_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert activation_recovery_write_attempts == 0
        recovered_source = await reader.read(connection, target)
        assert recovered_source.value == expected_promotion
        assert (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ].state.value == "activating"

        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=185),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        active = await plan_reader.read_rule_activation_plans(binding_id)
        assert active.items[0].state.value == "active"
        assert active.items[0].activation_publication_id == activation_publication_id

        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=201),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        restoration_publication_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=202),
        )
        restoration_write_attempts = 0
        original_restoration_write = (
            NacosRulePublicationProvider.write_configuration_if_revision
        )
        original_grpc_request = NacosGrpcTransport.request

        async def apply_restore_then_drop_grpc_ack(
            transport: NacosGrpcTransport,
            target: PinnedSourceTarget,
            *,
            request_type: str,
            body: dict[str, object],
            headers: dict[str, str],
        ) -> tuple[str, dict[str, object]]:
            nonlocal restoration_write_attempts
            response = await original_grpc_request(
                transport,
                target,
                request_type=request_type,
                body=body,
                headers=headers,
            )
            if request_type == "ConfigPublishRequest":
                # Nacos has committed the real CAS; discard the successful
                # transport response before NacosRuleSourceWriter observes it.
                restoration_write_attempts += 1
                raise NacosGrpcOutcomeUnknown
            return response

        with patch.object(
            NacosGrpcTransport,
            "request",
            new=apply_restore_then_drop_grpc_ack,
        ):
            assert await restoration_publication_worker.run_once() == (
                RulePublicationWorkerOutcome.UNKNOWN,
            )
        assert restoration_write_attempts == 1
        restored_source = await reader.read(connection, target)
        assert restored_source.value == expected
        restoring = await plan_reader.read_rule_activation_plans(binding_id)
        assert restoring.items[0].state.value == "restoring"
        restoration_publication_id = restoring.items[0].restore_publication_id
        assert isinstance(restoration_publication_id, str)
        assert restoration_publication_id != activation_publication_id

        restoration_recovery_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=263),
        )
        restoration_recovery_write_attempts = 0

        async def count_restoration_recovery_writes(
            provider: NacosRulePublicationProvider,
            provider_connection: SourceConnectionInput,
            provider_target: NacosRulePublicationTarget,
            *,
            expected_revision: str | None,
            value: bytes,
        ) -> str:
            nonlocal restoration_recovery_write_attempts
            restoration_recovery_write_attempts += 1
            return await original_restoration_write(
                provider,
                provider_connection,
                provider_target,
                expected_revision=expected_revision,
                value=value,
            )

        with patch.object(
            NacosRulePublicationProvider,
            "write_configuration_if_revision",
            new=count_restoration_recovery_writes,
        ):
            assert await restoration_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert restoration_recovery_write_attempts == 0
        assert await reader.read(connection, target) == restored_source

        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=324),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        finished = await plan_reader.read_rule_activation_plans(binding_id)
        assert finished.items[0].state.value == "completed"
        assert finished.items[0].restore_publication_id == restoration_publication_id
        assert await activation_scheduler.run_once() == ()
        assert await activation_recovery_worker.run_once() == ()
        assert await restoration_publication_worker.run_once() == ()
        assert await restoration_recovery_worker.run_once() == ()

        # A second scheduled cycle injects an external Nacos writer exactly
        # after the restoration worker's preflight read but before its CAS.
        conflict_plan_result = await store.mutate(
            RuleMutationCommand(
                binding_id,
                conflict_plan_request_key,
                CreateRuleActivationPlan(
                    promotion_version_id,
                    version_id,
                    _NOW + timedelta(seconds=361),
                    _NOW + timedelta(seconds=430),
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"conflict-plan-http-{token}",
            now=_NOW + timedelta(seconds=350),
        )
        assert conflict_plan_result.status is RuleOperationStatus.COMPLETED
        conflict_plan_id = conflict_plan_result.result.id
        conflict_plan_scheduler = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=362),
        )
        assert await conflict_plan_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        # Preserve the scheduled provider-side-effect process-exit case on a
        # second plan while the first plan above covers lost gRPC ack recovery.
        _run_worker_process_that_exits_after_provider_write(
            engine.url.render_as_string(hide_password=False),
            endpoint,
            http_port,
            grpc_port,
            _NOW + timedelta(seconds=363),
        )
        conflict_activation_source = await reader.read(connection, target)
        assert conflict_activation_source.value == expected_promotion
        conflict_activating = await plan_reader.read_rule_activation_plans(binding_id)
        conflict_activating_plan = next(
            item for item in conflict_activating.items if item.id == conflict_plan_id
        )
        assert conflict_activating_plan.state.value == "activating"
        conflict_activation_publication_id = (
            conflict_activating_plan.activation_publication_id
        )
        assert isinstance(conflict_activation_publication_id, str)
        conflict_interrupted_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, conflict_activation_publication_id)
        assert (
            conflict_interrupted_publication.configuration_write.state.value
            == "running"
        )
        assert conflict_interrupted_publication.read_back.state.value == "awaiting"
        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=423),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        conflict_activation_recovery_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=424),
        )
        conflict_activation_recovery_writes = 0
        original_recovery_provider_write = (
            NacosRulePublicationProvider.write_configuration_if_revision
        )

        async def count_conflict_activation_recovery_writes(
            provider: NacosRulePublicationProvider,
            provider_connection: SourceConnectionInput,
            provider_target: NacosRulePublicationTarget,
            *,
            expected_revision: str | None,
            value: bytes,
        ) -> str:
            nonlocal conflict_activation_recovery_writes
            conflict_activation_recovery_writes += 1
            return await original_recovery_provider_write(
                provider,
                provider_connection,
                provider_target,
                expected_revision=expected_revision,
                value=value,
            )

        with patch.object(
            NacosRulePublicationProvider,
            "write_configuration_if_revision",
            new=count_conflict_activation_recovery_writes,
        ):
            assert await conflict_activation_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert conflict_activation_recovery_writes == 0
        assert (await reader.read(connection, target)).value == expected_promotion
        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=485),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        conflict_restore_scheduler = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=491),
        )
        assert await conflict_restore_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )

        conflict_restore_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=492),
        )
        conflict_restore_write_attempts = 0
        external_payload = json.loads(expected_promotion)
        assert isinstance(external_payload, list) and external_payload
        assert isinstance(external_payload[0], dict)
        external_payload[0]["count"] += 1
        external_value = json.dumps(
            external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        assert external_value != expected_promotion
        external_writer = NacosRuleSourceWriter(policy, reader)
        original_conflict_write = (
            NacosRulePublicationProvider.write_configuration_if_revision
        )

        async def race_external_write_before_restore_cas(
            provider: NacosRulePublicationProvider,
            provider_connection: SourceConnectionInput,
            provider_target: NacosRulePublicationTarget,
            *,
            expected_revision: str | None,
            value: bytes,
        ) -> str:
            nonlocal conflict_restore_write_attempts
            conflict_restore_write_attempts += 1
            assert expected_revision is not None
            await external_writer.write(
                NacosRuleSourceWrite(
                    connection=provider_connection,
                    target=provider_target,
                    expected_md5=expected_revision,
                    value=external_value,
                )
            )
            return await original_conflict_write(
                provider,
                provider_connection,
                provider_target,
                expected_revision=expected_revision,
                value=value,
            )

        with patch.object(
            NacosRulePublicationProvider,
            "write_configuration_if_revision",
            new=race_external_write_before_restore_cas,
        ):
            assert await conflict_restore_worker.run_once() == (
                RulePublicationWorkerOutcome.REJECTED,
            )
        assert conflict_restore_write_attempts == 1
        external_snapshot = await reader.read(connection, target)
        assert external_snapshot.value == external_value
        assert await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=552),
        ).run_once() == (RuleActivationPlanWorkerOutcome.BLOCKED,)
        blocked_plans = await plan_reader.read_rule_activation_plans(binding_id)
        blocked_plan = next(
            item for item in blocked_plans.items if item.id == conflict_plan_id
        )
        assert blocked_plan.state.value == "blocked"
        conflict_restore_publication_id = blocked_plan.restore_publication_id
        assert isinstance(conflict_restore_publication_id, str)
        blocked_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, conflict_restore_publication_id)
        assert blocked_publication.configuration_write.state.value == "failed"
        assert blocked_publication.configuration_write.reason.value == "conflict"
        assert await conflict_plan_scheduler.run_once() == ()
        assert await reader.read(connection, target) == external_snapshot

        # Reset to an immutable, known baseline before testing the activation
        # side of the same preflight/CAS race with another non-overlapping plan.
        await external_writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=external_snapshot.md5,
                value=expected,
            )
        )
        assert (await reader.read(connection, target)).value == expected
        activation_race_result = await store.mutate(
            RuleMutationCommand(
                binding_id,
                activation_race_plan_request_key,
                CreateRuleActivationPlan(
                    promotion_version_id,
                    version_id,
                    _NOW + timedelta(seconds=621),
                    _NOW + timedelta(seconds=710),
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"activation-race-plan-http-{token}",
            now=_NOW + timedelta(seconds=610),
        )
        assert activation_race_result.status is RuleOperationStatus.COMPLETED
        activation_race_plan_id = activation_race_result.result.id
        activation_race_scheduler = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=622),
        )
        assert await activation_race_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        activation_race_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW + timedelta(seconds=623),
        )
        activation_external_payload = json.loads(expected)
        assert isinstance(activation_external_payload, list)
        assert activation_external_payload and isinstance(
            activation_external_payload[0], dict
        )
        activation_external_payload[0]["count"] += 17
        activation_external_value = json.dumps(
            activation_external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        process_context = multiprocessing.get_context("spawn")
        release_external_writer = process_context.Event()
        external_writer_ready = process_context.Event()
        external_writer_result = process_context.Queue()
        external_writer_process = process_context.Process(
            target=_compete_external_nacos_writer,
            args=(
                endpoint,
                http_port,
                grpc_port,
                binding_id,
                data_id,
                hashlib.md5(expected, usedforsecurity=False).hexdigest(),
                activation_external_value,
                release_external_writer,
                external_writer_ready,
                external_writer_result,
            ),
            name="sentinel-nacos-external-writer-race-acceptance",
        )
        external_writer_process.start()
        if not await asyncio.to_thread(external_writer_ready.wait, 20):
            external_writer_process.terminate()
            await asyncio.to_thread(external_writer_process.join, 5)
            raise AssertionError("external Nacos writer did not become ready")

        async def race_external_write_before_activation_cas(
            provider: NacosRulePublicationProvider,
            provider_connection: SourceConnectionInput,
            provider_target: NacosRulePublicationTarget,
            *,
            expected_revision: str | None,
            value: bytes,
        ) -> str:
            assert expected_revision is not None
            release_external_writer.set()
            return await original_conflict_write(
                provider,
                provider_connection,
                provider_target,
                expected_revision=expected_revision,
                value=value,
            )

        try:
            with patch.object(
                NacosRulePublicationProvider,
                "write_configuration_if_revision",
                new=race_external_write_before_activation_cas,
            ):
                activation_worker_outcomes = await activation_race_worker.run_once()
        finally:
            release_external_writer.set()
            await asyncio.to_thread(external_writer_process.join, 20)
            if external_writer_process.is_alive():
                external_writer_process.terminate()
                await asyncio.to_thread(external_writer_process.join, 5)
                raise AssertionError("external Nacos writer did not finish")
        assert external_writer_process.exitcode == 0
        external_writer_outcome = await asyncio.to_thread(
            external_writer_result.get, True, 5
        )
        external_writer_result.close()
        await asyncio.to_thread(external_writer_result.join_thread)
        assert external_writer_outcome in {"written", "conflict"}
        activation_external_snapshot = await reader.read(connection, target)
        assert activation_external_snapshot.value in {
            activation_external_value,
            expected_promotion,
        }
        worker_won_cas = activation_external_snapshot.value == expected_promotion
        assert worker_won_cas == (
            activation_worker_outcomes == (RulePublicationWorkerOutcome.COMPLETED,)
        )
        assert worker_won_cas == (external_writer_outcome == "conflict")
        activation_plan_outcomes = await RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: _NOW + timedelta(seconds=683),
        ).run_once()
        activation_blocked_plans = await plan_reader.read_rule_activation_plans(
            binding_id
        )
        activation_blocked_plan = next(
            item
            for item in activation_blocked_plans.items
            if item.id == activation_race_plan_id
        )
        if worker_won_cas:
            assert activation_plan_outcomes == (
                RuleActivationPlanWorkerOutcome.COMPLETED,
            )
            assert activation_blocked_plan.state.value == "active"
        else:
            assert activation_plan_outcomes == (
                RuleActivationPlanWorkerOutcome.BLOCKED,
            )
            assert activation_blocked_plan.state.value == "blocked"
        assert activation_blocked_plan.restore_publication_id is None
        activation_publication_id = activation_blocked_plan.activation_publication_id
        assert isinstance(activation_publication_id, str)
        activation_blocked_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, activation_publication_id)
        if worker_won_cas:
            assert (
                activation_blocked_publication.configuration_write.state.value
                == "succeeded"
            )
        else:
            assert (
                activation_blocked_publication.configuration_write.state.value
                == "failed"
            )
            assert (
                activation_blocked_publication.configuration_write.reason.value
                == "conflict"
            )
        assert await activation_race_scheduler.run_once() == ()
        assert await reader.read(connection, target) == activation_external_snapshot

        async with engine.connect() as sql_connection:
            for phase, publication_id in (
                ("activation", activation_publication_id),
                ("restoration", restoration_publication_id),
            ):
                phase_operation_count = await sql_connection.scalar(
                    select(func.count())
                    .select_from(RuleMutationOperationRecord)
                    .where(
                        RuleMutationOperationRecord.origin_plan_id == plan_id,
                        RuleMutationOperationRecord.origin_phase == phase,
                    )
                )
                phase_publication_count = await sql_connection.scalar(
                    select(func.count())
                    .select_from(RulePublicationRecord)
                    .where(RulePublicationRecord.publication_id == publication_id)
                )
                phase_audit_count = await sql_connection.scalar(
                    select(func.count())
                    .select_from(AuditEventRecord)
                    .where(
                        AuditEventRecord.target_id == plan_id,
                        AuditEventRecord.action
                        == (
                            "rules.activation_plan.activate"
                            if phase == "activation"
                            else "rules.activation_plan.restore"
                        ),
                        AuditEventRecord.outcome == "completed",
                    )
                )
                assert phase_operation_count == 1
                assert phase_publication_count == 1
                assert phase_audit_count == 1
            conflict_restore_operation_count = await sql_connection.scalar(
                select(func.count())
                .select_from(RuleMutationOperationRecord)
                .where(
                    RuleMutationOperationRecord.origin_plan_id == conflict_plan_id,
                    RuleMutationOperationRecord.origin_phase == "restoration",
                )
            )
            conflict_restore_publications = await sql_connection.scalar(
                select(func.count())
                .select_from(RulePublicationRecord)
                .where(
                    RulePublicationRecord.publication_id
                    == conflict_restore_publication_id
                )
            )
            assert conflict_restore_operation_count == 1
            assert conflict_restore_publications == 1
            activation_operation_count = await sql_connection.scalar(
                select(func.count())
                .select_from(RuleMutationOperationRecord)
                .where(
                    RuleMutationOperationRecord.origin_plan_id
                    == activation_race_plan_id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            activation_publication_count = await sql_connection.scalar(
                select(func.count())
                .select_from(RulePublicationRecord)
                .where(
                    RulePublicationRecord.publication_id == activation_publication_id
                )
            )
            assert activation_operation_count == 1
            assert activation_publication_count == 1
    finally:
        if container_started:
            try:
                _nacos_admin_request(
                    endpoint,
                    "DELETE",
                    {
                        "namespaceId": "public",
                        "groupName": _GROUP,
                        "dataId": data_id,
                    },
                    allow_failure=True,
                )
            finally:
                await asyncio.to_thread(
                    _remove_owned_container,
                    container_id,
                    token,
                )
        if sql_seeded:
            await _cleanup_database(
                engine,
                account_id=account_id,
                session_digest=session_digest,
                binding_id=binding_id,
                validation_ids=(validation_id, promotion_validation_id),
                version_ids=(version_id, promotion_version_id),
                request_keys=(
                    request_key,
                    plan_request_key,
                    conflict_plan_request_key,
                    activation_race_plan_request_key,
                ),
                plan_ids=tuple(
                    item
                    for item in (plan_id, conflict_plan_id, activation_race_plan_id)
                    if item is not None
                ),
            )


async def _seed_database(
    engine: AsyncEngine,
    *,
    account_id: str,
    username: str,
    session_digest: str,
    csrf_digest: str,
    binding_id: str,
    version_id: str,
    validation_id: str,
    candidate,
    checksum: str,
    promotion_version_id: str,
    promotion_validation_id: str,
    promotion_candidate,
    promotion_checksum: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(AccountRecord).values(
                account_id=account_id,
                username=username,
                username_key=_digest(username),
                password_hash="$argon2id$synthetic-acceptance-hash",
                role_id="admin",
                status="active",
                built_in=False,
                revision=1,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        await connection.execute(
            insert(AuthenticationSessionRecord).values(
                session_hash=session_digest,
                account_id=account_id,
                session_epoch=str(uuid4()),
                csrf_hash=csrf_digest,
                created_at=_NOW,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                revoked_at=None,
            )
        )
        await connection.execute(
            insert(RuleValidationReceiptRecord).values(
                validation_id=validation_id,
                binding_id=binding_id,
                profile=_PROFILE,
                base_checksum=candidate.base_checksum,
                candidate_checksum=checksum,
                is_publishable=True,
                issues=[],
                actor_account_id=account_id,
                request_id=f"validation-request-{validation_id}",
                created_at=_NOW,
            )
        )
        await connection.execute(
            insert(RuleSetVersionRecord).values(
                version_id=version_id,
                binding_id=binding_id,
                kind=candidate.kind.value,
                profile=_PROFILE,
                base_version_id=None,
                checksum=checksum,
                name="SQL to Nacos create-only acceptance",
                note="",
                validation_id=validation_id,
                records=[
                    rule_record_body(
                        RuleRecord("acceptance-record", candidate.rules[0].rule)
                    )
                ],
                created_at=_NOW,
                created_by_account_id=account_id,
            )
        )
        await connection.execute(
            insert(RuleValidationReceiptRecord).values(
                validation_id=promotion_validation_id,
                binding_id=binding_id,
                profile=_PROFILE,
                base_checksum=candidate.base_checksum,
                candidate_checksum=promotion_checksum,
                is_publishable=True,
                issues=[],
                actor_account_id=account_id,
                request_id=f"validation-request-{promotion_validation_id}",
                created_at=_NOW,
            )
        )
        await connection.execute(
            insert(RuleSetVersionRecord).values(
                version_id=promotion_version_id,
                binding_id=binding_id,
                kind=promotion_candidate.kind.value,
                profile=_PROFILE,
                base_version_id=version_id,
                checksum=promotion_checksum,
                name="Scheduled Nacos promotion acceptance",
                note="",
                validation_id=promotion_validation_id,
                records=[
                    rule_record_body(
                        RuleRecord(
                            "acceptance-record",
                            promotion_candidate.rules[0].rule,
                        )
                    )
                ],
                created_at=_NOW,
                created_by_account_id=account_id,
            )
        )


async def _cleanup_database(
    engine: AsyncEngine,
    *,
    account_id: str,
    session_digest: str,
    binding_id: str,
    version_ids: tuple[str, ...],
    validation_ids: tuple[str, ...],
    request_keys: tuple[str, ...],
    plan_ids: tuple[str, ...],
) -> None:
    async with engine.begin() as connection:
        audit_filter = AuditEventRecord.actor_account_id == account_id
        if plan_ids:
            audit_filter = audit_filter | AuditEventRecord.target_id.in_(plan_ids)
        await connection.execute(delete(AuditEventRecord).where(audit_filter))
        await connection.execute(
            delete(RulePublicationRecord).where(
                RulePublicationRecord.binding_id == binding_id
            )
        )
        await connection.execute(
            delete(RuleMutationOperationRecord).where(
                RuleMutationOperationRecord.request_key.in_(request_keys)
            )
        )
        if plan_ids:
            await connection.execute(
                delete(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id.in_(plan_ids)
                )
            )
            await connection.execute(
                delete(RuleActivationPlanRecord).where(
                    RuleActivationPlanRecord.plan_id.in_(plan_ids)
                )
            )
        await connection.execute(
            delete(RuleSetVersionRecord).where(
                RuleSetVersionRecord.version_id.in_(version_ids)
            )
        )
        await connection.execute(
            delete(RuleValidationReceiptRecord).where(
                RuleValidationReceiptRecord.validation_id.in_(validation_ids)
            )
        )
        await connection.execute(
            delete(AuthenticationSessionRecord).where(
                AuthenticationSessionRecord.session_hash == session_digest
            )
        )
        await connection.execute(
            delete(AccountRecord).where(AccountRecord.account_id == account_id)
        )


def _candidate(binding_id: str, *, count: int = 17):
    return parse_rule_candidate(
        {
            "bindingId": binding_id,
            "profile": _PROFILE,
            "kind": "flow",
            "baseVersionId": None,
            "baseChecksum": "sha256:baseline",
            "sourceRevision": None,
            "rules": [
                {
                    "recordId": "acceptance-record",
                    "rule": {
                        "kind": "flow",
                        "value": {
                            "resource": "/acceptance",
                            "limitApp": "default",
                            "grade": 1,
                            "count": count,
                            "strategy": 0,
                            "controlBehavior": 0,
                            "clusterMode": False,
                        },
                    },
                }
            ],
        }
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nacos_target_policy(
    http_port: int, grpc_port: int
) -> RegisteredSourceTargetPolicy:
    return RegisteredSourceTargetPolicy(
        [
            RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.NACOS,
                "127.0.0.1",
                ["127.0.0.1/32"],
                frozenset({http_port, grpc_port}),
            )
        ]
    )


def _run_worker_process_that_exits_after_provider_write(
    database_url: str,
    endpoint: str,
    http_port: int,
    grpc_port: int,
    clock_time: datetime,
) -> None:
    process_context = multiprocessing.get_context("spawn")
    worker_process = process_context.Process(
        target=_crash_worker_after_provider_write,
        args=(database_url, endpoint, http_port, grpc_port, clock_time),
        name="sentinel-nacos-publication-crash-acceptance",
    )
    worker_process.start()
    worker_process.join(timeout=45)
    if worker_process.is_alive():
        worker_process.terminate()
        worker_process.join(timeout=5)
        raise AssertionError("Nacos publication worker did not reach crash point")
    if worker_process.exitcode != 73:
        raise AssertionError(
            "Nacos publication worker did not exit after its successful provider write"
        )


def _crash_worker_after_provider_write(
    database_url: str,
    endpoint: str,
    http_port: int,
    grpc_port: int,
    clock_time: datetime,
) -> None:
    async def run_worker() -> None:
        engine = create_async_engine(database_url, pool_size=2)
        worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=_nacos_target_policy(http_port, grpc_port),
            credential_resolver=_NacosCredentialResolver(endpoint),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: clock_time,
        )
        original_write = NacosRulePublicationProvider.write_configuration_if_revision

        async def exit_after_successful_write(
            provider: NacosRulePublicationProvider,
            provider_connection: SourceConnectionInput,
            provider_target: NacosRulePublicationTarget,
            *,
            expected_revision: str | None,
            value: bytes,
        ) -> NoReturn:
            receipt = await original_write(
                provider,
                provider_connection,
                provider_target,
                expected_revision=expected_revision,
                value=value,
            )
            os._exit(73 if receipt else 74)

        with patch.object(
            NacosRulePublicationProvider,
            "write_configuration_if_revision",
            new=exit_after_successful_write,
        ):
            await worker.run_once()
        await engine.dispose()

    asyncio.run(run_worker())


def _compete_external_nacos_writer(
    endpoint: str,
    http_port: int,
    grpc_port: int,
    binding_id: str,
    data_id: str,
    expected_md5: str,
    value: bytes,
    release_event: ProcessEvent,
    ready_event: ProcessEvent,
    result_queue: ProcessQueue,
) -> None:
    """Race a second OS process against the scheduled Nacos CAS request."""
    ready_event.set()
    if not release_event.wait(timeout=30):
        result_queue.put("timeout")
        return

    async def write_external_configuration() -> str:
        policy = _nacos_target_policy(http_port, grpc_port)
        connection = SourceConnectionInput(
            source_id="acceptance-source",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        target = NacosRulePublicationTarget(
            binding_id=binding_id,
            source_id="acceptance-source",
            namespace="public",
            group=_GROUP,
            data_id=data_id,
        )
        writer = NacosRuleSourceWriter(policy, NacosRuleSourceReader(policy))
        try:
            await writer.write(
                NacosRuleSourceWrite(
                    connection=connection,
                    target=target,
                    expected_md5=expected_md5,
                    value=value,
                )
            )
        except NacosRuleSourceConflict:
            return "conflict"
        return "written"

    result_queue.put(asyncio.run(write_external_configuration()))


def _free_loopback_port_pair() -> tuple[int, int]:
    """Reserve a loopback HTTP/gRPC pair while preserving Nacos's +1000 offset.

    macOS commonly chooses ephemeral ports above 64535, which cannot be used
    as the HTTP base because Nacos derives its gRPC port by adding 1000.
    Fall back to an unprivileged local range in that environment.
    """
    for _ in range(100):
        try:
            with socket.socket() as http_socket, socket.socket() as grpc_socket:
                http_socket.bind(("127.0.0.1", 0))
                http_port = int(http_socket.getsockname()[1])
                grpc_port = http_port + _NACOS_GRPC_PORT_OFFSET
                if grpc_port > 65535:
                    continue
                grpc_socket.bind(("127.0.0.1", grpc_port))
                return http_port, grpc_port
        except OSError:
            continue
    for http_port in range(20_000, 48_000):
        grpc_port = http_port + _NACOS_GRPC_PORT_OFFSET
        try:
            with socket.socket() as http_socket, socket.socket() as grpc_socket:
                http_socket.bind(("127.0.0.1", http_port))
                grpc_socket.bind(("127.0.0.1", grpc_port))
                return http_port, grpc_port
        except OSError:
            continue
    raise AssertionError("could not reserve Nacos HTTP and HTTP+1000 loopback ports")


def _remove_owned_container(container_id: str, run_id: str) -> None:
    """Remove only the exact Nacos container created by this acceptance run."""
    inspection_format = (
        f'{{{{.Id}}}} {{{{ index .Config.Labels "{_CONTAINER_OWNER_LABEL}"' + " }}"
    )
    inspection = subprocess.run(
        ["docker", "container", "inspect", "--format", inspection_format, container_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if inspection.returncode != 0:
        daemon = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if daemon.returncode != 0:
            raise RuntimeError(
                "cannot verify Nacos container cleanup: Docker unavailable"
            )
        return

    expected_inspection = f"{container_id} {run_id}"
    if inspection.stdout.strip() != expected_inspection:
        raise RuntimeError("refusing to remove a Nacos container not owned by this run")

    subprocess.run(
        ["docker", "container", "rm", "--force", container_id],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    remaining = subprocess.run(
        ["docker", "container", "inspect", "--format", inspection_format, container_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if remaining.returncode == 0:
        raise RuntimeError("run-owned Nacos container still exists after cleanup")
    daemon = subprocess.run(
        ["docker", "info"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if daemon.returncode != 0:
        raise RuntimeError("cannot confirm Nacos cleanup: Docker became unavailable")


def _wait_for_nacos(endpoint: str) -> None:
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
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
    raise AssertionError(
        f"disposable Nacos Admin API did not become ready: {last_error!r}"
    )


def _nacos_admin_request(
    endpoint: str,
    method: str,
    parameters: dict[str, str],
    *,
    allow_failure: bool = False,
) -> dict[str, object]:
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
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise AssertionError("Nacos Admin API request was not accepted")
        return payload
    except (HTTPError, OSError, ValueError, AssertionError):
        if allow_failure:
            return {}
        raise


class _NacosAcceptanceInitialized:
    async def is_initialized(self) -> bool:
        return True


class _NacosAcceptanceSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _NacosAcceptanceOperatorVerifier:
    async def is_current_operator(self, _opaque_session: str | None) -> bool:
        return False


class _BindingReader:
    async def read_rule_binding(self, binding_id: str) -> RuleBinding:
        return RuleBinding(
            id=binding_id,
            environment_id="acceptance",
            app_id="acceptance-app",
            kind=RuleKind.FLOW,
            profile=_PROFILE,
            source_id="acceptance-source",
            source_label="Disposable Nacos",
            location="local acceptance target",
        )


class _NacosTargetReader:
    def __init__(self, target: NacosRulePublicationTarget) -> None:
        self._target = target

    async def read_rule_publication_target(self, binding_id: str):
        if binding_id != self._target.binding_id:
            return None
        return VersionedRulePublicationTarget(
            revision="target-revision-1",
            source_revision="source-revision-1",
            target=self._target,
        )


class _NacosCredentialResolver:
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


__all__ = ["assert_sql_outbox_publishes_create_only_to_disposable_nacos"]
