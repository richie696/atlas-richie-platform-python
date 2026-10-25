"""Real Nacos provider acceptance for activation-plan lost-link recovery."""

from __future__ import annotations

import asyncio
import multiprocessing
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from rule_publication_nacos_database_acceptance import (
    _CONTAINER_OWNER_LABEL,
    _FINGERPRINT_KEY,
    _GROUP,
    _IMAGE,
    _PROFILE,
    _SYNTHETIC_NACOS_TOKEN,
    _BindingReader,
    _candidate,
    _cleanup_database,
    _digest,
    _free_loopback_port_pair,
    _nacos_admin_request,
    _nacos_target_policy,
    _NacosCredentialResolver,
    _NacosTargetReader,
    _remove_owned_container,
    _seed_database,
    _wait_for_nacos,
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
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceWrite,
    NacosRuleSourceWriter,
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
    create_nacos_rule_publication_worker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_version_reader import (
    SqlAlchemyRuleVersionReader,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_NOW = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
_CONTAINER_INSPECTION_FORMAT = (
    "{{.Id}} {{index .Config.Labels \""
    f"{_CONTAINER_OWNER_LABEL}"
    "\"}}"
)


class _PauseAfterEnqueue:
    """Hold the scheduler before it can persist the publication link."""

    def __init__(self, store, result_connection, release_gate) -> None:
        self._store = store
        self._result_connection = result_connection
        self._release_gate = release_gate

    async def enqueue_scheduled_publication(self, claim, *, now):
        result = await self._store.enqueue_scheduled_publication(claim, now=now)
        if result.publication_id is None:
            raise AssertionError("scheduled publication has no identity")
        self._result_connection.send(
            {"status": "publication_enqueued", "publication_id": result.publication_id}
        )
        if not await asyncio.to_thread(self._release_gate.wait, 120):
            raise TimeoutError("scheduler association gate timed out")
        return result


def _run_scheduler_until_association_boundary(
    database_url: str,
    binding_id: str,
    data_id: str,
    plan_time_iso: str,
    result_connection,
    release_gate,
) -> None:
    async def run() -> None:
        engine = create_async_engine(database_url, pool_size=1)
        target = NacosRulePublicationTarget(
            binding_id=binding_id,
            source_id="acceptance-source",
            namespace="public",
            group=_GROUP,
            data_id=data_id,
        )
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_BindingReader(),
            publication_target_reader=_NacosTargetReader(target),
            publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=_PauseAfterEnqueue(
                store, result_connection, release_gate
            ),
            clock=lambda: datetime.fromisoformat(plan_time_iso),
        )
        try:
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


async def assert_real_nacos_publication_completes_before_plan_association(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Recover a scheduled plan after a real Nacos publish but lost plan link."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    test_id = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"nacos-plan-link-{test_id}"
    baseline_version_id = f"nacos-plan-link-baseline-{test_id}"
    activation_version_id = f"nacos-plan-link-activation-{test_id}"
    baseline_validation_id = f"nacos-plan-link-baseline-validation-{test_id}"
    activation_validation_id = f"nacos-plan-link-activation-validation-{test_id}"
    plan_request_key = f"nacos-plan-link-create-{test_id}"
    session_digest = _digest(f"nacos-plan-link-session-{test_id}")
    csrf_digest = _digest(f"nacos-plan-link-csrf-{test_id}")
    username = f"nacos-plan-link-{test_id}"
    data_id = f"sentinel-plan-link-{test_id}.json"
    container_name = f"sentinel-plan-link-nacos-{test_id[:12]}"
    http_port, grpc_port = _free_loopback_port_pair()
    endpoint = f"http://127.0.0.1:{http_port}/nacos"
    target = NacosRulePublicationTarget(
        binding_id=binding_id,
        source_id="acceptance-source",
        namespace="public",
        group=_GROUP,
        data_id=data_id,
    )
    now = datetime.now(UTC).replace(microsecond=0)
    scheduled_at = now - timedelta(seconds=1)
    deactivation_at = now + timedelta(minutes=10)
    plan_id: str | None = None
    rows_seeded = False
    container_id: str | None = None
    container_started = False
    nacos_ready = False
    parent_connection = None
    child_connection = None
    scheduler_process = None
    scheduler_lease_expires_at = now + timedelta(seconds=60)

    baseline_candidate = _candidate(binding_id, count=5)
    activation_candidate = _candidate(binding_id, count=17)
    baseline_checksum = candidate_checksum(baseline_candidate)
    activation_checksum = candidate_checksum(activation_candidate)
    try:
        await _seed_database(
            engine,
            account_id=account_id,
            username=username,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            binding_id=binding_id,
            version_id=baseline_version_id,
            validation_id=baseline_validation_id,
            candidate=baseline_candidate,
            checksum=baseline_checksum,
            promotion_version_id=activation_version_id,
            promotion_validation_id=activation_validation_id,
            promotion_candidate=activation_candidate,
            promotion_checksum=activation_checksum,
        )
        rows_seeded = True

        started = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container_name,
                "--label",
                f"{_CONTAINER_OWNER_LABEL}={test_id}",
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
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        candidate_container_id = started.stdout.strip()
        if len(candidate_container_id) == 64 and all(
            character in "0123456789abcdef"
            for character in candidate_container_id
        ):
            container_id = candidate_container_id
            container_started = True
        else:
            container_id = None
        if started.returncode != 0:
            raise RuntimeError(
                "disposable Nacos container start failed "
                f"(exit={started.returncode})"
            )
        if container_id is None:
            raise AssertionError("Docker did not return a valid Nacos container ID")
        await asyncio.to_thread(_wait_for_nacos, endpoint)
        nacos_ready = True

        baseline_version = await ReadRuleVersion(
            SqlAlchemyRuleVersionReader(engine)
        ).execute(binding_id, baseline_version_id)
        activation_version = await ReadRuleVersion(
            SqlAlchemyRuleVersionReader(engine)
        ).execute(binding_id, activation_version_id)
        encoder = SentinelRuleVersionJsonEncoder(_PROFILE)
        baseline_bytes = encoder.encode_rule_version(baseline_version)
        activation_bytes = encoder.encode_rule_version(activation_version)
        policy = _nacos_target_policy(http_port, grpc_port)
        credential_resolver = _NacosCredentialResolver(endpoint)
        connection = await credential_resolver.resolve_credentials(
            "acceptance-source",
            "source-revision-1",
            ConfigurationSourceProvider.NACOS,
        )
        source_reader = NacosRuleSourceReader(policy)
        source_writer = NacosRuleSourceWriter(policy, source_reader)
        await source_writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=None,
                value=baseline_bytes,
            )
        )
        baseline_snapshot = await source_reader.read(connection, target)
        assert baseline_snapshot.value == baseline_bytes

        target_reader = _NacosTargetReader(target)
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_BindingReader(),
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
            request_id=f"nacos-plan-link-create-{test_id}",
            now=now,
        )
        assert created.status is RuleOperationStatus.COMPLETED
        plan_id = created.result.id

        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=False)
        release_gate = context.Event()
        scheduler_process = context.Process(
            target=_run_scheduler_until_association_boundary,
            args=(
                database_url,
                binding_id,
                data_id,
                now.isoformat(),
                child_connection,
                release_gate,
            ),
            name=f"sentinel-nacos-plan-link-{test_id[:8]}",
        )
        scheduler_process.start()
        child_connection.close()
        child_connection = None
        if not await asyncio.to_thread(parent_connection.poll, 45):
            raise AssertionError("scheduler did not reach the enqueue boundary")
        message = parent_connection.recv()
        assert message.get("status") == "publication_enqueued", message
        publication_id = message["publication_id"]

        async with engine.connect() as sql:
            plan_publication_id = await sql.scalar(
                select(RuleActivationPlanRecord.activation_publication_id).where(
                    RuleActivationPlanRecord.plan_id == plan_id
                )
            )
            publication_state = await sql.execute(
                select(
                    RulePublicationRecord.write_state,
                    RulePublicationRecord.read_back_state,
                ).where(RulePublicationRecord.publication_id == publication_id)
            )
        assert plan_publication_id is None
        assert publication_state.one() == ("awaiting", "awaiting")

        publication_worker = create_nacos_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: now + timedelta(seconds=2),
        )
        provider_write_attempts = 0
        original_write = NacosRuleSourceWriter.write

        async def count_provider_write(writer, command):
            nonlocal provider_write_attempts
            provider_write_attempts += 1
            return await original_write(writer, command)

        with patch.object(NacosRuleSourceWriter, "write", new=count_provider_write):
            assert await publication_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
            assert await publication_worker.run_once() == ()
        assert provider_write_attempts == 1
        activated = await source_reader.read(connection, target)
        assert activated.value == activation_bytes
        assert activated.revision != baseline_snapshot.revision

        publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, publication_id)
        assert publication.configuration_write.state.value == "succeeded"
        assert publication.read_back.state.value == "succeeded"
        before_recovery = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert before_recovery.items[0].state.value == "activating"
        assert before_recovery.items[0].activation_publication_id is None

        scheduler_process.terminate()
        await asyncio.to_thread(scheduler_process.join, 10)
        assert not scheduler_process.is_alive()
        assert scheduler_process.exitcode not in (None, 0)

        recovery_scheduler = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=store,
            clock=lambda: scheduler_lease_expires_at + timedelta(seconds=1),
        )
        assert await recovery_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.COMPLETED,
        )
        assert await recovery_scheduler.run_once() == ()
        recovered = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert recovered.items[0].state.value == "active"
        assert recovered.items[0].activation_publication_id == publication_id
        assert provider_write_attempts == 1
        assert (
            await source_reader.read(connection, target)
        ).revision == activated.revision

        async with engine.connect() as sql:
            operation_count = await sql.scalar(
                select(func.count())
                .select_from(RuleMutationOperationRecord)
                .where(
                    RuleMutationOperationRecord.origin_plan_id == plan_id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            publication_count = await sql.scalar(
                select(func.count())
                .select_from(RulePublicationRecord)
                .where(RulePublicationRecord.publication_id == publication_id)
            )
            accepted_audit_count = await sql.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == plan_id,
                    AuditEventRecord.outcome == "accepted",
                )
            )
            completed_audit_count = await sql.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == plan_id,
                    AuditEventRecord.outcome == "completed",
                )
            )
        assert operation_count == publication_count == 1
        assert accepted_audit_count == completed_audit_count == 1
    finally:
        if scheduler_process is not None and scheduler_process.is_alive():
            scheduler_process.terminate()
            await asyncio.to_thread(scheduler_process.join, 10)
        if parent_connection is not None:
            parent_connection.close()
        if child_connection is not None:
            child_connection.close()
        if not container_started and container_id is None:
            container_id = await asyncio.to_thread(
                _find_owned_container_id, container_name, test_id
            )
            container_started = container_id is not None
        if container_started and container_id is not None:
            try:
                if nacos_ready:
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
                await asyncio.to_thread(_remove_owned_container, container_id, test_id)
        if rows_seeded:
            await _cleanup_database(
                engine,
                account_id=account_id,
                session_digest=session_digest,
                binding_id=binding_id,
                version_ids=(baseline_version_id, activation_version_id),
                validation_ids=(baseline_validation_id, activation_validation_id),
                request_keys=(plan_request_key,),
                plan_ids=tuple(item for item in (plan_id,) if item is not None),
            )


__all__ = ["assert_real_nacos_publication_completes_before_plan_association"]


def _find_owned_container_id(container_name: str, run_id: str) -> str | None:
    """Recover a run-owned container ID if `docker run` timed out after create."""
    inspection = subprocess.run(
        [
            "docker",
            "container",
            "inspect",
            "--format",
            _CONTAINER_INSPECTION_FORMAT,
            container_name,
        ],
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
            raise RuntimeError("cannot verify timed-out Nacos container ownership")
        return None

    container_id, separator, owner = inspection.stdout.strip().partition(" ")
    if (
        not separator
        or len(container_id) != 64
        or any(character not in "0123456789abcdef" for character in container_id)
        or owner != run_id
    ):
        raise RuntimeError("refusing to clean a Nacos container not owned by this run")
    return container_id
