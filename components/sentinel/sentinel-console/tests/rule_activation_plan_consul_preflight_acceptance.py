"""Real Consul acceptance for scheduled restoration preflight conflicts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

from consul_acl_test_support import DisposableConsulAclServer
from rule_publication_consul_database_acceptance import (
    _FINGERPRINT_KEY,
    _PROFILE,
    _AcceptanceBindingReader,
    _AcceptancePublicationTargetReader,
    _AcceptanceSourceReferenceResolver,
    _candidate,
    _cleanup_activation_rows,
    _digest,
    _seed_identity,
    _seed_version,
)
from sqlalchemy import delete, insert, select, func
from sqlalchemy.ext.asyncio import AsyncEngine

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
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
from atlas_richie.sentinel_console.application.resolve_registered_source_connection import (
    ResolveRegisteredSourceConnection,
)
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
from atlas_richie.sentinel_console.domain.registered_sources import (
    SourceAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    RegisteredConfigurationSourceRecord,
    RuleMutationOperationRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_store import (
    SqlAlchemyRegisteredSourceStore,
    encrypt_registered_source_credentials,
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
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)


async def assert_consul_restore_preflight_blocks_external_change(
    engine: AsyncEngine,
) -> None:
    """Prove restore preflight performs no CAS after a prior external edit."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    account_id = str(uuid4())
    binding_id = f"consul-preflight-{token}"
    source_id = "acceptance-source"
    baseline_version_id = f"consul-preflight-baseline-{token}"
    activation_version_id = f"consul-preflight-activation-{token}"
    baseline_validation_id = f"consul-preflight-baseline-validation-{token}"
    activation_validation_id = f"consul-preflight-activation-validation-{token}"
    request_key = f"consul-preflight-plan-{token}"
    session_digest = _digest(f"consul-preflight-session-{token}")
    csrf_digest = _digest(f"consul-preflight-csrf-{token}")
    username = f"consul-preflight-{token}"
    source_revision = "source-revision-1"
    source_reference = f"secret://consul/preflight/{token}"
    key = f"sentinel/acceptance/{token}/preflight.json"
    activation_at = now + timedelta(seconds=2)
    restoration_at = activation_at + timedelta(seconds=120)
    consul_server: DisposableConsulAclServer | None = None
    source_seeded = False
    identity_seeded = False
    versions_seeded = False

    try:
        await upgrade_database(engine)
        await _seed_identity(
            engine,
            account_id=account_id,
            username=username,
            username_key=_digest(username),
            session_digest=session_digest,
            csrf_digest=csrf_digest,
        )
        identity_seeded = True
        baseline_candidate = _candidate(binding_id, count=5)
        activation_candidate = _candidate(binding_id, count=17)
        await _seed_version(
            engine,
            account_id=account_id,
            binding_id=binding_id,
            version_id=baseline_version_id,
            validation_id=baseline_validation_id,
            candidate=baseline_candidate,
            checksum=candidate_checksum(baseline_candidate),
        )
        await _seed_version(
            engine,
            account_id=account_id,
            binding_id=binding_id,
            version_id=activation_version_id,
            validation_id=activation_validation_id,
            candidate=activation_candidate,
            checksum=candidate_checksum(activation_candidate),
        )
        versions_seeded = True

        consul_server = DisposableConsulAclServer(key)
        await consul_server.start()
        source_cipher = AesGcmSecretCipher(
            "consul-source-v1",
            {"consul-source-v1": b"consul-source-secret-key-acceptance-0001"[:32]},
        )
        source_input = SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint=consul_server.endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
            credential_reference=source_reference,
        )
        encrypted_credentials = encrypt_registered_source_credentials(
            source_input, source_id, source_cipher
        )
        if encrypted_credentials is None:
            raise AssertionError("Consul acceptance credentials were not encrypted")
        async with engine.begin() as connection:
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=source_id,
                    revision=source_revision,
                    name="Disposable Consul restoration preflight acceptance",
                    endpoint=consul_server.endpoint,
                    provider=ConfigurationSourceProvider.CONSUL.value,
                    location="dc1",
                    authentication_mode=SourceAuthenticationMode.CREDENTIAL_REFERENCE.value,
                    credential_configured=True,
                    credential_cipher_format=encrypted_credentials.format.value,
                    credential_key_id=encrypted_credentials.key_id,
                    credential_payload=encrypted_credentials.payload,
                    created_at=now,
                    updated_at=now,
                    updated_by_account_id=account_id,
                )
            )
        source_seeded = True

        credential_store = SqlAlchemyRegisteredSourceStore(
            engine,
            secret_cipher=source_cipher,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
        )
        reference_resolver = _AcceptanceSourceReferenceResolver(
            source_reference, consul_server.application_token
        )
        target_policy = consul_server.registered_target_policy()
        reader = ConsulRuleSourceReader(target_policy, consul_server.http_client())
        target_reader = _AcceptancePublicationTargetReader(key)
        mutation_store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_AcceptanceBindingReader(),
            publication_target_reader=target_reader,
            publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
        )
        queue = SqlAlchemyRuleActivationPlanWorkQueue(engine)

        versions = SqlAlchemyRuleVersionReader(engine)
        encoder = SentinelRuleVersionJsonEncoder(_PROFILE)
        baseline_bytes = encoder.encode_rule_version(
            await ReadRuleVersion(versions).execute(binding_id, baseline_version_id)
        )
        activation_bytes = encoder.encode_rule_version(
            await ReadRuleVersion(versions).execute(binding_id, activation_version_id)
        )
        consul_server.write_management_value(key, baseline_bytes)
        unresolved_source_connection = await credential_store.resolve_credentials(
            source_id, source_revision, ConfigurationSourceProvider.CONSUL
        )
        if unresolved_source_connection is None:
            raise AssertionError("registered Consul source was not readable")
        source_connection = await ResolveRegisteredSourceConnection(
            credential_store, reference_resolver
        ).execute(source_id, source_revision, ConfigurationSourceProvider.CONSUL)
        initial_snapshot = await reader.read(source_connection, key)
        if initial_snapshot.value != baseline_bytes:
            raise AssertionError("Consul baseline was not provisioned exactly")

        created = await mutation_store.mutate(
            RuleMutationCommand(
                binding_id,
                request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    activation_at,
                    restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-preflight-http-{token}",
            now=now,
        )
        if created.status is not RuleOperationStatus.COMPLETED:
            raise AssertionError("activation plan was not persisted")
        plan_id = created.result.id

        async def run_scheduler(at: datetime):
            return await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=mutation_store,
                clock=lambda: at,
            ).run_once()

        async def run_provider_worker(at: datetime):
            worker = create_consul_rule_publication_worker(
                engine,
                target_policy=target_policy,
                credential_resolver=credential_store,
                credential_reference_resolver=reference_resolver,
                profile_id=_PROFILE,
                ssl_context=consul_server.client_ssl_context,
                clock=lambda: at,
            )
            return await worker.run_once()

        if await run_scheduler(activation_at + timedelta(milliseconds=1)) != (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        ):
            raise AssertionError("activation phase was not enqueued")
        if await run_provider_worker(activation_at + timedelta(seconds=1)) != (
            RulePublicationWorkerOutcome.COMPLETED,
        ):
            raise AssertionError("Consul activation did not complete")
        if (await reader.read(source_connection, key)).value != activation_bytes:
            raise AssertionError("Consul did not retain the activated rule snapshot")
        if await run_scheduler(activation_at + timedelta(seconds=62)) != (
            RuleActivationPlanWorkerOutcome.COMPLETED,
        ):
            raise AssertionError("activation plan did not enter active state")

        if await run_scheduler(restoration_at + timedelta(milliseconds=1)) != (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        ):
            raise AssertionError("restoration phase was not enqueued")
        restoring = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        restoring_plan = next(item for item in restoring.items if item.id == plan_id)
        if restoring_plan.state.value != "restoring":
            raise AssertionError("plan did not persist restoring state")
        restoration_publication_id = restoring_plan.restore_publication_id
        if not isinstance(restoration_publication_id, str):
            raise AssertionError("restoration publication was not linked")

        external_payload = json.loads(baseline_bytes)
        if not isinstance(external_payload, list) or not external_payload:
            raise AssertionError("encoded baseline was not a rule list")
        if not isinstance(external_payload[0], dict):
            raise AssertionError("encoded baseline item was not an object")
        external_payload[0]["count"] = 83
        external_bytes = json.dumps(
            external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if external_bytes == baseline_bytes or external_bytes == activation_bytes:
            raise AssertionError("external test payload did not differ")
        consul_server.write_management_value(key, external_bytes)
        external_snapshot = await reader.read(source_connection, key)
        if external_snapshot.value != external_bytes:
            raise AssertionError("external Consul change was not accepted")
        encoded_key = f"/v1/kv/{key}?"
        cas_count_before = sum(
            path.startswith(encoded_key) and "cas=" in path
            for path, _ in consul_server.observed_requests
        )

        if await run_provider_worker(restoration_at + timedelta(seconds=1)) != (
            RulePublicationWorkerOutcome.REJECTED,
        ):
            raise AssertionError("restoration preflight did not reject changed baseline")
        cas_count_after = sum(
            path.startswith(encoded_key) and "cas=" in path
            for path, _ in consul_server.observed_requests
        )
        if cas_count_after != cas_count_before:
            raise AssertionError("restoration preflight issued a Consul CAS")
        if await reader.read(source_connection, key) != external_snapshot:
            raise AssertionError("restoration overwrote external Consul bytes")

        if await run_scheduler(restoration_at + timedelta(seconds=62)) != (
            RuleActivationPlanWorkerOutcome.BLOCKED,
        ):
            raise AssertionError("plan was not durably blocked after restore conflict")
        blocked = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        blocked_plan = next(item for item in blocked.items if item.id == plan_id)
        if blocked_plan.state.value != "blocked":
            raise AssertionError("blocked plan state was not persisted")
        if blocked_plan.restore_publication_id != restoration_publication_id:
            raise AssertionError("blocked plan lost its restoration publication")
        restoration_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restoration_publication_id)
        if (
            restoration_publication.validation.state.value != "failed"
            or restoration_publication.validation.reason.value != "conflict"
            or restoration_publication.configuration_write.state.value != "awaiting"
        ):
            raise AssertionError("restore conflict was not persisted")
        if await run_scheduler(restoration_at + timedelta(seconds=124)) != ():
            raise AssertionError("blocked plan created a follow-up restoration phase")
        if await run_provider_worker(restoration_at + timedelta(seconds=125)) != ():
            raise AssertionError("failed restoration publication was replayed")
        if await reader.read(source_connection, key) != external_snapshot:
            raise AssertionError("external Consul bytes changed after blocking")

        async with engine.connect() as connection:
            restoration_operations = await connection.scalar(
                select(func.count()).select_from(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id == plan_id,
                    RuleMutationOperationRecord.origin_phase == "restoration",
                )
            )
        if restoration_operations != 1:
            raise AssertionError("blocked plan created duplicate restoration operations")
    finally:
        if source_seeded:
            async with engine.begin() as connection:
                await connection.execute(
                    delete(RegisteredConfigurationSourceRecord).where(
                        RegisteredConfigurationSourceRecord.source_id == source_id
                    )
                )
        if identity_seeded or versions_seeded:
            await _cleanup_activation_rows(
                engine,
                account_id=account_id,
                session_digest=session_digest,
                binding_id=binding_id,
                plan_request_keys=(request_key,),
                version_ids=(baseline_version_id, activation_version_id),
                validation_ids=(baseline_validation_id, activation_validation_id),
            )
        if consul_server is not None:
            await consul_server.close()


__all__ = ["assert_consul_restore_preflight_blocks_external_change"]
