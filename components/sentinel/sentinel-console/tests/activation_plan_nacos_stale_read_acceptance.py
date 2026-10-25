"""Real Nacos stale-read fault injection for SQL activation recovery."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

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
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
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
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)
from nacos_stale_read_fault_proxy import NacosStaleReadFaultProxy
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

_NOW = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
_STALE_READ_OWNER_LABEL = "com.atlas-richie.sentinel-stale-read.run"


async def _assert_activation_plan_nacos_unknown_path(
    engine: AsyncEngine, *, inject_stale_read: bool
) -> None:
    """Accept one Nacos unknown-outcome path against real services.

    The stale response is a previously observed real baseline response replayed
    by a loopback proxy. It is controlled transport fault injection, not a claim
    that Nacos itself has native stale-read behavior.
    """
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"binding-{token}"
    baseline_version_id = f"baseline-{token}"
    baseline_validation_id = f"baseline-validation-{token}"
    promotion_version_id = f"promotion-{token}"
    promotion_validation_id = f"promotion-validation-{token}"
    session_token = f"session-{token}"
    csrf_token = f"csrf-{token}"
    session_digest = _digest(session_token)
    csrf_digest = _digest(csrf_token)
    username = f"stale-read-{token}"
    data_id = f"sentinel-stale-read-{token}.json"
    target = NacosRulePublicationTarget(
        binding_id=binding_id,
        source_id="acceptance-source",
        namespace="public",
        group=_GROUP,
        data_id=data_id,
    )
    candidate = _candidate(binding_id, count=17)
    checksum = candidate_checksum(candidate)
    promotion_candidate = _candidate(binding_id, count=31)
    promotion_checksum = candidate_checksum(promotion_candidate)
    plan_request_key = f"plan-request-{token}"
    plan_id: str | None = None
    container_id: str | None = None
    container_started = False
    sql_seeded = False
    proxy: NacosStaleReadFaultProxy | None = None
    upstream_http_port: int | None = None
    upstream_grpc_port: int | None = None
    upstream_endpoint = f"http://127.0.0.1:{upstream_http_port}/nacos"

    try:
        await upgrade_database(engine)
        await _seed_database(
            engine,
            account_id=account_id,
            username=username,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            binding_id=binding_id,
            version_id=baseline_version_id,
            validation_id=baseline_validation_id,
            candidate=candidate,
            checksum=checksum,
            promotion_version_id=promotion_version_id,
            promotion_validation_id=promotion_validation_id,
            promotion_candidate=promotion_candidate,
            promotion_checksum=promotion_checksum,
        )
        sql_seeded = True

        container_id, upstream_http_port, upstream_grpc_port = await asyncio.to_thread(
            _start_disposable_nacos, token
        )
        container_started = True
        upstream_endpoint = f"http://127.0.0.1:{upstream_http_port}/nacos"
        _wait_for_nacos(upstream_endpoint)

        version_reader = SqlAlchemyRuleVersionReader(engine)
        baseline_version = await ReadRuleVersion(version_reader).execute(
            binding_id, baseline_version_id
        )
        encoded_baseline = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            baseline_version
        )
        assert upstream_http_port is not None and upstream_grpc_port is not None
        upstream_policy = _nacos_target_policy(upstream_http_port, upstream_grpc_port)
        connection = _connection(target.source_id, upstream_endpoint)
        writer = NacosRuleSourceWriter(
            upstream_policy, NacosRuleSourceReader(upstream_policy)
        )
        await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=None,
                value=encoded_baseline,
            )
        )

        proxy = NacosStaleReadFaultProxy(
            upstream_http_port=upstream_http_port,
            upstream_grpc_port=upstream_grpc_port,
            data_id=data_id,
            group=_GROUP,
            baseline=encoded_baseline,
        )
        await proxy.start()
        proxy_policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({proxy.http_port, proxy.grpc_port}),
                )
            ]
        )
        proxy_endpoint = proxy.endpoint
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_BindingReader(),
            publication_target_reader=_NacosTargetReader(target),
        )
        scheduled_for = _NOW + timedelta(seconds=62)
        created = await store.mutate(
            RuleMutationCommand(
                binding_id,
                plan_request_key,
                CreateRuleActivationPlan(
                    promotion_version_id,
                    baseline_version_id,
                    scheduled_for,
                    _NOW + timedelta(seconds=400),
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"plan-http-{token}",
            now=_NOW + timedelta(seconds=61),
        )
        assert created.status is RuleOperationStatus.COMPLETED
        plan_id = created.result.id

        plan_reader = SqlAlchemyRuleActivationPlanReader(engine)
        assert await _run_plan_worker(engine, store, _NOW + timedelta(seconds=63)) == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        plan = (await plan_reader.read_rule_activation_plans(binding_id)).items[0]
        assert plan.id == plan_id
        assert plan.state.value == "activating"
        publication_id = plan.activation_publication_id
        assert isinstance(publication_id, str)

        if inject_stale_read:
            proxy.drop_next_publish_acknowledgement()
        else:
            proxy.abort_next_publish_before_upstream()
        assert await _run_publication_worker(
            engine, proxy_policy, proxy_endpoint, _NOW + timedelta(seconds=64)
        ) == (RulePublicationWorkerOutcome.UNKNOWN,)
        assert proxy.publish_requests_received == 1
        if inject_stale_read:
            assert proxy.successful_upstream_publishes == 1
            assert proxy.publish_requests_forwarded == 1
            assert proxy.dropped_publish_acks == 1
        else:
            assert proxy.successful_upstream_publishes == 0
            assert proxy.publish_requests_forwarded == 0
            assert proxy.dropped_publish_acks == 0
        assert proxy.baseline_reads_forwarded >= 1
        await _assert_publication_is_unknown(engine, binding_id, publication_id)
        assert (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ].state.value == "activating"

        if not inject_stale_read:
            # The proxy accepted the client RPC but never sent it to Nacos.
            # Even though the real provider still has the baseline, Nacos does
            # not advertise the strong-read guarantee needed to replay an
            # unknown CAS. Recovery must remain read-only and keep the plan
            # non-active rather than infer that the write was never applied.
            actual_snapshot = await NacosRuleSourceReader(upstream_policy).read(
                connection, target
            )
            assert actual_snapshot.value == encoded_baseline
            assert await _run_plan_worker(
                engine, store, _NOW + timedelta(seconds=124)
            ) == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
            assert await _run_publication_worker(
                engine, proxy_policy, proxy_endpoint, _NOW + timedelta(seconds=125)
            ) == (RulePublicationWorkerOutcome.UNKNOWN,)
            assert proxy.publish_requests_received == 1
            assert proxy.publish_requests_forwarded == 0
            assert proxy.successful_upstream_publishes == 0
            await _assert_publication_is_unknown(engine, binding_id, publication_id)
            assert (await plan_reader.read_rule_activation_plans(binding_id)).items[
                0
            ].state.value == "activating"
            final_snapshot = await NacosRuleSourceReader(upstream_policy).read(
                connection, target
            )
            assert final_snapshot.value == encoded_baseline
            return

        proxy.serve_one_stale_baseline_read()
        assert await _run_plan_worker(engine, store, _NOW + timedelta(seconds=124)) == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        assert await _run_publication_worker(
            engine, proxy_policy, proxy_endpoint, _NOW + timedelta(seconds=125)
        ) == (RulePublicationWorkerOutcome.UNKNOWN,)
        assert proxy.stale_reads_served == 1
        assert proxy.stale_reads_returned_baseline == 1
        assert proxy.publish_requests_forwarded == 1
        assert proxy.successful_upstream_publishes == 1
        assert proxy.dropped_publish_acks == 1
        await _assert_publication_is_unknown(engine, binding_id, publication_id)
        async with engine.connect() as sql:
            publication_count = await sql.scalar(
                select(func.count())
                .select_from(RulePublicationRecord)
                .where(RulePublicationRecord.publication_id == publication_id)
            )
            plan_state = await sql.scalar(
                select(RuleActivationPlanRecord.state).where(
                    RuleActivationPlanRecord.plan_id == plan_id
                )
            )
        assert publication_count == 1
        assert plan_state == "activating"

        # The one injected stale body is exhausted. The next attempt performs
        # actual Nacos GETs and must reconcile the committed candidate exactly.
        assert await _run_plan_worker(engine, store, _NOW + timedelta(seconds=185)) == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        assert await _run_publication_worker(
            engine, proxy_policy, proxy_endpoint, _NOW + timedelta(seconds=186)
        ) == (RulePublicationWorkerOutcome.COMPLETED,)
        assert proxy.successful_upstream_publishes == 1
        assert proxy.publish_requests_forwarded == 1
        assert proxy.dropped_publish_acks == 1
        assert proxy.stale_reads_served == 1
        assert proxy.candidate_reads_forwarded >= 1
        promotion_version = await ReadRuleVersion(version_reader).execute(
            binding_id, promotion_version_id
        )
        expected_promotion = SentinelRuleVersionJsonEncoder(
            _PROFILE
        ).encode_rule_version(promotion_version)
        real_nacos_snapshot = await NacosRuleSourceReader(upstream_policy).read(
            connection, target
        )
        assert real_nacos_snapshot.value == expected_promotion
        assert (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ].state.value == "activating"
        assert await _run_plan_worker(engine, store, _NOW + timedelta(seconds=247)) == (
            RuleActivationPlanWorkerOutcome.COMPLETED,
        )
        active_plan = (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ]
        assert active_plan.state.value == "active"
        assert active_plan.activation_publication_id == publication_id

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
                .where(
                    RulePublicationRecord.binding_id == binding_id,
                    RulePublicationRecord.publication_id == publication_id,
                )
            )
            audit_count = await sql.scalar(
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
        assert audit_count == 1
    finally:
        if proxy is not None:
            await proxy.close()
        if container_started and container_id is not None:
            try:
                _nacos_admin_request(
                    upstream_endpoint,
                    "DELETE",
                    {"namespaceId": "public", "groupName": _GROUP, "dataId": data_id},
                    allow_failure=True,
                )
            finally:
                await asyncio.to_thread(_remove_owned_container, container_id, token)
        if sql_seeded:
            await _cleanup_database(
                engine,
                account_id=account_id,
                session_digest=session_digest,
                binding_id=binding_id,
                validation_ids=(baseline_validation_id, promotion_validation_id),
                version_ids=(baseline_version_id, promotion_version_id),
                request_keys=(plan_request_key,),
                plan_ids=tuple(item for item in (plan_id,) if item is not None),
            )


async def assert_activation_plan_recovers_after_proxy_injected_nacos_stale_read(
    engine: AsyncEngine,
) -> None:
    """Accept lost-ack then one controlled stale read and exact recovery."""
    await _assert_activation_plan_nacos_unknown_path(engine, inject_stale_read=True)


async def assert_nacos_pre_dispatch_remains_unknown(engine: AsyncEngine) -> None:
    """Accept a pre-dispatch transport loss without unsafe Nacos replay."""
    await _assert_activation_plan_nacos_unknown_path(engine, inject_stale_read=False)


async def assert_nacos_restore_preflight_blocks_external_change(
    engine: AsyncEngine, *, pre_dispatch_unknown: bool = False
) -> None:
    """Accept scheduled Nacos restoration preflight or pre-dispatch unknown."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"nacos-preflight-{token}"
    baseline_version_id = f"baseline-{token}"
    baseline_validation_id = f"baseline-validation-{token}"
    promotion_version_id = f"promotion-{token}"
    promotion_validation_id = f"promotion-validation-{token}"
    session_token = f"session-{token}"
    csrf_token = f"csrf-{token}"
    session_digest = _digest(session_token)
    csrf_digest = _digest(csrf_token)
    username = f"nacos-preflight-{token}"
    data_id = f"sentinel-preflight-{token}.json"
    plan_request_key = f"plan-preflight-{token}"
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    activation_at = now + timedelta(seconds=2)
    restoration_at = activation_at + timedelta(seconds=120)
    target = NacosRulePublicationTarget(
        binding_id=binding_id,
        source_id="acceptance-source",
        namespace="public",
        group=_GROUP,
        data_id=data_id,
    )
    baseline_candidate = _candidate(binding_id, count=5)
    promotion_candidate = _candidate(binding_id, count=31)
    baseline_checksum = candidate_checksum(baseline_candidate)
    promotion_checksum = candidate_checksum(promotion_candidate)
    plan_id: str | None = None
    container_id: str | None = None
    container_started = False
    upstream_endpoint = ""
    proxy: NacosStaleReadFaultProxy | None = None

    try:
        await upgrade_database(engine)
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
            promotion_version_id=promotion_version_id,
            promotion_validation_id=promotion_validation_id,
            promotion_candidate=promotion_candidate,
            promotion_checksum=promotion_checksum,
        )
        container_id, upstream_http_port, upstream_grpc_port = await asyncio.to_thread(
            _start_disposable_nacos, token
        )
        container_started = True
        upstream_endpoint = f"http://127.0.0.1:{upstream_http_port}/nacos"
        _wait_for_nacos(upstream_endpoint)

        version_reader = SqlAlchemyRuleVersionReader(engine)
        encoder = SentinelRuleVersionJsonEncoder(_PROFILE)
        baseline_bytes = encoder.encode_rule_version(
            await ReadRuleVersion(version_reader).execute(
                binding_id, baseline_version_id
            )
        )
        upstream_policy = _nacos_target_policy(upstream_http_port, upstream_grpc_port)
        upstream_connection = _connection(target.source_id, upstream_endpoint)
        source_writer = NacosRuleSourceWriter(
            upstream_policy, NacosRuleSourceReader(upstream_policy)
        )
        await source_writer.write(
            NacosRuleSourceWrite(
                connection=upstream_connection,
                target=target,
                expected_md5=None,
                value=baseline_bytes,
            )
        )

        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_BindingReader(),
            publication_target_reader=_NacosTargetReader(target),
        )
        created = await store.mutate(
            RuleMutationCommand(
                binding_id,
                plan_request_key,
                CreateRuleActivationPlan(
                    promotion_version_id,
                    baseline_version_id,
                    activation_at,
                    restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"nacos-preflight-http-{token}",
            now=now,
        )
        assert created.status is RuleOperationStatus.COMPLETED
        plan_id = created.result.id

        assert await _run_plan_worker(
            engine, store, activation_at + timedelta(milliseconds=1)
        ) == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        assert await _run_publication_worker(
            engine,
            upstream_policy,
            upstream_endpoint,
            activation_at + timedelta(seconds=1),
        ) == (RulePublicationWorkerOutcome.COMPLETED,)
        promotion = await ReadRuleVersion(version_reader).execute(
            binding_id, promotion_version_id
        )
        promotion_bytes = encoder.encode_rule_version(promotion)
        upstream_reader = NacosRuleSourceReader(upstream_policy)
        assert (
            await upstream_reader.read(upstream_connection, target)
        ).value == promotion_bytes
        assert await _run_plan_worker(
            engine, store, activation_at + timedelta(seconds=62)
        ) == (RuleActivationPlanWorkerOutcome.COMPLETED,)

        assert await _run_plan_worker(
            engine, store, restoration_at + timedelta(milliseconds=1)
        ) == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        plan_reader = SqlAlchemyRuleActivationPlanReader(engine)
        restoring_plan = (
            await plan_reader.read_rule_activation_plans(binding_id)
        ).items[0]
        assert restoring_plan.id == plan_id
        assert restoring_plan.state.value == "restoring"
        restore_publication_id = restoring_plan.restore_publication_id
        assert isinstance(restore_publication_id, str)

        if pre_dispatch_unknown:
            proxy = NacosStaleReadFaultProxy(
                upstream_http_port=upstream_http_port,
                upstream_grpc_port=upstream_grpc_port,
                data_id=data_id,
                group=_GROUP,
                baseline=baseline_bytes,
            )
            await proxy.start()
            proxy_policy = RegisteredSourceTargetPolicy(
                [
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.NACOS,
                        "127.0.0.1",
                        ["127.0.0.1/32"],
                        frozenset({proxy.http_port, proxy.grpc_port}),
                    )
                ]
            )
            proxy.abort_next_publish_before_upstream()
            assert await _run_publication_worker(
                engine,
                proxy_policy,
                proxy.endpoint,
                restoration_at + timedelta(seconds=1),
            ) == (RulePublicationWorkerOutcome.UNKNOWN,)
            assert proxy.publish_requests_received == 1
            assert proxy.publish_requests_forwarded == 0
            assert proxy.successful_upstream_publishes == 0
            await _assert_publication_is_unknown(
                engine, binding_id, restore_publication_id
            )
            assert (await plan_reader.read_rule_activation_plans(binding_id)).items[
                0
            ].state.value == "restoring"
            promotion_snapshot = await upstream_reader.read(upstream_connection, target)
            assert promotion_snapshot.value == promotion_bytes

            # Nacos has no strong-read contract for safe CAS replay. A new
            # lease owner may reconcile by exact read, but must not infer that
            # the pre-dispatch abort guarantees a safe second write.
            recovery_candidate_reads = proxy.candidate_reads_forwarded
            assert await _run_plan_worker(
                engine, store, restoration_at + timedelta(seconds=62)
            ) == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
            assert await _run_publication_worker(
                engine,
                proxy_policy,
                proxy.endpoint,
                restoration_at + timedelta(seconds=63),
            ) == (RulePublicationWorkerOutcome.UNKNOWN,)
            assert proxy.candidate_reads_forwarded > recovery_candidate_reads
            assert proxy.publish_requests_received == 1
            assert proxy.publish_requests_forwarded == 0
            await _assert_publication_is_unknown(
                engine, binding_id, restore_publication_id
            )
            still_restoring = (
                await plan_reader.read_rule_activation_plans(binding_id)
            ).items[0]
            assert still_restoring.state.value == "restoring"
            assert still_restoring.restore_publication_id == restore_publication_id
            assert (
                await upstream_reader.read(upstream_connection, target)
            ).value == promotion_bytes
            async with engine.connect() as sql:
                restoration_operations = await sql.scalar(
                    select(func.count())
                    .select_from(RuleMutationOperationRecord)
                    .where(
                        RuleMutationOperationRecord.origin_plan_id == plan_id,
                        RuleMutationOperationRecord.origin_phase == "restoration",
                    )
                )
            assert restoration_operations == 1
            return

        external_payload = json.loads(baseline_bytes)
        assert isinstance(external_payload, list) and external_payload
        assert isinstance(external_payload[0], dict)
        external_payload[0]["count"] = 83
        external_bytes = json.dumps(
            external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        _nacos_admin_request(
            upstream_endpoint,
            "POST",
            {
                "namespaceId": "public",
                "groupName": _GROUP,
                "dataId": data_id,
                "content": external_bytes,
            },
        )
        external_snapshot = await upstream_reader.read(upstream_connection, target)
        assert external_snapshot.value == external_bytes.encode("utf-8")

        write_calls = 0
        original_write = NacosRuleSourceWriter.write

        async def count_provider_writes(writer, command):
            nonlocal write_calls
            write_calls += 1
            return await original_write(writer, command)

        with patch.object(NacosRuleSourceWriter, "write", new=count_provider_writes):
            assert await _run_publication_worker(
                engine,
                upstream_policy,
                upstream_endpoint,
                restoration_at + timedelta(seconds=1),
            ) == (RulePublicationWorkerOutcome.REJECTED,)
        assert write_calls == 0
        assert (
            await upstream_reader.read(upstream_connection, target)
        ) == external_snapshot

        publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restore_publication_id)
        assert publication.validation.state.value == "failed"
        assert publication.validation.reason.value == "conflict"
        assert publication.configuration_write.state.value == "awaiting"
        assert await _run_plan_worker(
            engine, store, restoration_at + timedelta(seconds=62)
        ) == (RuleActivationPlanWorkerOutcome.BLOCKED,)
        blocked_plan = (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ]
        assert blocked_plan.state.value == "blocked"
        assert blocked_plan.restore_publication_id == restore_publication_id
        assert (
            await _run_plan_worker(
                engine, store, restoration_at + timedelta(seconds=124)
            )
            == ()
        )
        assert (
            await _run_publication_worker(
                engine,
                upstream_policy,
                upstream_endpoint,
                restoration_at + timedelta(seconds=125),
            )
            == ()
        )
        assert (
            await upstream_reader.read(upstream_connection, target)
        ) == external_snapshot
        async with engine.connect() as sql:
            restoration_operations = await sql.scalar(
                select(func.count())
                .select_from(RuleMutationOperationRecord)
                .where(
                    RuleMutationOperationRecord.origin_plan_id == plan_id,
                    RuleMutationOperationRecord.origin_phase == "restoration",
                )
            )
        assert restoration_operations == 1
    finally:
        if proxy is not None:
            await proxy.close()
        if container_started and container_id is not None:
            try:
                _nacos_admin_request(
                    upstream_endpoint,
                    "DELETE",
                    {"namespaceId": "public", "groupName": _GROUP, "dataId": data_id},
                    allow_failure=True,
                )
            finally:
                await asyncio.to_thread(_remove_owned_container, container_id, token)
        await _cleanup_database(
            engine,
            account_id=account_id,
            session_digest=session_digest,
            binding_id=binding_id,
            validation_ids=(baseline_validation_id, promotion_validation_id),
            version_ids=(baseline_version_id, promotion_version_id),
            request_keys=(plan_request_key,),
            plan_ids=tuple(item for item in (plan_id,) if item is not None),
        )


async def assert_nacos_worker_dies_while_successful_ack_is_held(
    engine: AsyncEngine,
) -> None:
    """Recover a scheduled activation after its process dies with Nacos ACK in flight."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"nacos-held-ack-{token}"
    baseline_version_id = f"baseline-{token}"
    baseline_validation_id = f"baseline-validation-{token}"
    promotion_version_id = f"promotion-{token}"
    promotion_validation_id = f"promotion-validation-{token}"
    session_digest = _digest(f"nacos-held-ack-session-{token}")
    csrf_digest = _digest(f"nacos-held-ack-csrf-{token}")
    username = f"nacos-held-ack-{token}"
    data_id = f"sentinel-held-ack-{token}.json"
    plan_request_key = f"plan-held-ack-{token}"
    target = NacosRulePublicationTarget(
        binding_id=binding_id,
        source_id="acceptance-source",
        namespace="public",
        group=_GROUP,
        data_id=data_id,
    )
    baseline_candidate = _candidate(binding_id, count=17)
    promotion_candidate = _candidate(binding_id, count=31)
    baseline_checksum = candidate_checksum(baseline_candidate)
    promotion_checksum = candidate_checksum(promotion_candidate)
    scheduled_for = _NOW + timedelta(seconds=62)
    restoration_at = _NOW + timedelta(seconds=400)
    plan_id: str | None = None
    container_id: str | None = None
    container_started = False
    sql_seeded = False
    proxy: NacosStaleReadFaultProxy | None = None
    parent_connection = None
    child_connection = None
    child_process = None
    upstream_endpoint = ""

    try:
        await upgrade_database(engine)
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
            promotion_version_id=promotion_version_id,
            promotion_validation_id=promotion_validation_id,
            promotion_candidate=promotion_candidate,
            promotion_checksum=promotion_checksum,
        )
        sql_seeded = True

        container_id, upstream_http_port, upstream_grpc_port = await asyncio.to_thread(
            _start_disposable_nacos, token
        )
        container_started = True
        upstream_endpoint = f"http://127.0.0.1:{upstream_http_port}/nacos"
        _wait_for_nacos(upstream_endpoint)

        version_reader = SqlAlchemyRuleVersionReader(engine)
        encoder = SentinelRuleVersionJsonEncoder(_PROFILE)
        baseline_bytes = encoder.encode_rule_version(
            await ReadRuleVersion(version_reader).execute(
                binding_id, baseline_version_id
            )
        )
        upstream_policy = _nacos_target_policy(upstream_http_port, upstream_grpc_port)
        upstream_connection = _connection(target.source_id, upstream_endpoint)
        await NacosRuleSourceWriter(
            upstream_policy, NacosRuleSourceReader(upstream_policy)
        ).write(
            NacosRuleSourceWrite(
                connection=upstream_connection,
                target=target,
                expected_md5=None,
                value=baseline_bytes,
            )
        )

        proxy = NacosStaleReadFaultProxy(
            upstream_http_port=upstream_http_port,
            upstream_grpc_port=upstream_grpc_port,
            data_id=data_id,
            group=_GROUP,
            baseline=baseline_bytes,
        )
        await proxy.start()
        proxy_policy = RegisteredSourceTargetPolicy(
            [
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "127.0.0.1",
                    ["127.0.0.1/32"],
                    frozenset({proxy.http_port, proxy.grpc_port}),
                )
            ]
        )
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_BindingReader(),
            publication_target_reader=_NacosTargetReader(target),
        )
        created = await store.mutate(
            RuleMutationCommand(
                binding_id,
                plan_request_key,
                CreateRuleActivationPlan(
                    promotion_version_id,
                    baseline_version_id,
                    scheduled_for,
                    restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"nacos-held-ack-http-{token}",
            now=_NOW + timedelta(seconds=61),
        )
        assert created.status is RuleOperationStatus.COMPLETED
        plan_id = created.result.id

        proxy.hold_next_successful_publish_acknowledgement()
        process_context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = process_context.Pipe(duplex=False)
        child_process = process_context.Process(
            target=_run_nacos_activation_publish_until_held_ack,
            args=(
                engine.url.render_as_string(hide_password=False),
                target,
                proxy.http_port,
                proxy.grpc_port,
                scheduled_for.isoformat(),
                child_connection,
            ),
            name=f"sentinel-nacos-held-ack-{token[:8]}",
        )
        child_process.start()
        child_connection.close()
        child_connection = None
        ready = await asyncio.to_thread(parent_connection.poll, 45)
        assert ready, "Nacos activation worker did not enqueue the scheduled phase"
        message = parent_connection.recv()
        assert message == {"status": "activation-enqueued"}, message
        await proxy.wait_for_held_publish_acknowledgement(timeout=60)
        assert proxy.publish_requests_received == 1
        assert proxy.publish_requests_forwarded == 1
        assert proxy.successful_upstream_publishes == 1

        promotion = await ReadRuleVersion(version_reader).execute(
            binding_id, promotion_version_id
        )
        promotion_bytes = encoder.encode_rule_version(promotion)
        provider_snapshot = await NacosRuleSourceReader(upstream_policy).read(
            upstream_connection, target
        )
        assert provider_snapshot.value == promotion_bytes
        plan_reader = SqlAlchemyRuleActivationPlanReader(engine)
        current_plan = (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ]
        assert current_plan.id == plan_id
        assert current_plan.state.value == "activating"
        publication_id = current_plan.activation_publication_id
        assert isinstance(publication_id, str)
        async with engine.connect() as sql:
            publication = (
                (
                    await sql.execute(
                        select(RulePublicationRecord.__table__).where(
                            RulePublicationRecord.publication_id == publication_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            operation = (
                (
                    await sql.execute(
                        select(RuleMutationOperationRecord.__table__).where(
                            RuleMutationOperationRecord.origin_plan_id == plan_id,
                            RuleMutationOperationRecord.origin_phase == "activation",
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert publication["write_state"] == "running"
        assert publication["read_back_state"] == "awaiting"
        assert operation["status"] == "pending"

        child_process.terminate()
        await asyncio.to_thread(child_process.join, 10)
        assert not child_process.is_alive()
        assert child_process.exitcode is not None and child_process.exitcode != 0
        proxy.release_held_publish_acknowledgement()

        assert await _run_plan_worker(engine, store, _NOW + timedelta(seconds=124)) == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        assert await _run_publication_worker(
            engine,
            proxy_policy,
            proxy.endpoint,
            _NOW + timedelta(seconds=125),
        ) == (RulePublicationWorkerOutcome.COMPLETED,)
        assert proxy.publish_requests_received == 1
        assert proxy.publish_requests_forwarded == 1
        assert proxy.successful_upstream_publishes == 1
        assert proxy.candidate_reads_forwarded >= 1
        assert (
            await NacosRuleSourceReader(upstream_policy).read(
                upstream_connection, target
            )
        ).value == promotion_bytes

        assert await _run_plan_worker(engine, store, _NOW + timedelta(seconds=186)) == (
            RuleActivationPlanWorkerOutcome.COMPLETED,
        )
        active_plan = (await plan_reader.read_rule_activation_plans(binding_id)).items[
            0
        ]
        assert active_plan.state.value == "active"
        assert active_plan.activation_publication_id == publication_id
        completed = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, publication_id)
        assert completed.configuration_write.state.value == "succeeded"
        assert completed.read_back.state.value == "succeeded"
        async with engine.connect() as sql:
            publication_count = await sql.scalar(
                select(func.count())
                .select_from(RulePublicationRecord)
                .where(RulePublicationRecord.binding_id == binding_id)
            )
            activation_operation_count = await sql.scalar(
                select(func.count())
                .select_from(RuleMutationOperationRecord)
                .where(
                    RuleMutationOperationRecord.origin_plan_id == plan_id,
                    RuleMutationOperationRecord.origin_phase == "activation",
                )
            )
            completion_audit_count = await sql.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == "rules.activation_plan.activate",
                    AuditEventRecord.target_id == plan_id,
                    AuditEventRecord.outcome == "completed",
                )
            )
        assert publication_count == 1
        assert activation_operation_count == 1
        assert completion_audit_count == 1

        # Exercise the symmetric restoration failure window: Nacos has already
        # committed the immutable baseline, but the scheduled worker dies before
        # receiving the successful gRPC acknowledgement.
        assert await _run_plan_worker(
            engine, store, restoration_at + timedelta(seconds=1)
        ) == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        restoring_plan = (
            await plan_reader.read_rule_activation_plans(binding_id)
        ).items[0]
        assert restoring_plan.id == plan_id
        assert restoring_plan.state.value == "restoring"
        restoration_publication_id = restoring_plan.restore_publication_id
        assert isinstance(restoration_publication_id, str)

        proxy.hold_next_successful_publish_acknowledgement()
        if parent_connection is not None:
            parent_connection.close()
            parent_connection = None
        parent_connection, child_connection = process_context.Pipe(duplex=False)
        child_process = process_context.Process(
            target=_run_nacos_restoration_publish_until_held_ack,
            args=(
                engine.url.render_as_string(hide_password=False),
                target,
                proxy.http_port,
                proxy.grpc_port,
                (restoration_at + timedelta(seconds=2)).isoformat(),
                child_connection,
            ),
            name=f"sentinel-nacos-restore-held-ack-{token[:8]}",
        )
        child_process.start()
        child_connection.close()
        child_connection = None
        ready = await asyncio.to_thread(parent_connection.poll, 45)
        assert ready, "Nacos restoration worker did not start publication"
        message = parent_connection.recv()
        assert message == {"status": "restoration-publish-started"}, message
        await proxy.wait_for_held_publish_acknowledgement(timeout=60)
        assert proxy.publish_requests_received == 2
        assert proxy.publish_requests_forwarded == 2
        assert proxy.successful_upstream_publishes == 2

        restored_snapshot = await NacosRuleSourceReader(upstream_policy).read(
            upstream_connection, target
        )
        assert restored_snapshot.value == baseline_bytes
        restoring_plan = (
            await plan_reader.read_rule_activation_plans(binding_id)
        ).items[0]
        assert restoring_plan.state.value == "restoring"
        restoration_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restoration_publication_id)
        assert restoration_publication.configuration_write.state.value == "running"
        assert restoration_publication.read_back.state.value == "awaiting"

        child_process.terminate()
        await asyncio.to_thread(child_process.join, 10)
        assert not child_process.is_alive()
        assert child_process.exitcode is not None and child_process.exitcode != 0
        proxy.release_held_publish_acknowledgement()

        restoration_recovery_writes = 0
        original_write = NacosRuleSourceWriter.write

        async def count_restoration_recovery_writes(writer, command):
            nonlocal restoration_recovery_writes
            restoration_recovery_writes += 1
            return await original_write(writer, command)

        with patch.object(
            NacosRuleSourceWriter,
            "write",
            new=count_restoration_recovery_writes,
        ):
            assert await _run_publication_worker(
                engine,
                proxy_policy,
                proxy.endpoint,
                restoration_at + timedelta(seconds=62),
            ) == (RulePublicationWorkerOutcome.COMPLETED,)
        assert restoration_recovery_writes == 0
        assert proxy.publish_requests_received == 2
        assert proxy.publish_requests_forwarded == 2
        assert proxy.successful_upstream_publishes == 2
        assert (
            await NacosRuleSourceReader(upstream_policy).read(
                upstream_connection, target
            )
        ).value == baseline_bytes

        assert await _run_plan_worker(
            engine, store, restoration_at + timedelta(seconds=124)
        ) == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        completed_plan = (
            await plan_reader.read_rule_activation_plans(binding_id)
        ).items[0]
        assert completed_plan.state.value == "completed"
        assert completed_plan.restore_publication_id == restoration_publication_id
        completed_restoration = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restoration_publication_id)
        assert completed_restoration.configuration_write.state.value == "succeeded"
        assert completed_restoration.read_back.state.value == "succeeded"
    finally:
        if child_process is not None and child_process.is_alive():
            child_process.terminate()
            await asyncio.to_thread(child_process.join, 10)
        if child_connection is not None:
            child_connection.close()
        if parent_connection is not None:
            parent_connection.close()
        if proxy is not None:
            proxy.release_held_publish_acknowledgement()
            await proxy.close()
        if container_started and container_id is not None:
            try:
                _nacos_admin_request(
                    upstream_endpoint,
                    "DELETE",
                    {"namespaceId": "public", "groupName": _GROUP, "dataId": data_id},
                    allow_failure=True,
                )
            finally:
                await asyncio.to_thread(_remove_owned_container, container_id, token)
        if sql_seeded:
            await _cleanup_database(
                engine,
                account_id=account_id,
                session_digest=session_digest,
                binding_id=binding_id,
                validation_ids=(baseline_validation_id, promotion_validation_id),
                version_ids=(baseline_version_id, promotion_version_id),
                request_keys=(plan_request_key,),
                plan_ids=tuple(item for item in (plan_id,) if item is not None),
            )


async def assert_nacos_restore_pre_dispatch_remains_unknown(
    engine: AsyncEngine,
) -> None:
    """Keep a lost-before-upstream restoration dispatch pending and unreplayed."""
    await assert_nacos_restore_preflight_blocks_external_change(
        engine, pre_dispatch_unknown=True
    )


def _connection(source_id: str, endpoint: str) -> SourceConnectionInput:
    return SourceConnectionInput(
        source_id=source_id,
        expected_revision="source-revision-1",
        provider=ConfigurationSourceProvider.NACOS,
        endpoint=endpoint,
        location="public",
        authentication_mode=SourceCheckAuthenticationMode.NONE,
    )


def _start_disposable_nacos(run_id: str) -> tuple[str, int, int]:
    """Start Nacos with bounded retry only for confirmed host-port conflicts."""
    for attempt in range(1, 6):
        http_port, grpc_port = _free_loopback_port_pair()
        container_name = f"sentinel-stale-nacos-{run_id[:12]}-{attempt}"
        result = subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container_name,
                "--label",
                f"{_CONTAINER_OWNER_LABEL}={run_id}",
                "--label",
                f"{_STALE_READ_OWNER_LABEL}={run_id}",
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
        container_id = result.stdout.strip()
        if result.returncode == 0:
            if len(container_id) != 64 or any(
                character not in "0123456789abcdef" for character in container_id
            ):
                raise AssertionError("Docker did not return a valid Nacos container ID")
            return container_id, http_port, grpc_port

        _remove_failed_owned_nacos(container_name, run_id)
        if "address already in use" not in result.stderr.casefold():
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
    raise RuntimeError("Nacos host-port conflict persisted after five attempts")


def _remove_failed_owned_nacos(container_name: str, run_id: str) -> None:
    """Remove a failed-start container only after exact id/owner verification."""
    inspection_format = (
        f'{{{{.Id}}}} {{{{ index .Config.Labels "{_CONTAINER_OWNER_LABEL}"' + " }}"
    )
    inspection = subprocess.run(
        [
            "docker",
            "container",
            "inspect",
            "--format",
            inspection_format,
            container_name,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if inspection.returncode != 0:
        return
    container_id, owner = inspection.stdout.strip().split(maxsplit=1)
    if owner != run_id:
        raise RuntimeError("refusing to remove failed Nacos container not owned by run")
    _remove_owned_container(container_id, run_id)


async def _run_plan_worker(engine, store, instant: datetime):
    return await RunRuleActivationPlanWorker(
        work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
        publication_enqueuer=store,
        clock=lambda: instant,
    ).run_once()


def _run_nacos_activation_publish_until_held_ack(
    database_url: str,
    target: NacosRulePublicationTarget,
    proxy_http_port: int,
    proxy_grpc_port: int,
    scheduled_for_iso: str,
    result_connection,
) -> None:
    """Run production scheduler and publication workers in a killable process."""

    async def run() -> None:
        instant = datetime.fromisoformat(scheduled_for_iso) + timedelta(seconds=1)
        engine = create_async_engine(database_url, pool_size=1)
        try:
            store = SqlAlchemyRuleMutationStore(
                engine,
                fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
                active_fingerprint_key_id="acceptance",
                binding_reader=_BindingReader(),
                publication_target_reader=_NacosTargetReader(target),
            )
            scheduled = await _run_plan_worker(engine, store, instant)
            if scheduled != (RuleActivationPlanWorkerOutcome.ENQUEUED,):
                raise AssertionError("scheduled Nacos activation was not enqueued")
            result_connection.send({"status": "activation-enqueued"})
            proxy_policy = RegisteredSourceTargetPolicy(
                [
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.NACOS,
                        "127.0.0.1",
                        ["127.0.0.1/32"],
                        frozenset({proxy_http_port, proxy_grpc_port}),
                    )
                ]
            )
            await _run_publication_worker(
                engine,
                proxy_policy,
                f"http://127.0.0.1:{proxy_http_port}/nacos",
                instant + timedelta(seconds=1),
            )
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


def _run_nacos_restoration_publish_until_held_ack(
    database_url: str,
    target: NacosRulePublicationTarget,
    proxy_http_port: int,
    proxy_grpc_port: int,
    restoration_instant_iso: str,
    result_connection,
) -> None:
    """Run the real restoration publication in a killable worker process."""

    async def run() -> None:
        instant = datetime.fromisoformat(restoration_instant_iso)
        engine = create_async_engine(database_url, pool_size=1)
        try:
            result_connection.send({"status": "restoration-publish-started"})
            proxy_policy = RegisteredSourceTargetPolicy(
                [
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.NACOS,
                        "127.0.0.1",
                        ["127.0.0.1/32"],
                        frozenset({proxy_http_port, proxy_grpc_port}),
                    )
                ]
            )
            await _run_publication_worker(
                engine,
                proxy_policy,
                f"http://127.0.0.1:{proxy_http_port}/nacos",
                instant,
            )
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


async def _run_publication_worker(engine, policy, endpoint, instant: datetime):
    worker = create_nacos_rule_publication_worker(
        engine,
        target_policy=policy,
        credential_resolver=_NacosCredentialResolver(endpoint),
        credential_reference_resolver=None,
        profile_id=_PROFILE,
        clock=lambda: instant,
    )
    return await worker.run_once()


async def _assert_publication_is_unknown(
    engine: AsyncEngine, binding_id: str, publication_id: str
) -> None:
    publication = await ReadRulePublication(
        SqlAlchemyRulePublicationReader(engine)
    ).execute(binding_id, publication_id)
    assert publication.configuration_write.state.value == "unknown"
    assert publication.read_back.state.value == "awaiting"


__all__ = [
    "assert_activation_plan_recovers_after_proxy_injected_nacos_stale_read",
    "assert_nacos_pre_dispatch_remains_unknown",
    "assert_nacos_restore_pre_dispatch_remains_unknown",
    "assert_nacos_restore_preflight_blocks_external_change",
    "assert_nacos_worker_dies_while_successful_ack_is_held",
]
