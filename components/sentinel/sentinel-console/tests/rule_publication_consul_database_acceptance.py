"""Opt-in SQL-dialect to disposable Consul publication acceptance."""

from __future__ import annotations

import hashlib
import subprocess
import time
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    PublishRuleVersion,
    RuleMutationCommand,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.application.read_rule_version import ReadRuleVersion
from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RulePublicationWorkerOutcome,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import (
    RuleSetCandidate,
    candidate_checksum,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_store import (
    SqlAlchemyRuleMutationStore,
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
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)
from atlas_richie.sentinel_console.api.rule_candidate_parsing import (
    parse_rule_candidate,
)
from atlas_richie.sentinel_console.api.rule_snapshot_serializers import rule_record_body
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    VersionedRulePublicationTarget,
)

_CONSUL_IMAGE = "hashicorp/consul:1.21.1"
_PROFILE = "sentinel-profile-v1"
_FINGERPRINT_KEY = b"synthetic-cross-database-consul-acceptance-key-0001"
_NOW = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)


async def assert_sql_outbox_publishes_to_disposable_consul(engine: AsyncEngine) -> None:
    """Exercise the real SQL outbox/worker with PostgreSQL or MySQL and Consul.

    The caller must supply an isolated ``sentinel_console_test_*`` database.
    The only external service this helper starts is a uniquely named disposable
    Consul container, removed in ``finally``.
    """
    if engine.dialect.name not in {"postgresql", "mysql"}:
        raise ValueError("acceptance requires PostgreSQL or MySQL")

    token = uuid4().hex
    account_id = str(uuid4())
    actor_id = account_id
    binding_id = f"binding-{token}"
    version_id = f"version-{token}"
    validation_id = f"validation-{token}"
    request_key = f"request-{token}"
    session_token = f"session-{token}"
    csrf_token = f"csrf-{token}"
    session_digest = _digest(session_token)
    csrf_digest = _digest(csrf_token)
    username = f"consul-acceptance-{token}"
    username_key = _digest(username)
    container_name = f"sentinel-sql-consul-{token[:12]}"
    consul_started = False
    identity_seeded = False
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

        consul_started = True
        subprocess.run(
            [
                "docker", "run", "--detach", "--rm", "--name", container_name,
                "--publish", "127.0.0.1::8500/tcp", _CONSUL_IMAGE,
                "agent", "-dev", "-client=0.0.0.0",
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
        key = f"sentinel/acceptance/{token}/rules.json"
        target_reader = _AcceptancePublicationTargetReader(key)
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _FINGERPRINT_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_AcceptanceBindingReader(),
            publication_target_reader=target_reader,
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
                    "synthetic acceptance reason",
                ),
            ),
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"http-{token}",
            now=_NOW,
        )
        assert accepted.status is RuleOperationStatus.PENDING

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
        credential_resolver = _AcceptanceConsulCredentialResolver(endpoint)
        worker = create_consul_rule_publication_worker(
            engine,
            target_policy=policy,
            credential_resolver=credential_resolver,
            credential_reference_resolver=None,
            profile_id=_PROFILE,
            clock=lambda: _NOW,
        )
        assert await worker.run_once() == (RulePublicationWorkerOutcome.COMPLETED,)

        source_connection = await credential_resolver.resolve_credentials(
            "acceptance-source", "source-revision-1", ConfigurationSourceProvider.CONSUL
        )
        stored = await ConsulRuleSourceReader(policy).read(source_connection, key)
        version = await ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)).execute(
            binding_id, version_id
        )
        assert stored.value == SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            version
        )
        assert stored.modify_index is not None
        completed = await store.read_operation(
            binding_id, request_key, actor_id=actor_id, session_digest=session_digest
        )
        assert completed.status is RuleOperationStatus.COMPLETED
        assert completed.result.read_back.state.value == "succeeded"
        assert "synthetic acceptance reason" not in repr(completed)
        assert await worker.run_once() == ()
        assert (await ConsulRuleSourceReader(policy).read(source_connection, key)).modify_index == (
            stored.modify_index
        )
    finally:
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
        if consul_started:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )


async def _seed_identity(
    engine: AsyncEngine,
    *,
    account_id: str,
    username: str,
    username_key: str,
    session_digest: str,
    csrf_digest: str,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(AccountRecord).values(
                account_id=account_id,
                username=username,
                username_key=username_key,
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
                records=[rule_record_body(RuleRecord("acceptance-record", candidate.rules[0].rule))],
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
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            delete(AuditEventRecord).where(AuditEventRecord.actor_account_id == account_id)
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
            delete(RuleSetVersionRecord).where(RuleSetVersionRecord.version_id == version_id)
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
        await connection.execute(
            delete(AccountRecord).where(AccountRecord.account_id == account_id)
        )


def _candidate(binding_id: str) -> RuleSetCandidate:
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
                            "count": 17,
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


def _wait_for_consul(endpoint: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{endpoint}/v1/status/leader", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise AssertionError("disposable Consul did not become healthy")


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
