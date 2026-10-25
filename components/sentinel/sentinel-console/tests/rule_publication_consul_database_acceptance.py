"""Opt-in SQL-dialect to disposable Consul publication acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import ssl
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from consul_acl_test_support import DisposableConsulAclServer
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
    PublishRuleVersion,
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
    RunRulePublicationWorker,
)
from atlas_richie.sentinel_console.application.source_credential_references import (
    ResolvedSourceCredentials,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.registered_sources import (
    SourceAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import (
    RuleSetCandidate,
    candidate_checksum,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
    ConsulRuleSourceSnapshot,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceWriter,
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
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
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
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_PROFILE = "sentinel-profile-v1"
_FINGERPRINT_KEY = b"synthetic-cross-database-consul-acceptance-key-0001"
_NOW = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)


def _write_consul_value_from_external_process(
    port: int,
    management_token: str,
    key: str,
    value: bytes,
) -> None:
    """Apply a synthetic management-plane update from an independent process."""
    request = Request(
        f"http://127.0.0.1:{port}/v1/kv/{quote(key, safe='/')}?dc=dc1",
        data=value,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Consul-Token": management_token,
        },
        method="PUT",
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200 or response.read() != b"true":
            raise AssertionError("disposable Consul rejected external test write")


async def _assert_cas_is_rejected_after_external_process_write(
    *,
    worker: RunRulePublicationWorker,
    consul_server: DisposableConsulAclServer,
    reader: ConsulRuleSourceReader,
    source_connection: SourceConnectionInput,
    key: str,
    expected_snapshot: ConsulRuleSourceSnapshot,
    external_value: bytes,
) -> ConsulRuleSourceSnapshot:
    """Race a separate management process against one exact production CAS."""
    if expected_snapshot.modify_index is None:
        raise AssertionError("CAS race requires an existing baseline revision")

    consul_server.arm_hold_cas_before_upstream(key)
    publication_task = asyncio.create_task(worker.run_once())
    external_writer_process = multiprocessing.get_context("spawn").Process(
        target=_write_consul_value_from_external_process,
        args=(
            consul_server.port,
            consul_server.management_token,
            key,
            external_value,
        ),
    )
    try:
        await consul_server.wait_for_held_cas(timeout=20)
        cas_requests = [
            request_path
            for request_path, _ in consul_server.observed_requests
            if request_path.startswith(f"/v1/kv/{quote(key, safe='/')}?")
        ]
        if not cas_requests:
            raise AssertionError("production worker did not send the expected CAS")
        cas_query = parse_qs(urlsplit(cas_requests[-1]).query)
        if cas_query.get("cas") != [expected_snapshot.modify_index]:
            raise AssertionError("production CAS did not use its observed baseline")

        external_writer_process.start()
        await asyncio.to_thread(external_writer_process.join, 15)
        if external_writer_process.is_alive():
            raise AssertionError("external Consul writer process did not finish")
        if external_writer_process.exitcode != 0:
            raise AssertionError("external Consul writer process failed")

        external_snapshot = await reader.read(source_connection, key)
        if external_snapshot.value != external_value:
            raise AssertionError("Consul did not retain the external writer value")
        if external_snapshot.modify_index == expected_snapshot.modify_index:
            raise AssertionError("external Consul write did not advance ModifyIndex")

        consul_server.release_held_cas()
        outcome = await asyncio.wait_for(publication_task, timeout=20)
        if outcome != (RulePublicationWorkerOutcome.REJECTED,):
            raise AssertionError("stale Consul CAS was not rejected by the worker")
        return external_snapshot
    finally:
        consul_server.release_held_cas()
        if not publication_task.done():
            publication_task.cancel()
        await asyncio.gather(publication_task, return_exceptions=True)
        if external_writer_process.pid is not None:
            if external_writer_process.is_alive():
                external_writer_process.terminate()
            await asyncio.to_thread(external_writer_process.join, 10)
            external_writer_process.close()


def _run_consul_write_then_pause_worker(
    database_url: str,
    endpoint: str,
    acl_token: str,
    ca_pem: str,
    port: int,
    key: str,
    now_iso: str,
    connection,
) -> None:
    """Run a real worker in a child while the proxy holds its Consul response."""

    async def run() -> None:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            rule = RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.CONSUL,
                "127.0.0.1",
                ("127.0.0.1/32",),
                frozenset({port}),
            )
            resolver = _AcceptanceConsulCredentialResolver(endpoint, acl_token)
            worker = create_consul_rule_publication_worker(
                engine,
                target_policy=RegisteredSourceTargetPolicy((rule,)),
                credential_resolver=resolver,
                credential_reference_resolver=None,
                profile_id=_PROFILE,
                ssl_context=ssl.create_default_context(cadata=ca_pem),
                clock=lambda: datetime.fromisoformat(now_iso),
            )
            connection.send({"status": "worker-started"})
            await worker.run_once()
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except BaseException as error:
        try:
            connection.send({"status": "error", "error_type": type(error).__name__})
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    finally:
        connection.close()


async def assert_consul_process_termination_recovers_after_real_write(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Prove real Consul CAS recovery after the publishing OS process is killed."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    actor_id = account_id
    binding_id = f"consul-kill-binding-{token}"
    version_id = f"consul-kill-version-{token}"
    validation_id = f"consul-kill-validation-{token}"
    request_key = f"consul-kill-request-{token}"
    session_digest = _digest(f"consul-kill-session-{token}")
    csrf_digest = _digest(f"consul-kill-csrf-{token}")
    username = f"consul-kill-{token}"
    key = f"sentinel/acceptance/{token}/process-kill.json"
    consul_server: DisposableConsulAclServer | None = None
    parent_connection = None
    child_connection = None
    child_process = None
    identity_seeded = False
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
        candidate = _candidate(binding_id)
        checksum = candidate_checksum(candidate)
        await _seed_version(
            engine,
            account_id=account_id,
            binding_id=binding_id,
            version_id=version_id,
            validation_id=validation_id,
            candidate=candidate,
            checksum=checksum,
        )
        consul_server = DisposableConsulAclServer(key)
        await consul_server.start()
        consul_server.arm_response_drop_after_commit(key)
        target_reader = _AcceptancePublicationTargetReader(key)
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_AcceptanceBindingReader(),
            publication_target_reader=target_reader,
            publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
        )
        accepted = await store.mutate(
            RuleMutationCommand(
                binding_id,
                request_key,
                PublishRuleVersion(
                    version_id,
                    checksum,
                    None,
                    "sha256:baseline",
                    "target-revision-1",
                    "synthetic process-kill acceptance",
                ),
            ),
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"http-{token}",
            now=_NOW,
        )
        assert accepted.status is RuleOperationStatus.PENDING

        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=False)
        child_process = context.Process(
            target=_run_consul_write_then_pause_worker,
            args=(
                database_url,
                consul_server.endpoint,
                consul_server.application_token,
                consul_server.client_ca_pem,
                consul_server.proxy_port,
                key,
                _NOW.isoformat(),
                child_connection,
            ),
            name=f"sentinel-consul-publication-{token[:8]}",
        )
        child_process.start()
        child_connection.close()
        child_connection = None
        ready = await asyncio.to_thread(parent_connection.poll, 45)
        assert ready, "child did not start the provider worker"
        message = parent_connection.recv()
        assert message.get("status") == "worker-started", message
        await consul_server.wait_for_committed_response(timeout=45)

        policy = consul_server.registered_target_policy()
        credential_resolver = _AcceptanceConsulCredentialResolver(
            consul_server.endpoint, consul_server.application_token
        )
        source_connection = await credential_resolver.resolve_credentials(
            "acceptance-source",
            "source-revision-1",
            ConfigurationSourceProvider.CONSUL,
        )
        consul_reader = ConsulRuleSourceReader(policy, consul_server.http_client())
        before_kill = await consul_reader.read(source_connection, key)
        version = await ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)).execute(
            binding_id, version_id
        )
        expected_bytes = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            version
        )
        assert before_kill.value == expected_bytes
        async with engine.connect() as connection:
            publication = (
                (
                    await connection.execute(
                        select(RulePublicationRecord.__table__).where(
                            RulePublicationRecord.binding_id == binding_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            operation = (
                (
                    await connection.execute(
                        select(RuleMutationOperationRecord.__table__).where(
                            RuleMutationOperationRecord.request_key == request_key
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
        consul_server.release_dropped_response()
        await consul_server.wait_for_dropped_response(timeout=10)

        write_calls = 0
        original_write = ConsulRuleSourceWriter.write

        async def count_recovery_write(writer, command):
            nonlocal write_calls
            write_calls += 1
            return await original_write(writer, command)

        recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: _NOW + timedelta(seconds=62),
        )
        with patch.object(ConsulRuleSourceWriter, "write", count_recovery_write):
            recovered = await recovery_worker.run_once()
            assert await recovery_worker.run_once() == ()
        assert recovered == (RulePublicationWorkerOutcome.COMPLETED,)
        assert write_calls == 0
        after_recovery = await consul_reader.read(source_connection, key)
        assert after_recovery.value == expected_bytes
        assert after_recovery.modify_index == before_kill.modify_index

        completed = await store.read_operation(
            binding_id,
            request_key,
            actor_id=actor_id,
            session_digest=session_digest,
        )
        assert completed.status is RuleOperationStatus.COMPLETED
        assert completed.result.read_back.state.value == "succeeded"
        async with engine.connect() as connection:
            publications = (
                (
                    await connection.execute(
                        select(RulePublicationRecord.__table__).where(
                            RulePublicationRecord.binding_id == binding_id
                        )
                    )
                )
                .mappings()
                .all()
            )
            operations = (
                (
                    await connection.execute(
                        select(RuleMutationOperationRecord.__table__).where(
                            RuleMutationOperationRecord.request_key == request_key
                        )
                    )
                )
                .mappings()
                .all()
            )
            audit = (
                (
                    await connection.execute(
                        select(AuditEventRecord.__table__).where(
                            AuditEventRecord.actor_account_id == actor_id
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(publications) == 1
        assert publications[0]["write_state"] == "succeeded"
        assert publications[0]["read_back_state"] == "succeeded"
        assert len(operations) == 1 and operations[0]["status"] == "completed"
        assert len(audit) == 2
        assert {row["outcome"] for row in audit} == {"accepted", "completed"}
    finally:
        if child_process is not None and child_process.is_alive():
            child_process.terminate()
            await asyncio.to_thread(child_process.join, 10)
        if child_connection is not None:
            child_connection.close()
        if parent_connection is not None:
            parent_connection.close()
        try:
            if identity_seeded:
                await _cleanup_rows(
                    engine,
                    account_id=account_id,
                    session_digest=session_digest,
                    binding_id=binding_id,
                    version_id=version_id,
                    validation_id=validation_id,
                    request_key=request_key,
                )
        finally:
            if consul_server is not None:
                await consul_server.close()


async def assert_sql_outbox_publishes_to_disposable_consul(engine: AsyncEngine) -> None:
    """Exercise the real SQL outbox/worker with PostgreSQL or MySQL and Consul.

    The caller must supply an isolated ``sentinel_console_test_*`` database.
    The only external service this helper starts is a uniquely named disposable
    ACL-enabled Consul agent and its HTTPS test proxy, both removed in ``finally``.
    """
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    viewer_account_id = str(uuid4())
    actor_id = account_id
    binding_id = f"binding-{token}"
    version_id = f"version-{token}"
    validation_id = f"validation-{token}"
    request_key = f"request-{token}"
    request_id = f"http-{token}"
    session_token = f"session-{token}"
    csrf_token = f"csrf-{token}"
    viewer_session_token = f"viewer-session-{token}"
    viewer_csrf_token = f"viewer-csrf-{token}"
    session_digest = _digest(session_token)
    csrf_digest = _digest(csrf_token)
    viewer_session_digest = _digest(viewer_session_token)
    viewer_csrf_digest = _digest(viewer_csrf_token)
    username = f"consul-acceptance-{token}"
    viewer_username = f"consul-viewer-{token}"
    username_key = _digest(username)
    consul_server: DisposableConsulAclServer | None = None
    identity_seeded = False
    viewer_identity_seeded = False
    source_seeded = False
    source_id = "acceptance-source"
    try:
        await upgrade_database(engine)
        await _seed_identity(
            engine,
            account_id=account_id,
            username=username,
            username_key=username_key,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
        )
        identity_seeded = True
        await _seed_identity(
            engine,
            account_id=viewer_account_id,
            username=viewer_username,
            username_key=_digest(viewer_username),
            session_digest=viewer_session_digest,
            csrf_digest=viewer_csrf_digest,
            role_id="view",
        )
        viewer_identity_seeded = True
        candidate = _candidate(binding_id)
        checksum = candidate_checksum(candidate)
        await _seed_version(
            engine,
            account_id=account_id,
            binding_id=binding_id,
            version_id=version_id,
            validation_id=validation_id,
            candidate=candidate,
            checksum=checksum,
        )

        key = f"sentinel/acceptance/{token}/rules.json"
        consul_server = DisposableConsulAclServer(key)
        await consul_server.start()
        endpoint = consul_server.endpoint
        target_reader = _AcceptancePublicationTargetReader(key)
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_AcceptanceBindingReader(),
            publication_target_reader=target_reader,
            publication_payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
        )
        app = build_app(
            bootstrap_initialization_reader=_AcceptanceInitialized(),
            setup_window_reader=_AcceptanceSetupWindow(),
            bootstrap_operator_verifier=_AcceptanceOperatorVerifier(),
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
                "expectedChecksum": "sha256:baseline",
                "expectedSourceRevision": "target-revision-1",
                "reason": "synthetic acceptance reason",
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
                    "x-request-id": f"invalid-origin-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert invalid_origin.status_code == 403
            mismatch = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"mismatched-idempotency-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": f"different-{request_key}",
                },
            )
            assert mismatch.status_code == 409
            invalid_csrf = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"invalid-csrf-{token}",
                    "x-sentinel-csrf": f"wrong-{csrf_token}",
                    "idempotency-key": request_key,
                },
            )
            assert invalid_csrf.status_code == 403
            client.cookies.set("sentinel_session", viewer_session_token)
            client.cookies.set("__Host-sentinel_csrf", viewer_csrf_token)
            viewer_denied = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"viewer-denied-{token}",
                    "x-sentinel-csrf": viewer_csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert viewer_denied.status_code == 403
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        select(func.count())
                        .select_from(RuleMutationOperationRecord)
                        .where(RuleMutationOperationRecord.request_key == request_key)
                    )
                    == 0
                )
            assert consul_server.observed_requests == []

            client.cookies.set("sentinel_session", session_token)
            client.cookies.set("__Host-sentinel_csrf", csrf_token)
            accepted = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": request_id,
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["status"] == "pending"
            assert accepted.json()["requestKey"] == request_key
            assert "synthetic acceptance reason" not in accepted.text
            retry = await client.post(
                command_url,
                json=command_payload,
                headers={
                    "origin": "https://console.test",
                    "x-request-id": f"retry-{token}",
                    "x-sentinel-csrf": csrf_token,
                    "idempotency-key": request_key,
                },
            )
            assert retry.status_code == 202
            assert retry.json() == accepted.json()

            pending_receipt = await client.get(
                f"/api/v1/rulesets/{binding_id}/operations/{request_key}",
                headers={"x-request-id": f"pending-read-{token}"},
            )
            assert pending_receipt.status_code == 200
            assert pending_receipt.json()["status"] == "pending"

        policy = consul_server.registered_target_policy()
        source_reference = f"secret://consul/{token}"
        source_revision = "source-revision-1"
        source_cipher = AesGcmSecretCipher(
            "consul-source-v1",
            {"consul-source-v1": b"consul-source-secret-key-acceptance-0001"[:32]},
        )
        source_input = SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint=endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
            credential_reference=source_reference,
        )
        encrypted_source_credentials = encrypt_registered_source_credentials(
            source_input,
            source_id,
            source_cipher,
        )
        assert encrypted_source_credentials is not None
        async with engine.begin() as connection:
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=source_id,
                    revision=source_revision,
                    name="Disposable Consul credential-reference acceptance",
                    endpoint=endpoint,
                    provider=ConfigurationSourceProvider.CONSUL.value,
                    location="dc1",
                    authentication_mode=SourceAuthenticationMode.CREDENTIAL_REFERENCE.value,
                    credential_configured=True,
                    credential_cipher_format=encrypted_source_credentials.format.value,
                    credential_key_id=encrypted_source_credentials.key_id,
                    credential_payload=encrypted_source_credentials.payload,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id=account_id,
                )
            )
        source_seeded = True
        async with engine.connect() as connection:
            stored_source = (
                (
                    await connection.execute(
                        select(RegisteredConfigurationSourceRecord.__table__).where(
                            RegisteredConfigurationSourceRecord.source_id == source_id
                        )
                    )
                )
                .mappings()
                .one()
            )
        assert source_reference.encode() not in stored_source["credential_payload"]
        assert (
            consul_server.application_token.encode()
            not in stored_source["credential_payload"]
        )
        credential_resolver = SqlAlchemyRegisteredSourceStore(
            engine,
            secret_cipher=source_cipher,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
        )
        reference_resolver = _AcceptanceSourceReferenceResolver(
            source_reference,
            consul_server.application_token,
        )
        worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: _NOW,
        )
        consul_reader = ConsulRuleSourceReader(policy, consul_server.http_client())
        consul_server.arm_cas_drop_before_upstream(key)
        write_attempts = 0
        original_write = ConsulRuleSourceWriter.write

        async def count_write_attempt(writer, command):
            nonlocal write_attempts
            write_attempts += 1
            return await original_write(writer, command)

        with patch.object(ConsulRuleSourceWriter, "write", count_write_attempt):
            first_attempt = await worker.run_once()
        await consul_server.wait_for_pre_upstream_cas_drop(timeout=10)
        assert first_attempt == (RulePublicationWorkerOutcome.UNKNOWN,)
        absent_after_drop = await consul_reader.read(
            await ResolveRegisteredSourceConnection(
                credential_resolver,
                reference_resolver,
            ).execute(source_id, source_revision, ConfigurationSourceProvider.CONSUL),
            key,
        )
        assert not absent_after_drop.exists
        async with engine.connect() as connection:
            publication_id = await connection.scalar(
                select(RulePublicationRecord.publication_id).where(
                    RulePublicationRecord.binding_id == binding_id
                )
            )
        assert publication_id is not None
        unknown = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, publication_id)
        assert unknown.configuration_write.state.value == "unknown"
        pending_after_drop = await store.read_operation(
            binding_id, request_key, actor_id=actor_id, session_digest=session_digest
        )
        assert pending_after_drop.status is RuleOperationStatus.PENDING

        recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: _NOW + timedelta(seconds=62),
        )
        with patch.object(ConsulRuleSourceWriter, "write", count_write_attempt):
            recovered = await recovery_worker.run_once()
            assert await recovery_worker.run_once() == ()
        assert recovered == (RulePublicationWorkerOutcome.COMPLETED,)
        assert write_attempts == 2

        unresolved_connection = await credential_resolver.resolve_credentials(
            source_id, source_revision, ConfigurationSourceProvider.CONSUL
        )
        assert unresolved_connection is not None
        assert (
            unresolved_connection.authentication_mode
            is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE
        )
        assert unresolved_connection.credential_reference == source_reference
        assert unresolved_connection.acl_token is None
        resolved_connection = await ResolveRegisteredSourceConnection(
            credential_resolver,
            reference_resolver,
        ).execute(source_id, source_revision, ConfigurationSourceProvider.CONSUL)
        assert resolved_connection.acl_token == consul_server.application_token
        assert source_reference not in repr(resolved_connection)
        assert consul_server.application_token not in repr(resolved_connection)
        assert reference_resolver.references
        assert all(
            observed == (ConfigurationSourceProvider.CONSUL, source_reference)
            for observed in reference_resolver.references
        )
        stored = await consul_reader.read(resolved_connection, key)
        provider_requests = consul_server.observed_requests
        assert len(provider_requests) >= 2
        assert all(
            request_token == consul_server.application_token
            for _, request_token in provider_requests
        )
        assert all(
            consul_server.application_token not in request_path
            for request_path, _ in provider_requests
        )
        version = await ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)).execute(
            binding_id, version_id
        )
        assert stored.value == SentinelRuleVersionJsonEncoder(
            _PROFILE
        ).encode_rule_version(version)
        assert stored.modify_index is not None
        completed = await store.read_operation(
            binding_id, request_key, actor_id=actor_id, session_digest=session_digest
        )
        assert completed.status is RuleOperationStatus.COMPLETED
        assert completed.result.read_back.state.value == "succeeded"
        assert "synthetic acceptance reason" not in repr(completed)
        assert await worker.run_once() == ()
        assert (await consul_reader.read(resolved_connection, key)).modify_index == (
            stored.modify_index
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            client.cookies.set("sentinel_session", session_token)
            completed_receipt = await client.get(
                f"/api/v1/rulesets/{binding_id}/operations/{request_key}",
                headers={"x-request-id": f"completed-read-{token}"},
            )
        assert completed_receipt.status_code == 200
        assert completed_receipt.json()["status"] == "completed"
        assert completed_receipt.json()["requestKey"] == request_key
        assert completed_receipt.json()["result"]["kind"] == "publish"
        assert "synthetic acceptance reason" not in completed_receipt.text
    finally:
        try:
            if viewer_identity_seeded:
                async with engine.begin() as connection:
                    await connection.execute(
                        delete(AuthenticationSessionRecord).where(
                            AuthenticationSessionRecord.session_hash
                            == viewer_session_digest
                        )
                    )
                    await connection.execute(
                        delete(AccountRecord).where(
                            AccountRecord.account_id == viewer_account_id
                        )
                    )
            if identity_seeded:
                await _cleanup_rows(
                    engine,
                    account_id=account_id,
                    session_digest=session_digest,
                    binding_id=binding_id,
                    version_id=version_id,
                    validation_id=validation_id,
                    request_key=request_key,
                    source_id=source_id if source_seeded else None,
                )
        finally:
            if consul_server is not None:
                await consul_server.close()


async def assert_sql_activation_plan_publishes_and_restores_to_disposable_consul(
    engine: AsyncEngine,
) -> None:
    """Exercise scheduled activation and restoration through real Consul KV."""
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"consul-plan-binding-{token}"
    baseline_version_id = f"consul-plan-baseline-{token}"
    activation_version_id = f"consul-plan-activation-{token}"
    baseline_validation_id = f"consul-plan-baseline-validation-{token}"
    activation_validation_id = f"consul-plan-activation-validation-{token}"
    plan_request_key = f"consul-plan-request-{token}"
    conditional_replay_race_plan_request_key = (
        f"consul-conditional-replay-race-plan-{token}"
    )
    external_race_plan_request_key = f"consul-external-race-plan-{token}"
    restore_race_plan_request_key = f"consul-restore-race-plan-{token}"
    process_kill_plan_request_key = f"consul-process-kill-plan-{token}"
    unknown_conflict_plan_request_key = f"consul-unknown-conflict-plan-{token}"
    session_digest = _digest(f"consul-plan-session-{token}")
    csrf_digest = _digest(f"consul-plan-csrf-{token}")
    username = f"consul-plan-{token}"
    source_id = "acceptance-source"
    source_revision = "source-revision-1"
    source_reference = f"secret://consul/activation-plan/{token}"
    key = f"sentinel/acceptance/{token}/scheduled-rules.json"
    activation_at = _NOW + timedelta(seconds=10)
    restoration_at = _NOW + timedelta(seconds=200)
    consul_server: DisposableConsulAclServer | None = None
    rows_seeded = False
    source_seeded = False
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
        encrypted_source_credentials = encrypt_registered_source_credentials(
            source_input,
            source_id,
            source_cipher,
        )
        assert encrypted_source_credentials is not None
        async with engine.begin() as connection:
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(
                    source_id=source_id,
                    revision=source_revision,
                    name="Disposable Consul scheduled credential-reference acceptance",
                    endpoint=consul_server.endpoint,
                    provider=ConfigurationSourceProvider.CONSUL.value,
                    location="dc1",
                    authentication_mode=SourceAuthenticationMode.CREDENTIAL_REFERENCE.value,
                    credential_configured=True,
                    credential_cipher_format=encrypted_source_credentials.format.value,
                    credential_key_id=encrypted_source_credentials.key_id,
                    credential_payload=encrypted_source_credentials.payload,
                    created_at=_NOW,
                    updated_at=_NOW,
                    updated_by_account_id=account_id,
                )
            )
        source_seeded = True
        credential_resolver = SqlAlchemyRegisteredSourceStore(
            engine,
            secret_cipher=source_cipher,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
        )
        reference_resolver = _AcceptanceSourceReferenceResolver(
            source_reference,
            consul_server.application_token,
        )
        unresolved_source_connection = await credential_resolver.resolve_credentials(
            source_id, source_revision, ConfigurationSourceProvider.CONSUL
        )
        assert unresolved_source_connection is not None
        assert unresolved_source_connection.credential_reference == source_reference
        assert unresolved_source_connection.acl_token is None
        source_connection = await ResolveRegisteredSourceConnection(
            credential_resolver,
            reference_resolver,
        ).execute(source_id, source_revision, ConfigurationSourceProvider.CONSUL)
        assert source_connection.acl_token == consul_server.application_token
        assert source_reference not in repr(source_connection)
        assert consul_server.application_token not in repr(source_connection)
        policy = consul_server.registered_target_policy()
        reader = ConsulRuleSourceReader(policy, consul_server.http_client())
        baseline = await ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)).execute(
            binding_id, baseline_version_id
        )
        baseline_bytes = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            baseline
        )
        consul_server.write_management_value(key, baseline_bytes)
        baseline_snapshot = await reader.read(source_connection, key)

        async def publish_after_committed_response_is_dropped(
            worker,
            expected_bytes,
            publication_id,
        ):
            cas_put_count_before = sum(
                request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
                for request_path, _request_token in consul_server.observed_requests
            )
            consul_server.arm_response_drop_after_commit(key)
            worker_task = asyncio.create_task(worker.run_once())
            try:
                await consul_server.wait_for_committed_response(timeout=15)
                committed_snapshot = await reader.read(source_connection, key)
                assert committed_snapshot.value == expected_bytes
            finally:
                consul_server.release_dropped_response()
                await consul_server.wait_for_dropped_response(timeout=15)
            cas_put_count_after = sum(
                request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
                for request_path, _request_token in consul_server.observed_requests
            )
            assert cas_put_count_after == cas_put_count_before + 1
            outcome = await asyncio.wait_for(worker_task, timeout=15)
            publication_state = await ReadRulePublication(
                SqlAlchemyRulePublicationReader(engine)
            ).execute(binding_id, publication_id)
            cas_put_paths = [
                request_path
                for request_path, _request_token in consul_server.observed_requests
                if request_path.startswith("/v1/kv/") and "cas=" in request_path
            ]
            assert outcome == (RulePublicationWorkerOutcome.UNKNOWN,), (
                f"{outcome!r}; write={publication_state.configuration_write!r}; "
                f"read_back={publication_state.read_back!r}; cas_puts={cas_put_paths!r}"
            )
            return committed_snapshot

        async def publish_before_consul_dispatch_is_dropped(
            worker,
            expected_baseline_bytes,
            publication_id,
            plan_creation_request_key=plan_request_key,
        ):
            cas_put_count_before = sum(
                request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
                for request_path, _request_token in consul_server.observed_requests
            )
            consul_server.arm_cas_drop_before_upstream(key)
            outcome = await worker.run_once()
            await consul_server.wait_for_pre_upstream_cas_drop(timeout=10)
            cas_put_count_after = sum(
                request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
                for request_path, _request_token in consul_server.observed_requests
            )
            assert cas_put_count_after == cas_put_count_before + 1
            unchanged_snapshot = await reader.read(source_connection, key)
            assert unchanged_snapshot.value == expected_baseline_bytes
            publication_state = await ReadRulePublication(
                SqlAlchemyRulePublicationReader(engine)
            ).execute(binding_id, publication_id)
            assert outcome == (RulePublicationWorkerOutcome.UNKNOWN,), (
                f"{outcome!r}; write={publication_state.configuration_write!r}; "
                f"read_back={publication_state.read_back!r}"
            )
            assert publication_state.configuration_write.state.value == "unknown"
            assert publication_state.read_back.state.value == "awaiting"
            plan_creation_operation = await store.read_operation(
                binding_id,
                plan_creation_request_key,
                actor_id=account_id,
                session_digest=session_digest,
            )
            assert plan_creation_operation is not None
            assert plan_creation_operation.status is RuleOperationStatus.COMPLETED
            return unchanged_snapshot

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
                    activation_at,
                    restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-plan-http-{token}",
            now=_NOW,
        )
        assert created.status is RuleOperationStatus.COMPLETED
        plan_id = created.result.id
        queue = SqlAlchemyRuleActivationPlanWorkQueue(engine)
        scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: activation_at + timedelta(milliseconds=1),
        )
        assert await scheduler.run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        activation_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert activation_plan.items[0].state.value == "activating"
        activation_publication_id = activation_plan.items[0].activation_publication_id
        assert isinstance(activation_publication_id, str)

        provider_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: activation_at + timedelta(seconds=1),
        )
        original_consul_write = ConsulRuleSourceWriter.write
        activation_version = await ReadRuleVersion(
            SqlAlchemyRuleVersionReader(engine)
        ).execute(binding_id, activation_version_id)
        activation_bytes = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            activation_version
        )
        unchanged_before_activation = await publish_before_consul_dispatch_is_dropped(
            provider_worker,
            baseline_bytes,
            activation_publication_id,
        )
        assert unchanged_before_activation.value == baseline_bytes
        assert (
            unchanged_before_activation.modify_index == baseline_snapshot.modify_index
        )
        activation_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, activation_publication_id)
        assert activation_publication.configuration_write.state.value == "unknown"
        assert activation_publication.read_back.state.value == "awaiting"

        # Recovery reuses the scheduled publication. Consul's explicit strong
        # read proves the original baseline is still current, so recovery may
        # issue exactly one CAS fenced by that observed ModifyIndex.
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: activation_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        activation_recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: activation_at + timedelta(seconds=63),
        )
        activation_recovery_write_attempts = 0

        async def count_activation_recovery_writes(writer, command):
            nonlocal activation_recovery_write_attempts
            activation_recovery_write_attempts += 1
            return await original_consul_write(writer, command)

        # The recovery CAS itself commits, but its ACK is lost. The publication
        # must remain unknown and the scheduled plan must not become active yet.
        with patch.object(
            ConsulRuleSourceWriter,
            "write",
            new=count_activation_recovery_writes,
        ):
            recovered_commit = await publish_after_committed_response_is_dropped(
                activation_recovery_worker,
                activation_bytes,
                activation_publication_id,
            )
        assert activation_recovery_write_attempts == 1
        activation_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, activation_publication_id)
        assert activation_publication.configuration_write.state.value == "unknown"
        assert activation_publication.read_back.state.value == "awaiting"
        plan_after_lost_recovery_ack = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert plan_after_lost_recovery_ack.items[0].state.value == "activating"
        assert recovered_commit.value == activation_bytes

        # A later lease owner must use a strong exact read to recognize the
        # already committed candidate; it must not issue a third CAS.
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: activation_at + timedelta(seconds=124),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        requests_before_final_recovery = len(consul_server.observed_requests)
        cas_puts_before_final_recovery = sum(
            request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
            for request_path, _request_token in consul_server.observed_requests
        )
        activation_final_recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: activation_at + timedelta(seconds=125),
        )
        with patch.object(
            ConsulRuleSourceWriter,
            "write",
            new=count_activation_recovery_writes,
        ):
            assert await activation_final_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert activation_recovery_write_attempts == 1
        final_recovery_requests = consul_server.observed_requests[
            requests_before_final_recovery:
        ]
        assert any(
            path.startswith(f"/v1/kv/{quote(key, safe='/')}?")
            and parse_qs(urlsplit(path).query).get("consistent") == ["true"]
            and "cas=" not in path
            for path, _request_token in final_recovery_requests
        )
        cas_puts_after_final_recovery = sum(
            request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
            for request_path, _request_token in consul_server.observed_requests
        )
        assert cas_puts_after_final_recovery == cas_puts_before_final_recovery
        activated_snapshot = await reader.read(source_connection, key)
        assert activated_snapshot.value == activation_bytes
        assert activated_snapshot.modify_index != baseline_snapshot.modify_index
        assert reference_resolver.references
        activation_reference_resolution_count = len(reference_resolver.references)
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: activation_at + timedelta(seconds=186),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        active_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert active_plan.items[0].state.value == "active"

        restoration_scheduler = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restoration_at + timedelta(milliseconds=1),
        )
        assert await restoration_scheduler.run_once() == (
            RuleActivationPlanWorkerOutcome.ENQUEUED,
        )
        restoring_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        restoration_publication_id = restoring_plan.items[0].restore_publication_id
        assert isinstance(restoration_publication_id, str)
        restoration_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: restoration_at + timedelta(seconds=1),
        )
        unchanged_before_restoration = await publish_before_consul_dispatch_is_dropped(
            restoration_worker,
            activation_bytes,
            restoration_publication_id,
        )
        assert unchanged_before_restoration.value == activation_bytes
        assert (
            unchanged_before_restoration.modify_index == activated_snapshot.modify_index
        )
        restoration_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restoration_publication_id)
        assert restoration_publication.configuration_write.state.value == "unknown"
        assert restoration_publication.read_back.state.value == "awaiting"
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restoration_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        restoration_recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: restoration_at + timedelta(seconds=63),
        )
        restoration_recovery_write_attempts = 0

        async def count_restoration_recovery_writes(writer, command):
            nonlocal restoration_recovery_write_attempts
            restoration_recovery_write_attempts += 1
            return await original_consul_write(writer, command)

        # The recovery CAS itself commits the immutable restore baseline, but
        # its ACK is lost. The plan must remain restoring until another lease
        # owner confirms the value through an exact strong read.
        with patch.object(
            ConsulRuleSourceWriter,
            "write",
            new=count_restoration_recovery_writes,
        ):
            recovered_restoration_commit = (
                await publish_after_committed_response_is_dropped(
                    restoration_recovery_worker,
                    baseline_bytes,
                    restoration_publication_id,
                )
            )
        assert restoration_recovery_write_attempts == 1
        restoration_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restoration_publication_id)
        assert restoration_publication.configuration_write.state.value == "unknown"
        assert restoration_publication.read_back.state.value == "awaiting"
        plan_after_lost_restoration_ack = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert plan_after_lost_restoration_ack.items[0].state.value == "restoring"
        assert recovered_restoration_commit.value == baseline_bytes

        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restoration_at + timedelta(seconds=124),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        requests_before_final_restoration_recovery = len(
            consul_server.observed_requests
        )
        cas_puts_before_final_restoration_recovery = sum(
            request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
            for request_path, _request_token in consul_server.observed_requests
        )
        restoration_final_recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: restoration_at + timedelta(seconds=125),
        )
        with patch.object(
            ConsulRuleSourceWriter,
            "write",
            new=count_restoration_recovery_writes,
        ):
            assert await restoration_final_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert restoration_recovery_write_attempts == 1
        final_restoration_recovery_requests = consul_server.observed_requests[
            requests_before_final_restoration_recovery:
        ]
        assert any(
            path.startswith(f"/v1/kv/{quote(key, safe='/')}?")
            and parse_qs(urlsplit(path).query).get("consistent") == ["true"]
            and "cas=" not in path
            for path, _request_token in final_restoration_recovery_requests
        )
        cas_puts_after_final_restoration_recovery = sum(
            request_path.startswith(f"/v1/kv/{key}?") and "cas=" in request_path
            for request_path, _request_token in consul_server.observed_requests
        )
        assert (
            cas_puts_after_final_restoration_recovery
            == cas_puts_before_final_restoration_recovery
        )
        restored_snapshot = await reader.read(source_connection, key)
        assert restored_snapshot.value == baseline_bytes
        assert restored_snapshot.modify_index != activated_snapshot.modify_index
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restoration_at + timedelta(seconds=186),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)

        # A conditional replay is safe only while the exact baseline observed
        # by the strong recovery read remains current. Race an independent
        # management writer after that read but before the recovery CAS reaches
        # Consul, then prove Consul rejects the stale revision and the plan is
        # blocked without replacing the external bytes.
        replay_race_activation_at = _NOW + timedelta(seconds=330)
        replay_race_restoration_at = _NOW + timedelta(seconds=430)
        replay_race_plan = await store.mutate(
            RuleMutationCommand(
                binding_id,
                conditional_replay_race_plan_request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    replay_race_activation_at,
                    replay_race_restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-replay-race-http-{token}",
            now=_NOW + timedelta(seconds=210),
        )
        assert replay_race_plan.status is RuleOperationStatus.COMPLETED
        replay_race_plan_id = replay_race_plan.result.id
        replay_external_payload = json.loads(baseline_bytes)
        assert isinstance(replay_external_payload, list) and replay_external_payload
        assert isinstance(replay_external_payload[0], dict)
        replay_external_payload[0]["count"] = 97
        replay_race_external_bytes = json.dumps(
            replay_external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        assert replay_race_external_bytes not in {baseline_bytes, activation_bytes}
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: replay_race_activation_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        replay_race_plan_snapshot = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        replay_race_plan_item = next(
            item
            for item in replay_race_plan_snapshot.items
            if item.id == replay_race_plan_id
        )
        replay_race_publication_id = replay_race_plan_item.activation_publication_id
        assert isinstance(replay_race_publication_id, str)
        replay_race_initial_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: replay_race_activation_at + timedelta(seconds=1),
        )
        replay_race_baseline = await reader.read(source_connection, key)
        assert replay_race_baseline.value == baseline_bytes
        replay_race_after_drop = await publish_before_consul_dispatch_is_dropped(
            replay_race_initial_worker,
            baseline_bytes,
            replay_race_publication_id,
            conditional_replay_race_plan_request_key,
        )
        assert replay_race_after_drop.modify_index == replay_race_baseline.modify_index
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: replay_race_activation_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        replay_race_recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=reference_resolver,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: replay_race_activation_at + timedelta(seconds=63),
        )
        consul_server.arm_hold_cas_before_upstream(key)
        replay_race_recovery_task = asyncio.create_task(
            replay_race_recovery_worker.run_once()
        )
        replay_race_external_writer = multiprocessing.get_context("spawn").Process(
            target=_write_consul_value_from_external_process,
            args=(
                consul_server.port,
                consul_server.management_token,
                key,
                replay_race_external_bytes,
            ),
        )
        try:
            await consul_server.wait_for_held_cas(timeout=20)
            recovery_requests = list(consul_server.observed_requests)
            strong_read_indexes = [
                index
                for index, (path, _) in enumerate(recovery_requests)
                if path.startswith(f"/v1/kv/{quote(key, safe='/')}?")
                and "cas=" not in path
                and parse_qs(urlsplit(path).query).get("consistent") == ["true"]
            ]
            if not strong_read_indexes:
                raise AssertionError(
                    "conditional recovery did not precede its CAS with a strong read"
                )
            held_cas_indexes = [
                index
                for index, (path, _) in enumerate(recovery_requests)
                if path.startswith(f"/v1/kv/{quote(key, safe='/')}?") and "cas=" in path
            ]
            if not held_cas_indexes:
                raise AssertionError("conditional recovery CAS was not observed")
            latest_strong_read = max(strong_read_indexes)
            latest_held_cas = max(held_cas_indexes)
            held_cas_query = parse_qs(
                urlsplit(recovery_requests[latest_held_cas][0]).query
            )
            if latest_strong_read >= latest_held_cas:
                raise AssertionError(
                    "the recovery CAS was not preceded by its strong read"
                )
            if held_cas_query.get("cas") != [replay_race_baseline.modify_index]:
                raise AssertionError(
                    "conditional recovery CAS did not use its strongly-read baseline"
                )

            replay_race_external_writer.start()
            await asyncio.to_thread(replay_race_external_writer.join, 15)
            if replay_race_external_writer.is_alive():
                raise AssertionError(
                    "external Consul recovery-race writer did not finish"
                )
            if replay_race_external_writer.exitcode != 0:
                raise AssertionError("external Consul recovery-race writer failed")
            replay_race_external_snapshot = await reader.read(source_connection, key)
            assert replay_race_external_snapshot.value == replay_race_external_bytes
            assert (
                replay_race_external_snapshot.modify_index
                != replay_race_baseline.modify_index
            )
            consul_server.release_held_cas()
            replay_race_recovery_outcome = await asyncio.wait_for(
                replay_race_recovery_task, timeout=20
            )
            assert replay_race_recovery_outcome == (
                RulePublicationWorkerOutcome.REJECTED,
            ), replay_race_recovery_outcome
        finally:
            consul_server.release_held_cas()
            if not replay_race_recovery_task.done():
                replay_race_recovery_task.cancel()
            await asyncio.gather(replay_race_recovery_task, return_exceptions=True)
            if (
                replay_race_external_writer.pid is not None
                and replay_race_external_writer.is_alive()
            ):
                replay_race_external_writer.terminate()
                await asyncio.to_thread(replay_race_external_writer.join, 5)

        replay_race_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, replay_race_publication_id)
        assert replay_race_publication.configuration_write.state.value == "failed"
        assert replay_race_publication.configuration_write.reason.value == "conflict"
        replay_race_plan_outcome = await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: replay_race_activation_at + timedelta(seconds=124),
        ).run_once()
        assert replay_race_plan_outcome == (RuleActivationPlanWorkerOutcome.BLOCKED,), (
            replay_race_plan_outcome
        )
        replay_race_blocked_plans = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        replay_race_blocked_item = next(
            item
            for item in replay_race_blocked_plans.items
            if item.id == replay_race_plan_id
        )
        assert replay_race_blocked_item.state.value == "blocked"
        assert replay_race_blocked_item.restore_publication_id is None
        assert await replay_race_recovery_worker.run_once() == ()
        assert (
            await reader.read(source_connection, key) == replay_race_external_snapshot
        )

        # Restore the immutable daily snapshot and use its fresh revision for
        # the following independent external-writer race.
        consul_server.write_management_value(key, baseline_bytes)
        external_race_baseline_snapshot = await reader.read(source_connection, key)
        assert external_race_baseline_snapshot.value == baseline_bytes
        assert (
            len(reference_resolver.references) > activation_reference_resolution_count
        )
        assert all(
            provider is ConfigurationSourceProvider.CONSUL
            and reference == source_reference
            for provider, reference in reference_resolver.references
        )
        assert (
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=store,
                clock=lambda: restoration_at + timedelta(seconds=124),
            ).run_once()
            == ()
        )

        completed_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        assert completed_plan.items[0].state.value == "completed"

        # A separate non-overlapping scheduled activation races a real
        # management-plane edit between the worker's baseline read and CAS.
        external_race_activation_at = _NOW + timedelta(seconds=500)
        external_race_restoration_at = _NOW + timedelta(seconds=600)
        external_race_plan = await store.mutate(
            RuleMutationCommand(
                binding_id,
                external_race_plan_request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    external_race_activation_at,
                    external_race_restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-external-race-http-{token}",
            now=_NOW + timedelta(seconds=455),
        )
        assert external_race_plan.status is RuleOperationStatus.COMPLETED
        external_race_plan_id = external_race_plan.result.id
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: external_race_activation_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)

        external_payload = json.loads(baseline_bytes)
        assert isinstance(external_payload, list) and external_payload
        assert isinstance(external_payload[0], dict)
        assert external_payload[0].get("count") != 97
        external_payload[0]["count"] = 97
        external_bytes = json.dumps(
            external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        assert external_bytes != baseline_bytes
        assert external_bytes != activation_bytes

        external_race_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=_AcceptanceConsulCredentialResolver(
                consul_server.endpoint, consul_server.application_token
            ),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: external_race_activation_at + timedelta(seconds=1),
        )
        external_snapshot = await _assert_cas_is_rejected_after_external_process_write(
            worker=external_race_worker,
            consul_server=consul_server,
            reader=reader,
            source_connection=source_connection,
            key=key,
            expected_snapshot=external_race_baseline_snapshot,
            external_value=external_bytes,
        )
        assert external_snapshot.value == external_bytes
        assert external_snapshot.modify_index != restored_snapshot.modify_index

        external_race_plan_outcome = await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: external_race_activation_at + timedelta(seconds=62),
        ).run_once()
        assert external_race_plan_outcome == (RuleActivationPlanWorkerOutcome.BLOCKED,)
        blocked_plans = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        blocked_plan = next(
            item for item in blocked_plans.items if item.id == external_race_plan_id
        )
        assert blocked_plan.state.value == "blocked"
        assert blocked_plan.restore_publication_id is None
        assert isinstance(blocked_plan.activation_publication_id, str)
        blocked_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, blocked_plan.activation_publication_id)
        assert blocked_publication.configuration_write.state.value == "failed"
        assert blocked_publication.configuration_write.reason.value == "conflict"
        assert (
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=store,
                clock=lambda: external_race_restoration_at + timedelta(seconds=1),
            ).run_once()
            == ()
        )
        assert await external_race_worker.run_once() == ()
        assert await reader.read(source_connection, key) == external_snapshot

        # Reset the disposable provider to a known baseline, then race an
        # external edit between the scheduled restoration preflight and CAS.
        restore_race_activation_at = _NOW + timedelta(seconds=700)
        restore_race_restoration_at = _NOW + timedelta(seconds=800)
        consul_server.write_management_value(key, baseline_bytes)
        restore_race_baseline = await reader.read(source_connection, key)
        assert restore_race_baseline.value == baseline_bytes
        restore_race_plan = await store.mutate(
            RuleMutationCommand(
                binding_id,
                restore_race_plan_request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    restore_race_activation_at,
                    restore_race_restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-restore-race-http-{token}",
            now=_NOW + timedelta(seconds=660),
        )
        assert restore_race_plan.status is RuleOperationStatus.COMPLETED
        restore_race_plan_id = restore_race_plan.result.id
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restore_race_activation_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        restore_race_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=_AcceptanceConsulCredentialResolver(
                consul_server.endpoint, consul_server.application_token
            ),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: restore_race_activation_at + timedelta(seconds=1),
        )
        assert await restore_race_worker.run_once() == (
            RulePublicationWorkerOutcome.COMPLETED,
        )
        restore_race_activated = await reader.read(source_connection, key)
        assert restore_race_activated.value == activation_bytes
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restore_race_activation_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        restore_race_active_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        restore_race_active_item = next(
            item
            for item in restore_race_active_plan.items
            if item.id == restore_race_plan_id
        )
        assert restore_race_active_item.state.value == "active"
        assert isinstance(restore_race_active_item.activation_publication_id, str)

        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restore_race_restoration_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        restore_race_restoring_plan = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        restore_race_restoring_item = next(
            item
            for item in restore_race_restoring_plan.items
            if item.id == restore_race_plan_id
        )
        assert restore_race_restoring_item.state.value == "restoring"
        assert isinstance(restore_race_restoring_item.restore_publication_id, str)

        restore_external_payload = json.loads(activation_bytes)
        assert isinstance(restore_external_payload, list)
        assert isinstance(restore_external_payload[0], dict)
        restore_external_payload[0]["count"] = 83
        restore_external_bytes = json.dumps(
            restore_external_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        assert restore_external_bytes not in {
            baseline_bytes,
            activation_bytes,
            external_bytes,
        }
        restore_external_snapshot = (
            await _assert_cas_is_rejected_after_external_process_write(
                worker=restore_race_worker,
                consul_server=consul_server,
                reader=reader,
                source_connection=source_connection,
                key=key,
                expected_snapshot=restore_race_activated,
                external_value=restore_external_bytes,
            )
        )
        assert restore_external_snapshot.value == restore_external_bytes
        assert (
            restore_external_snapshot.modify_index
            != restore_race_activated.modify_index
        )
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: restore_race_restoration_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.BLOCKED,)
        restore_race_blocked_plans = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        restore_race_blocked_item = next(
            item
            for item in restore_race_blocked_plans.items
            if item.id == restore_race_plan_id
        )
        assert restore_race_blocked_item.state.value == "blocked"
        assert restore_race_blocked_item.activation_publication_id == (
            restore_race_active_item.activation_publication_id
        )
        assert restore_race_blocked_item.restore_publication_id == (
            restore_race_restoring_item.restore_publication_id
        )
        restore_race_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, restore_race_blocked_item.restore_publication_id)
        assert restore_race_publication.configuration_write.state.value == "failed"
        assert restore_race_publication.configuration_write.reason.value == "conflict"
        assert (
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=store,
                clock=lambda: restore_race_restoration_at + timedelta(seconds=124),
            ).run_once()
            == ()
        )
        assert await restore_race_worker.run_once() == ()
        assert await reader.read(source_connection, key) == restore_external_snapshot

        # Reset to the immutable baseline and prove a real process can disappear
        # after Consul committed activation but before SQL records the receipt.
        consul_server.write_management_value(key, baseline_bytes)
        process_kill_baseline = await reader.read(source_connection, key)
        assert process_kill_baseline.value == baseline_bytes
        process_kill_activation_at = _NOW + timedelta(seconds=1000)
        process_kill_restoration_at = _NOW + timedelta(seconds=1200)
        process_kill_plan = await store.mutate(
            RuleMutationCommand(
                binding_id,
                process_kill_plan_request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    process_kill_activation_at,
                    process_kill_restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-process-kill-http-{token}",
            now=_NOW + timedelta(seconds=900),
        )
        assert process_kill_plan.status is RuleOperationStatus.COMPLETED
        process_kill_plan_id = process_kill_plan.result.id
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: process_kill_activation_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        process_kill_activating = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        process_kill_activating_item = next(
            item
            for item in process_kill_activating.items
            if item.id == process_kill_plan_id
        )
        process_kill_activation_publication_id = (
            process_kill_activating_item.activation_publication_id
        )
        assert isinstance(process_kill_activation_publication_id, str)
        consul_server.arm_response_drop_after_commit(key)
        await _run_consul_publication_worker_process_that_exits_after_provider_write(
            engine.url.render_as_string(hide_password=False),
            consul_server.endpoint,
            consul_server.application_token,
            consul_server.client_ca_pem,
            consul_server.proxy_port,
            process_kill_activation_at + timedelta(seconds=1),
            consul_server,
        )
        process_kill_activated = await reader.read(source_connection, key)
        assert process_kill_activated.value == activation_bytes
        assert process_kill_activated.modify_index != process_kill_baseline.modify_index
        process_kill_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, process_kill_activation_publication_id)
        assert process_kill_publication.configuration_write.state.value == "running"
        assert process_kill_publication.read_back.state.value == "awaiting"
        assert process_kill_activating_item.state.value == "activating"

        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: process_kill_activation_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        process_kill_recovery_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=_AcceptanceConsulCredentialResolver(
                consul_server.endpoint, consul_server.application_token
            ),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: process_kill_activation_at + timedelta(seconds=63),
        )
        process_kill_recovery_writes = 0

        async def count_process_kill_recovery_writes(writer, command):
            nonlocal process_kill_recovery_writes
            process_kill_recovery_writes += 1
            return await original_consul_write(writer, command)

        with patch.object(
            ConsulRuleSourceWriter,
            "write",
            new=count_process_kill_recovery_writes,
        ):
            assert await process_kill_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert process_kill_recovery_writes == 0
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: process_kill_activation_at + timedelta(seconds=124),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)

        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: process_kill_restoration_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        process_kill_restoring = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        process_kill_restoring_item = next(
            item
            for item in process_kill_restoring.items
            if item.id == process_kill_plan_id
        )
        process_kill_restoration_publication_id = (
            process_kill_restoring_item.restore_publication_id
        )
        assert isinstance(process_kill_restoration_publication_id, str)
        consul_server.arm_response_drop_after_commit(key)
        await _run_consul_publication_worker_process_that_exits_after_provider_write(
            engine.url.render_as_string(hide_password=False),
            consul_server.endpoint,
            consul_server.application_token,
            consul_server.client_ca_pem,
            consul_server.proxy_port,
            process_kill_restoration_at + timedelta(seconds=1),
            consul_server,
        )
        process_kill_restored = await reader.read(source_connection, key)
        assert process_kill_restored.value == baseline_bytes
        assert process_kill_restored.modify_index != process_kill_activated.modify_index
        process_kill_restoration_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, process_kill_restoration_publication_id)
        assert (
            process_kill_restoration_publication.configuration_write.state.value
            == "running"
        )
        assert (
            process_kill_restoration_publication.read_back.state.value == "awaiting"
        )
        process_kill_restoring = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        process_kill_restoring_item = next(
            item
            for item in process_kill_restoring.items
            if item.id == process_kill_plan_id
        )
        assert process_kill_restoring_item.state.value == "restoring"

        process_kill_restoration_recovery_worker = (
            create_consul_rule_publication_worker(
                engine,
                target_policy=policy,
                credential_resolver=_AcceptanceConsulCredentialResolver(
                    consul_server.endpoint, consul_server.application_token
                ),
                credential_reference_resolver=None,
                profile_id=_PROFILE,
                ssl_context=consul_server.client_ssl_context,
                clock=lambda: process_kill_restoration_at + timedelta(seconds=62),
            )
        )
        process_kill_restoration_recovery_writes = 0

        async def count_process_kill_restoration_recovery_writes(writer, command):
            nonlocal process_kill_restoration_recovery_writes
            process_kill_restoration_recovery_writes += 1
            return await original_consul_write(writer, command)

        with patch.object(
            ConsulRuleSourceWriter,
            "write",
            new=count_process_kill_restoration_recovery_writes,
        ):
            assert await process_kill_restoration_recovery_worker.run_once() == (
                RulePublicationWorkerOutcome.COMPLETED,
            )
        assert process_kill_restoration_recovery_writes == 0
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: process_kill_restoration_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.COMPLETED,)
        process_kill_completed = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        process_kill_completed_item = next(
            item
            for item in process_kill_completed.items
            if item.id == process_kill_plan_id
        )
        assert process_kill_completed_item.state.value == "completed"

        # An external write can make Consul reject the plan's baseline-fenced
        # CAS. If that negative response is lost, takeover must strongly read
        # the external value and block rather than replay the CAS.
        unknown_conflict_activation_at = _NOW + timedelta(seconds=1300)
        unknown_conflict_restoration_at = _NOW + timedelta(seconds=1500)
        unknown_conflict_plan = await store.mutate(
            RuleMutationCommand(
                binding_id,
                unknown_conflict_plan_request_key,
                CreateRuleActivationPlan(
                    activation_version_id,
                    baseline_version_id,
                    unknown_conflict_activation_at,
                    unknown_conflict_restoration_at,
                    "UTC",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"consul-unknown-conflict-http-{token}",
            now=_NOW + timedelta(seconds=1250),
        )
        assert unknown_conflict_plan.status is RuleOperationStatus.COMPLETED
        unknown_conflict_plan_id = unknown_conflict_plan.result.id
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: unknown_conflict_activation_at + timedelta(milliseconds=1),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        unknown_conflict_pending = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        unknown_conflict_item = next(
            item
            for item in unknown_conflict_pending.items
            if item.id == unknown_conflict_plan_id
        )
        unknown_conflict_publication_id = (
            unknown_conflict_item.activation_publication_id
        )
        assert isinstance(unknown_conflict_publication_id, str)
        unknown_payload = json.loads(baseline_bytes)
        assert isinstance(unknown_payload, list) and unknown_payload
        assert isinstance(unknown_payload[0], dict)
        unknown_payload[0]["count"] = 111
        unknown_external_bytes = json.dumps(
            unknown_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        unknown_conflict_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=_AcceptanceConsulCredentialResolver(
                consul_server.endpoint, consul_server.application_token
            ),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: unknown_conflict_activation_at + timedelta(seconds=1),
        )
        cas_count_before_unknown_conflict = sum(
            path.startswith(f"/v1/kv/{key}?") and "cas=" in path
            for path, _request_token in consul_server.observed_requests
        )
        consul_server.arm_hold_cas_before_upstream(key)
        consul_server.arm_drop_cas_conflict_response(key)
        unknown_conflict_task = asyncio.create_task(
            unknown_conflict_worker.run_once()
        )
        try:
            await consul_server.wait_for_held_cas(timeout=20)
            pre_conflict_snapshot = await reader.read(source_connection, key)
            assert pre_conflict_snapshot.value == baseline_bytes
            await asyncio.to_thread(
                consul_server.write_management_value,
                key,
                unknown_external_bytes,
            )
            external_unknown_snapshot = await reader.read(source_connection, key)
            assert external_unknown_snapshot.value == unknown_external_bytes
            assert (
                external_unknown_snapshot.modify_index
                != pre_conflict_snapshot.modify_index
            )
            consul_server.release_held_cas()
            await consul_server.wait_for_held_cas_conflict_response(timeout=15)
            consul_server.release_dropped_cas_conflict_response()
            await consul_server.wait_for_dropped_cas_conflict_response(timeout=15)
            assert await asyncio.wait_for(unknown_conflict_task, timeout=15) == (
                RulePublicationWorkerOutcome.UNKNOWN,
            )
        finally:
            consul_server.release_held_cas()
            consul_server.release_dropped_cas_conflict_response()
            if not unknown_conflict_task.done():
                unknown_conflict_task.cancel()
            await asyncio.gather(unknown_conflict_task, return_exceptions=True)

        unknown_conflict_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, unknown_conflict_publication_id)
        assert unknown_conflict_publication.configuration_write.state.value == "unknown"
        assert unknown_conflict_publication.read_back.state.value == "awaiting"
        assert (
            sum(
                path.startswith(f"/v1/kv/{key}?") and "cas=" in path
                for path, _request_token in consul_server.observed_requests
            )
            == cas_count_before_unknown_conflict + 1
        )
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: unknown_conflict_activation_at + timedelta(seconds=62),
        ).run_once() == (RuleActivationPlanWorkerOutcome.ENQUEUED,)
        cas_count_before_unknown_takeover = sum(
            path.startswith(f"/v1/kv/{key}?") and "cas=" in path
            for path, _request_token in consul_server.observed_requests
        )
        unknown_takeover_worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=_AcceptanceConsulCredentialResolver(
                consul_server.endpoint, consul_server.application_token
            ),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=consul_server.client_ssl_context,
            clock=lambda: unknown_conflict_activation_at + timedelta(seconds=63),
        )
        unknown_takeover_outcome = await unknown_takeover_worker.run_once()
        assert unknown_takeover_outcome == (
            RulePublicationWorkerOutcome.REJECTED,
        ), unknown_takeover_outcome
        assert (
            sum(
                path.startswith(f"/v1/kv/{key}?") and "cas=" in path
                for path, _request_token in consul_server.observed_requests
            )
            == cas_count_before_unknown_takeover
        )
        blocked_unknown_publication = await ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ).execute(binding_id, unknown_conflict_publication_id)
        assert blocked_unknown_publication.validation.state.value == "succeeded"
        assert blocked_unknown_publication.configuration_write.state.value == "failed"
        assert blocked_unknown_publication.configuration_write.reason.value == "conflict"
        assert await RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=store,
            clock=lambda: unknown_conflict_activation_at + timedelta(seconds=124),
        ).run_once() == (RuleActivationPlanWorkerOutcome.BLOCKED,)
        unknown_blocked_plans = await ReadRuleActivationPlans(
            SqlAlchemyRuleActivationPlanReader(engine)
        ).execute(binding_id)
        unknown_blocked_item = next(
            item
            for item in unknown_blocked_plans.items
            if item.id == unknown_conflict_plan_id
        )
        assert unknown_blocked_item.state.value == "blocked"
        assert unknown_blocked_item.activation_publication_id == (
            unknown_conflict_publication_id
        )
        assert unknown_blocked_item.restore_publication_id is None
        assert await unknown_takeover_worker.run_once() == ()
        assert await reader.read(source_connection, key) == external_unknown_snapshot

        async with engine.connect() as connection:
            phase_operations = (
                await connection.execute(
                    select(
                        RuleMutationOperationRecord.origin_phase,
                        RuleMutationOperationRecord.status,
                    )
                    .where(RuleMutationOperationRecord.origin_plan_id == plan_id)
                    .order_by(RuleMutationOperationRecord.origin_phase)
                )
            ).all()
            process_kill_phase_operations = (
                await connection.execute(
                    select(
                        RuleMutationOperationRecord.origin_phase,
                        RuleMutationOperationRecord.status,
                    )
                    .where(
                        RuleMutationOperationRecord.origin_plan_id
                        == process_kill_plan_id
                    )
                    .order_by(RuleMutationOperationRecord.origin_phase)
                )
            ).all()
            publication_ids = (
                (
                    await connection.execute(
                        select(RulePublicationRecord.publication_id).where(
                            RulePublicationRecord.binding_id == binding_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert phase_operations == [
            ("activation", "completed"),
            ("restoration", "completed"),
        ]
        assert process_kill_phase_operations == [
            ("activation", "completed"),
            ("restoration", "completed"),
        ]
        assert set(publication_ids) == {
            activation_publication_id,
            restoration_publication_id,
            replay_race_publication_id,
            blocked_plan.activation_publication_id,
            restore_race_active_item.activation_publication_id,
            restore_race_blocked_item.restore_publication_id,
            process_kill_activation_publication_id,
            process_kill_restoration_publication_id,
                        unknown_conflict_publication_id,
        }
        provider_requests = consul_server.observed_requests
        assert len(provider_requests) >= 8
        assert all(
            request_token == consul_server.application_token
            for _, request_token in provider_requests
        )
        assert all(
            consul_server.application_token not in request_path
            for request_path, _ in provider_requests
        )
        assert await restoration_recovery_worker.run_once() == ()
        assert (
            await RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=store,
                clock=lambda: restoration_at + timedelta(seconds=125),
            ).run_once()
            == ()
        )
        assert (await reader.read(source_connection, key)) == external_unknown_snapshot
    finally:
        try:
            if source_seeded:
                async with engine.begin() as connection:
                    await connection.execute(
                        delete(RegisteredConfigurationSourceRecord).where(
                            RegisteredConfigurationSourceRecord.source_id == source_id
                        )
                    )
            if rows_seeded:
                await _cleanup_activation_rows(
                    engine,
                    account_id=account_id,
                    session_digest=session_digest,
                    binding_id=binding_id,
                    plan_request_keys=(
                        plan_request_key,
                        conditional_replay_race_plan_request_key,
                        external_race_plan_request_key,
                        restore_race_plan_request_key,
                        process_kill_plan_request_key,
                        unknown_conflict_plan_request_key,
                    ),
                    version_ids=(baseline_version_id, activation_version_id),
                    validation_ids=(baseline_validation_id, activation_validation_id),
                )
        finally:
            if consul_server is not None:
                await consul_server.close()


async def _seed_identity(
    engine: AsyncEngine,
    *,
    account_id: str,
    username: str,
    username_key: str,
    session_digest: str,
    csrf_digest: str,
    role_id: str = "admin",
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(AccountRecord).values(
                account_id=account_id,
                username=username,
                username_key=username_key,
                password_hash="$argon2id$synthetic-acceptance-hash",
                role_id=role_id,
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


async def _seed_version(
    engine: AsyncEngine,
    *,
    account_id: str,
    binding_id: str,
    version_id: str,
    validation_id: str,
    candidate: RuleSetCandidate,
    checksum: str,
) -> None:
    async with engine.begin() as connection:
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
                name="SQL to Consul acceptance",
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


async def _cleanup_rows(
    engine: AsyncEngine,
    *,
    account_id: str,
    session_digest: str,
    binding_id: str,
    version_id: str,
    validation_id: str,
    request_key: str,
    source_id: str | None = None,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            delete(AuditEventRecord).where(
                AuditEventRecord.actor_account_id == account_id
            )
        )
        await connection.execute(
            delete(RulePublicationRecord).where(
                RulePublicationRecord.binding_id == binding_id
            )
        )
        await connection.execute(
            delete(RuleMutationOperationRecord).where(
                RuleMutationOperationRecord.request_key == request_key
            )
        )
        await connection.execute(
            delete(RuleSetVersionRecord).where(
                RuleSetVersionRecord.version_id == version_id
            )
        )
        await connection.execute(
            delete(RuleValidationReceiptRecord).where(
                RuleValidationReceiptRecord.validation_id == validation_id
            )
        )
        await connection.execute(
            delete(AuthenticationSessionRecord).where(
                AuthenticationSessionRecord.session_hash == session_digest
            )
        )
        if source_id is not None:
            await connection.execute(
                delete(RegisteredConfigurationSourceRecord).where(
                    RegisteredConfigurationSourceRecord.source_id == source_id
                )
            )
        await connection.execute(
            delete(AccountRecord).where(AccountRecord.account_id == account_id)
        )


async def _cleanup_activation_rows(
    engine: AsyncEngine,
    *,
    account_id: str,
    session_digest: str,
    binding_id: str,
    plan_request_keys: tuple[str, ...],
    version_ids: tuple[str, str],
    validation_ids: tuple[str, str],
) -> None:
    async with engine.begin() as connection:
        plan_ids = select(RuleActivationPlanRecord.plan_id).where(
            RuleActivationPlanRecord.binding_id == binding_id
        )
        await connection.execute(
            delete(AuditEventRecord).where(
                AuditEventRecord.actor_account_id == account_id
            )
        )
        await connection.execute(
            delete(RuleMutationOperationRecord).where(
                (RuleMutationOperationRecord.request_key.in_(plan_request_keys))
                | RuleMutationOperationRecord.origin_plan_id.in_(plan_ids)
            )
        )
        await connection.execute(
            delete(RulePublicationRecord).where(
                RulePublicationRecord.binding_id == binding_id
            )
        )
        await connection.execute(
            delete(RuleActivationPlanRecord).where(
                RuleActivationPlanRecord.binding_id == binding_id
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


def _candidate(binding_id: str, *, count: int = 17) -> RuleSetCandidate:
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


async def _run_consul_publication_worker_process_that_exits_after_provider_write(
    database_url: str,
    endpoint: str,
    acl_token: str,
    ca_pem: str,
    port: int,
    clock_time: datetime,
    consul_server: DisposableConsulAclServer,
) -> None:
    """Kill a scheduled publisher while its committed CAS response is held."""
    process_context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = process_context.Pipe(duplex=False)
    worker_process = process_context.Process(
        target=_exit_consul_publication_worker_after_provider_write,
        args=(
            database_url,
            endpoint,
            acl_token,
            ca_pem,
            port,
            clock_time,
            child_connection,
        ),
        name="sentinel-consul-activation-crash-acceptance",
    )
    worker_process.start()
    child_connection.close()
    try:
        ready = await asyncio.to_thread(parent_connection.poll, 45)
        if not ready:
            raise AssertionError("Consul activation publisher did not start")
        child_result = parent_connection.recv()
        if child_result != {"status": "worker-started"}:
            raise AssertionError(
                f"Consul activation publisher failed: {child_result!r}"
            )
        await consul_server.wait_for_committed_response(timeout=45)
        worker_process.terminate()
        await asyncio.to_thread(worker_process.join, 10)
        if worker_process.is_alive():
            raise AssertionError("Consul activation publisher resisted termination")
        consul_server.release_dropped_response()
        await consul_server.wait_for_dropped_response(timeout=10)
        if worker_process.exitcode is None or worker_process.exitcode == 0:
            raise AssertionError(
                "Consul activation publisher did not terminate during its provider call"
            )
    finally:
        if worker_process.is_alive():
            worker_process.terminate()
            await asyncio.to_thread(worker_process.join, 5)
            if worker_process.is_alive():
                worker_process.kill()
                await asyncio.to_thread(worker_process.join, 5)
            consul_server.release_dropped_response()
        parent_connection.close()


def _exit_consul_publication_worker_after_provider_write(
    database_url: str,
    endpoint: str,
    acl_token: str,
    ca_pem: str,
    port: int,
    clock_time: datetime,
    connection,
) -> None:
    async def run_worker() -> None:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        target_rule = RegisteredSourceTargetRule.create(
            ConfigurationSourceProvider.CONSUL,
            "127.0.0.1",
            ("127.0.0.1/32",),
            frozenset({port}),
        )
        worker = create_consul_rule_publication_worker(
            engine,
            target_policy=RegisteredSourceTargetPolicy((target_rule,)),
            credential_resolver=_AcceptanceConsulCredentialResolver(
                endpoint, acl_token
            ),
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            ssl_context=ssl.create_default_context(cadata=ca_pem),
            clock=lambda: clock_time,
        )
        connection.send({"status": "worker-started"})
        await worker.run_once()

    try:
        asyncio.run(run_worker())
    except BaseException as error:
        try:
            connection.send({"status": "error", "error_type": type(error).__name__})
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    finally:
        connection.close()


class _AcceptanceBindingReader:
    async def read_rule_binding(self, binding_id: str) -> RuleBinding:
        return RuleBinding(
            id=binding_id,
            environment_id="acceptance",
            app_id="acceptance-app",
            kind=RuleKind.FLOW,
            profile=_PROFILE,
            source_id="acceptance-source",
            source_label="Disposable Consul",
            location="local acceptance target",
        )


class _AcceptanceInitialized:
    async def is_initialized(self) -> bool:
        return True


class _AcceptanceSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _AcceptanceOperatorVerifier:
    async def is_current_operator(self, _opaque_session: str | None) -> bool:
        return False


class _AcceptancePublicationTargetReader:
    def __init__(self, key: str) -> None:
        self._key = key

    async def read_rule_publication_target(self, binding_id: str):
        target = ConsulRulePublicationTarget(
            binding_id=binding_id,
            source_id="acceptance-source",
            key=self._key,
        )
        return VersionedRulePublicationTarget(
            revision="target-revision-1",
            source_revision="source-revision-1",
            target=target,
        )


class _AcceptanceConsulCredentialResolver:
    def __init__(self, endpoint: str, acl_token: str) -> None:
        self._endpoint = endpoint
        self._acl_token = acl_token

    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint=self._endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token=self._acl_token,
        )


class _AcceptanceSourceReferenceResolver:
    def __init__(self, reference: str, acl_token: str) -> None:
        self._reference = reference
        self._acl_token = acl_token
        self.references: list[tuple[ConfigurationSourceProvider, str]] = []

    async def resolve(self, provider: ConfigurationSourceProvider, reference: str):
        self.references.append((provider, reference))
        if (
            provider is not ConfigurationSourceProvider.CONSUL
            or reference != self._reference
        ):
            return None
        return ResolvedSourceCredentials(provider=provider, acl_token=self._acl_token)
