"""Real Consul provider acceptance for activation-plan lost-association recovery."""

from __future__ import annotations

import asyncio
import multiprocessing
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import quote
from uuid import uuid4

from consul_acl_test_support import DisposableConsulAclServer
from rule_publication_consul_database_acceptance import (
    _FINGERPRINT_KEY,
    _PROFILE,
    _AcceptanceBindingReader,
    _AcceptanceConsulCredentialResolver,
    _AcceptancePublicationTargetReader,
    _candidate,
    _cleanup_activation_rows,
    _digest,
    _seed_identity,
    _seed_version,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from atlas_richie.sentinel_console.application.mutate_rule_set import (
    CreateRuleActivationPlan,
    RuleMutationCommand,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.application.read_rule_activation_plans import (
    ReadRuleActivationPlans,
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
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AuditEventRecord,
    RuleActivationPlanRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
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
    create_consul_rule_publication_worker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_version_reader import (
    SqlAlchemyRuleVersionReader,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)


class _PauseAfterEnqueue:
    """Hold the production scheduler immediately before plan association."""

    def __init__(self, store, result_connection, release_gate) -> None:
        self._store = store
        self._result_connection = result_connection
        self._release_gate = release_gate

    async def enqueue_scheduled_publication(self, claim, *, now):
        result = await self._store.enqueue_scheduled_publication(claim, now=now)
        if result.publication_id is None:
            raise AssertionError("scheduled publication has no identity")
        self._result_connection.send(
            {
                "status": "publication_enqueued",
                "publication_id": result.publication_id,
            }
        )
        if not await asyncio.to_thread(self._release_gate.wait, 120):
            raise TimeoutError("scheduler association gate timed out")
        return result


def _run_scheduler_until_association_boundary(
    database_url: str,
    binding_id: str,
    key: str,
    plan_time_iso: str,
    result_connection,
    release_gate,
) -> None:
    async def run() -> None:
        engine = create_async_engine(database_url, pool_size=1)
        try:
            store = SqlAlchemyRuleMutationStore(
                engine,
                fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
                active_fingerprint_key_id="acceptance",
                binding_reader=_AcceptanceBindingReader(),
                publication_target_reader=_AcceptancePublicationTargetReader(key),
                publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
            )
            worker = RunRuleActivationPlanWorker(
                work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
                publication_enqueuer=_PauseAfterEnqueue(
                    store, result_connection, release_gate
                ),
                clock=lambda: datetime.fromisoformat(plan_time_iso),
            )
            await worker.run_once()
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except BaseException as error:
        try:
            result_connection.send(
                {"status": "error", "error_type": type(error).__name__}
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    finally:
        result_connection.close()


async def assert_real_consul_publication_completes_before_plan_association(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Prove real Consul outbox completion is recoverable before plan linking."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    test_id = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"consul-plan-link-{test_id}"
    baseline_version_id = f"consul-plan-link-baseline-{test_id}"
    activation_version_id = f"consul-plan-link-activation-{test_id}"
    baseline_validation_id = f"consul-plan-link-baseline-validation-{test_id}"
    activation_validation_id = f"consul-plan-link-activation-validation-{test_id}"
    plan_request_key = f"consul-plan-link-create-{test_id}"
    session_digest = _digest(f"consul-plan-link-session-{test_id}")
    csrf_digest = _digest(f"consul-plan-link-csrf-{test_id}")
    username = f"consul-plan-link-{test_id}"
    key = f"sentinel/acceptance/{test_id}/plan-link.json"
    now = datetime.now(UTC).replace(microsecond=0)
    scheduled_at = now - timedelta(seconds=1)
    deactivation_at = now + timedelta(minutes=10)
    scheduler_lease_expires_at = now + timedelta(seconds=60)
    plan_id: str | None = None
    rows_seeded = False
    consul_server: DisposableConsulAclServer | None = None
    parent_connection = None
    child_connection = None
    scheduler_process = None
    release_gate = None

    try:
        await _seed_identity(
            engine,
            account_id=account_id,
            username=username,
            username_key=_digest(username),
            session_digest=session_digest,
            csrf_digest=csrf_digest,
        )
        rows_seeded = True

        baseline_candidate = _candidate(binding_id, count=5)
        activation_candidate = _candidate(binding_id, count=17)
        baseline_checksum = candidate_checksum(baseline_candidate)
        activation_checksum = candidate_checksum(activation_candidate)
        await _seed_version(
            engine,
            account_id=account_id,
            binding_id=binding_id,
            version_id=baseline_version_id,
            validation_id=baseline_validation_id,
            candidate=baseline_candidate,
            checksum=baseline_checksum,
        )
        await _seed_version(
            engine,
            account_id=account_id,
            binding_id=binding_id,
            version_id=activation_version_id,
            validation_id=activation_validation_id,
            candidate=activation_candidate,
            checksum=activation_checksum,
        )

        consul_server = DisposableConsulAclServer(key)
        await consul_server.start()
        target_reader = _AcceptancePublicationTargetReader(key)
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_AcceptanceBindingReader(),
            publication_target_reader=target_reader,
            publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
        )
        created = await store.mutate(
            RuleMutationCommand(
                binding_id,
                plan_request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    scheduled_at,
                    deactivation_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-plan-link-create-{test_id}",
            now=now,
        )
        assert created.status is RuleOperationStatus.COMPLETED
        plan_id = created.result.id

        credential_resolver = _AcceptanceConsulCredentialResolver(
            consul_server.endpoint, consul_server.application_token
        )
        source_connection = await credential_resolver.resolve_credentials(
            "acceptance-source",
            "source-revision-1",
            ConfigurationSourceProvider.CONSUL,
        )
        reader = ConsulRuleSourceReader(
            consul_server.registered_target_policy(), consul_server.http_client()
        )
        baseline_version = await ReadRuleVersion(
            SqlAlchemyRuleVersionReader(engine)
        ).execute(binding_id, baseline_version_id)
        activation_version = await ReadRuleVersion(
            SqlAlchemyRuleVersionReader(engine)
        ).execute(binding_id, activation_version_id)
        encoder = SentinelRuleVersionJsonEncoder(_PROFILE)
        baseline_bytes = encoder.encode_rule_version(baseline_version)
        activation_bytes = encoder.encode_rule_version(activation_version)
        consul_server.write_management_value(key, baseline_bytes)
        baseline_snapshot = await reader.read(source_connection, key)
        assert baseline_snapshot.value == baseline_bytes

        process_context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = process_context.Pipe(duplex=False)
        release_gate = process_context.Event()
        scheduler_process = process_context.Process(
            target=_run_scheduler_until_association_boundary,
            args=(
                database_url,
                binding_id,
                key,
                now.isoformat(),
                child_connection,
                release_gate,
            ),
            name=f"sentinel-plan-link-scheduler-{test_id[:8]}",
        )
        scheduler_process.start()
        child_connection.close()
        child_connection = None
        if not await asyncio.to_thread(parent_connection.poll, 45):
            raise AssertionError("scheduler did not reach the enqueue boundary")
        scheduler_message = parent_connection.recv()
        assert scheduler_message.get("status") == "publication_enqueued", (
            scheduler_message
        )
        publication_id = scheduler_message["publication_id"]

        async with engine.connect() as connection:
            plan_publication_id = await connection.scalar(
                select(RuleActivationPlanRecord.activation_publication_id).where(
                    RuleActivationPlanRecord.plan_id == plan_id
                )
            )
            publication_state = await connection.execute(
                select(
                    RulePublicationRecord.write_state,
                    RulePublicationRecord.read_back_state,
                ).where(RulePublicationRecord.publication_id == publication_id)
            )
        assert plan_publication_id is None
        assert publication_state.one() == ("awaiting", "awaiting")

        policy = consul_server.registered_target_policy()
        publication_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: now + timedelta(seconds=2),
        )
        provider_write_attempts = 0
        original_write = ConsulRuleSourceWriter.write

        async def count_provider_write(writer, command):
            nonlocal provider_write_attempts
            provider_write_attempts += 1
            return await original_write(writer, command)

        with patch.object(ConsulRuleSourceWriter, "write", new=count_provider_write):
            assert await publication_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
            assert await publication_worker.run_once() == ()
        assert provider_write_attempts == 1
        activation_snapshot = await reader.read(source_connection, key)
        assert activation_snapshot.value == activation_bytes
        assert activation_snapshot.modify_index != baseline_snapshot.modify_index

        publication_before_recovery = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, publication_id)
        assert (
            publication_before_recovery.configuration_write.state.value == "succeeded"
        )
        assert publication_before_recovery.read_back.state.value == "succeeded"
        plan_before_recovery = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert plan_before_recovery.items[0].state.value == "activating"
        assert plan_before_recovery.items[0].activation_publication_id is None

        scheduler_process.terminate()
        await asyncio.to_thread(scheduler_process.join, 10)
        assert not scheduler_process.is_alive()
        assert (
            scheduler_process.exitcode is not None and scheduler_process.exitcode != 0
        )

        plan_queue = SqlAlchemyRuleActivationPlanWorkQueue(engine)
        recovery_scheduler = RunRuleActivationPlanWorker(
            work_queue=plan_queue,
            publication_enqueuer=store,
            clock=lambda: scheduler_lease_expires_at + timedelta(seconds=1),
        )
        assert await recovery_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.COMPLETED,
        )
        assert await recovery_scheduler.run_once() == ()
        recovered_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert recovered_plan.items[0].state.value == "active"
        assert recovered_plan.items[0].activation_publication_id == publication_id
        assert provider_write_attempts == 1
        assert (await reader.read(source_connection, key)).modify_index == (
            activation_snapshot.modify_index
        )

        async with engine.connect() as connection:
            operation_count = await connection.scalar(
                select(func.count())
                .select_from(RuleMutationOperationRecord)
                .where(
                    RuleMutationOperationRecord.origin_plan_id == plan_id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            publication_count = await connection.scalar(
                select(func.count())
                .select_from(RulePublicationRecord)
                .where(
                    RulePublicationRecord.publication_id == publication_id,
                )
            )
            accepted_audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == plan_id,
                    AuditEventRecord.outcome == "accepted",
                )
            )
            completed_audit_count = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == plan_id,
                    AuditEventRecord.outcome == "completed",
                )
            )
        assert operation_count == 1
        assert publication_count == 1
        assert accepted_audit_count == 1
        assert completed_audit_count == 1

        cas_write_requests = [
            path
            for path, token in consul_server.observed_requests
            if token == consul_server.application_token
            and path.startswith(f"/v1/kv/{quote(key, safe='/')}?")
            and "cas=" in path
        ]
        assert len(cas_write_requests) == 1
    finally:
        if scheduler_process is not None and scheduler_process.is_alive():
            scheduler_process.terminate()
            await asyncio.to_thread(scheduler_process.join, 10)
        if child_connection is not None:
            child_connection.close()
        if parent_connection is not None:
            parent_connection.close()
        try:
            if rows_seeded:
                await _cleanup_activation_rows(
                    engine,
                    account_id=account_id,
                    session_digest=session_digest,
                    binding_id=binding_id,
                    plan_request_keys=(plan_request_key,),
                    version_ids=(baseline_version_id, activation_version_id),
                    validation_ids=(
                        baseline_validation_id,
                        activation_validation_id,
                    ),
                )
        finally:
            if consul_server is not None:
                await consul_server.close()
