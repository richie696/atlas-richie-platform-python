"""Focused lifecycle tests for durable publication execution and recovery."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atlas_richie.contracts.rules.managed_publication.v1 import (
    ManagedRuleKind,
    ManagedRulePublicationV1,
    decode_managed_rule_publication,
    encode_managed_rule_publication,
)
from atlas_richie.sentinel_console.application import (
    resolve_registered_source_connection,
)
from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.read_rule_publication import (
    ReadRulePublication,
)
from atlas_richie.sentinel_console.application.read_rule_version import ReadRuleVersion
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationConflict,
    RulePublicationProviderConflict,
    RulePublicationProviderOutcomeUnknown,
    RulePublishWorkClaim,
)
from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RulePublicationWorkerOutcome,
    RunRulePublicationWorker,
)
from atlas_richie.sentinel_console.application.rule_version_ports import (
    RuleSetVersionNotFound,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    PublicationPhase,
    PublicationReason,
    PublicationStage,
    RulePublication,
    advance_publication_phase,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowRuleValue,
    FlowStrategy,
    RuleRecord,
)
from atlas_richie.sentinel_console.domain.rule_versions import RuleSetVersion
from atlas_richie.sentinel_console.infrastructure.consul_rule_publication_provider import (
    ConsulRulePublicationProvider,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_publication_provider import (
    NacosRulePublicationProvider,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_PROFILE = "sentinel-profile-v1"
_START = datetime(2026, 10, 9, 3, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.value = _START

    def __call__(self) -> datetime:
        result = self.value
        self.value += timedelta(seconds=1)
        return result


class _ElapsedClock:
    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._started_at = self._loop.time()

    def __call__(self) -> datetime:
        elapsed = self._loop.time() - self._started_at
        return _START + timedelta(milliseconds=int(elapsed * 1000))


class _Outbox:
    def __init__(self, claim: RulePublishWorkClaim, publication: RulePublication):
        self.claim = claim
        self.publication = publication
        self.completed = False
        self.rejected = False
        self.claim_limits: list[int] = []
        self.renewals: list[RulePublishWorkClaim] = []
        self.renewal_error: Exception | None = None

    async def claim_ready(self, *, now, lease_expires_at, supported_providers, limit=1):
        self.claim_limits.append(limit)
        if self.claim.target.provider not in supported_providers:
            return ()
        if self.completed or self.rejected or limit < 1:
            return ()
        self.claim = replace(
            self.claim,
            attempt=self.claim.attempt + 1,
            claim_token=f"claim-{self.claim.attempt + 1}",
            lease_expires_at=lease_expires_at,
        )
        return (self.claim,)

    async def renew_claim(self, claim, *, now, lease_expires_at):
        if self.renewal_error is not None:
            raise self.renewal_error
        self.assert_current(claim)
        if now >= claim.lease_expires_at or lease_expires_at <= claim.lease_expires_at:
            raise AssertionError("renewal did not extend a live claim")
        self.claim = replace(claim, lease_expires_at=lease_expires_at)
        self.renewals.append(self.claim)
        return self.claim

    async def advance_claimed_phase(
        self, claim, phase_name, *, expected_state, next_phase
    ):
        self.assert_current(claim)
        self.publication = advance_publication_phase(
            self.publication,
            phase_name,
            expected_state=expected_state,
            next_phase=next_phase,
        )
        return self.publication

    async def complete_claimed_publication(self, claim, *, completed_at):
        self.assert_current(claim)
        self.completed = True

    async def reject_claimed_publication(self, claim, *, rejected_at, reason):
        self.assert_current(claim)
        self.rejected = True

    def assert_current(self, claim):
        if (
            claim.claim_token != self.claim.claim_token
            or claim.lease_expires_at != self.claim.lease_expires_at
        ):
            raise AssertionError("worker attempted a stale claim transition")


class _PublicationReader:
    def __init__(self, outbox: _Outbox):
        self.outbox = outbox

    async def read_rule_publication(self, binding_id, publication_id):
        return self.outbox.publication


class _VersionReader:
    def __init__(self, versions: dict[str, RuleSetVersion]):
        self.versions = versions

    async def read_rule_version(self, binding_id, version_id):
        try:
            return self.versions[version_id]
        except KeyError:
            raise RuleSetVersionNotFound("rule version does not exist") from None


class _PayloadChecksumWriter:
    def __init__(self):
        self.checksums = {}

    async def ensure_rule_publication_payload_checksum(
        self, binding_id, publication_id, payload_sha256
    ):
        key = (binding_id, publication_id)
        existing = self.checksums.get(key)
        if existing is not None and existing != payload_sha256:
            raise RulePublicationConflict("publication payload checksum changed")
        self.checksums[key] = payload_sha256


class _SourceResolver:
    def __init__(self, endpoint: str = "https://nacos.example.test") -> None:
        self.endpoint = endpoint

    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )

    async def execute(self, source_id, source_revision, provider):
        if (
            source_id != "source-1"
            or source_revision != "source-rev-1"
            or provider is not ConfigurationSourceProvider.NACOS
        ):
            raise AssertionError("worker did not use the frozen source identity")
        return object()


class _ConsulAcceptanceCredentialResolver(_SourceResolver):
    def __init__(self, endpoint: str, acl_token: str) -> None:
        super().__init__(endpoint)
        self._acl_token = acl_token

    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint=self.endpoint,
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token=self._acl_token,
        )


class _Provider:
    supported_providers = frozenset({ConfigurationSourceProvider.NACOS})

    def __init__(
        self,
        *,
        lose_first_write_reply: bool = False,
        stale_reads_after_unknown: int = 0,
        conditional_replay_safe: bool = False,
        leave_baseline_after_unknown: bool = False,
    ):
        self.snapshot = RuleConfigurationSnapshot(
            None, None, conditional_replay_safe=conditional_replay_safe
        )
        self.lose_first_write_reply = lose_first_write_reply
        self.stale_reads_after_unknown = stale_reads_after_unknown
        self.leave_baseline_after_unknown = leave_baseline_after_unknown
        self._eventual_snapshot: RuleConfigurationSnapshot | None = None
        self.write_calls = 0

    async def read_configuration(self, connection, target):
        if self._eventual_snapshot is not None:
            if self.stale_reads_after_unknown > 0:
                self.stale_reads_after_unknown -= 1
                return RuleConfigurationSnapshot(
                    None,
                    None,
                    conditional_replay_safe=self.snapshot.conditional_replay_safe,
                )
            self.snapshot = self._eventual_snapshot
            self._eventual_snapshot = None
        return self.snapshot

    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        if expected_revision != self.snapshot.revision:
            raise AssertionError("write did not use the observed provider revision")
        if self.lose_first_write_reply:
            self.lose_first_write_reply = False
            if not self.leave_baseline_after_unknown:
                self._eventual_snapshot = RuleConfigurationSnapshot(
                    "revision-2",
                    value,
                    conditional_replay_safe=self.snapshot.conditional_replay_safe,
                )
            raise RulePublicationProviderOutcomeUnknown
        self.snapshot = RuleConfigurationSnapshot(
            "revision-2",
            value,
            conditional_replay_safe=self.snapshot.conditional_replay_safe,
        )
        return "revision-2"


class _SlowReadProvider(_Provider):
    async def read_configuration(self, connection, target):
        await asyncio.sleep(0.11)
        return await super().read_configuration(connection, target)


class _ConcurrentModificationProvider(_Provider):
    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        if expected_revision != self.snapshot.revision:
            raise AssertionError("CAS did not use the observed provider revision")
        self.snapshot = RuleConfigurationSnapshot(
            "external-revision", b"external configuration"
        )
        raise RulePublicationProviderConflict


class _UnknownAfterExternalModificationProvider(_Provider):
    def __init__(self) -> None:
        super().__init__(conditional_replay_safe=True)

    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        self.snapshot = RuleConfigurationSnapshot(
            "external-revision",
            b"external configuration",
            conditional_replay_safe=True,
        )
        raise RulePublicationProviderOutcomeUnknown


class _ConditionalReplayConflictProvider(_Provider):
    def __init__(self) -> None:
        super().__init__(
            conditional_replay_safe=True, leave_baseline_after_unknown=True
        )

    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        if expected_revision != self.snapshot.revision:
            raise AssertionError(
                "recovery CAS did not use the observed provider revision"
            )
        if self.write_calls == 1:
            raise RulePublicationProviderOutcomeUnknown
        self.snapshot = RuleConfigurationSnapshot(
            "external-revision",
            b"external configuration",
            conditional_replay_safe=True,
        )
        raise RulePublicationProviderConflict


def _version() -> RuleSetVersion:
    return RuleSetVersion(
        id="version-1",
        binding_id="binding-1",
        kind=RuleKind.FLOW,
        profile=_PROFILE,
        base_version_id=None,
        checksum="version-checksum-1",
        name="Candidate",
        note="",
        created_at=_START,
        created_by_id="admin-1",
        records=(
            RuleRecord(
                "record-1",
                FlowRuleValue(
                    resource="/orders",
                    limit_app="default",
                    grade=FlowGrade.QPS,
                    count=100,
                    strategy=FlowStrategy.DIRECT,
                    control_behavior=FlowControlBehavior.REJECT,
                    cluster_mode=False,
                ),
            ),
        ),
    )


def _publication() -> RulePublication:
    awaiting = PublicationPhase(PublicationStage.AWAITING, None, None)
    return RulePublication(
        id="publication-1",
        binding_id="binding-1",
        target_version_id="version-1",
        target_checksum="version-checksum-1",
        base_version_id=None,
        created_at=_START,
        validation=awaiting,
        configuration_write=awaiting,
        read_back=awaiting,
    )


def _claim() -> RulePublishWorkClaim:
    return RulePublishWorkClaim(
        request_key="request-1",
        operation_id="operation-1",
        binding_id="binding-1",
        publication_id="publication-1",
        version_id="version-1",
        version_checksum="version-checksum-1",
        expected_version_id=None,
        expected_checksum="no-baseline",
        expected_source_revision=None,
        target_revision="target-rev-1",
        source_revision="source-rev-1",
        target=NacosRulePublicationTarget(
            binding_id="binding-1",
            source_id="source-1",
            namespace="public",
            group="SENTINEL_GROUP",
            data_id="rules.json",
        ),
        claim_token="claim-1",
        lease_expires_at=_START + timedelta(seconds=60),
        attempt=1,
    )


class RulePublicationWorkerTest(unittest.IsolatedAsyncioTestCase):
    def _worker(
        self,
        *,
        lose_first_write_reply: bool = False,
        stale_reads_after_unknown: int = 0,
        lease_duration: timedelta = timedelta(seconds=60),
        clock=None,
        slow_provider: bool = False,
        provider_override: _Provider | None = None,
        conditional_replay_safe: bool = False,
        leave_baseline_after_unknown: bool = False,
        managed_binding_ids: frozenset[str] = frozenset(),
        claim_override: RulePublishWorkClaim | None = None,
        publication_override: RulePublication | None = None,
        versions: dict[str, RuleSetVersion] | None = None,
        source_resolver: _SourceResolver
        | _ConsulAcceptanceCredentialResolver
        | None = None,
    ):
        claim = claim_override or _claim()
        publication = publication_override or _publication()
        outbox = _Outbox(claim, publication)
        provider_type = _SlowReadProvider if slow_provider else _Provider
        provider = provider_override or provider_type(
            lose_first_write_reply=lose_first_write_reply,
            stale_reads_after_unknown=stale_reads_after_unknown,
            conditional_replay_safe=conditional_replay_safe,
            leave_baseline_after_unknown=leave_baseline_after_unknown,
        )
        version = _version()
        version_facts = versions or {version.id: version}
        payload_checksum_writer = _PayloadChecksumWriter()
        worker = RunRulePublicationWorker(
            outbox=outbox,
            publication_reader=ReadRulePublication(_PublicationReader(outbox)),
            version_reader=ReadRuleVersion(_VersionReader(version_facts)),
            source_connection_resolver=(
                resolve_registered_source_connection.ResolveRegisteredSourceConnection(
                    source_resolver or _SourceResolver()
                )
            ),
            payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
            payload_checksum_writer=payload_checksum_writer,
            provider=provider,
            managed_binding_ids=managed_binding_ids,
            clock=clock or _Clock(),
            lease_duration=lease_duration,
        )
        self.payload_checksum_writer = payload_checksum_writer
        return worker, outbox, provider

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_NACOS_ACCEPTANCE=1 to start disposable Nacos",
    )
    async def test_managed_publication_worker_writes_and_reads_real_nacos_envelope(
        self,
    ):
        from rule_publication_nacos_database_acceptance import (
            _CONTAINER_OWNER_LABEL,
            _IMAGE,
            _free_loopback_port_pair,
            _nacos_target_policy,
            _remove_owned_container,
            _wait_for_nacos,
        )

        token = uuid4().hex
        http_port, grpc_port = _free_loopback_port_pair()
        endpoint = f"http://127.0.0.1:{http_port}/nacos"
        target = NacosRulePublicationTarget(
            binding_id="binding-1",
            source_id="source-1",
            namespace="public",
            group="SENTINEL_MANAGED_ACCEPTANCE",
            data_id=f"managed-{token}.json",
        )
        container_name = f"sentinel-managed-nacos-{token[:12]}"
        container_id: str | None = None
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "run",
                    "--detach",
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
                    "NACOS_AUTH_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI=",
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
            container_id = result.stdout.strip()
            try:
                _wait_for_nacos(endpoint)
            except AssertionError:
                logs = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "logs", container_name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                raise AssertionError(
                    "disposable Nacos did not become ready; startup logs: "
                    f"{logs.stdout[-4000:]}{logs.stderr[-4000:]}"
                ) from None

            policy = _nacos_target_policy(http_port, grpc_port)
            reader = NacosRuleSourceReader(policy)
            provider = NacosRulePublicationProvider(
                reader=reader,
                writer=NacosRuleSourceWriter(policy, reader),
            )
            worker, outbox, _provider = self._worker(
                provider_override=provider,
                managed_binding_ids=frozenset({"binding-1"}),
                claim_override=replace(_claim(), target=target),
                source_resolver=_SourceResolver(endpoint),
            )

            self.assertEqual(
                await worker.run_once(), (RulePublicationWorkerOutcome.COMPLETED,)
            )
            connection = await resolve_registered_source_connection.ResolveRegisteredSourceConnection(
                _SourceResolver(endpoint)
            ).execute("source-1", "source-rev-1", ConfigurationSourceProvider.NACOS)
            stored = await provider.read_configuration(connection, target)
            envelope = decode_managed_rule_publication(stored.value)
            native_payload = SentinelRuleVersionJsonEncoder(
                _PROFILE
            ).encode_rule_version(_version())
            self.assertEqual(envelope.binding_id, "binding-1")
            self.assertEqual(envelope.publication_id, "publication-1")
            self.assertEqual(envelope.target_version_id, "version-1")
            self.assertEqual(envelope.publication_sequence, 1)
            self.assertEqual(envelope.rule_payload, native_payload)
            self.assertEqual(
                envelope.payload_sha256, hashlib.sha256(native_payload).hexdigest()
            )
            self.assertTrue(outbox.completed)
        finally:
            if container_id is not None:
                await asyncio.to_thread(_remove_owned_container, container_id, token)

    @unittest.skipUnless(
        os.environ.get("SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE") == "1",
        "set SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE=1 to start disposable Consul",
    )
    async def test_managed_publication_worker_writes_and_reads_real_consul_envelope(
        self,
    ):
        from consul_acl_test_support import DisposableConsulAclServer

        token = uuid4().hex
        key = f"sentinel/acceptance/managed-{token}.json"
        server = DisposableConsulAclServer(key)
        await server.start()
        try:
            policy = server.registered_target_policy()
            target = ConsulRulePublicationTarget(
                binding_id="binding-1", source_id="source-1", key=key
            )
            reader = ConsulRuleSourceReader(policy, server.http_client())
            provider = ConsulRulePublicationProvider(
                reader=reader,
                writer=ConsulRuleSourceWriter(policy, server.http_client()),
            )
            connection_resolver = _ConsulAcceptanceCredentialResolver(
                server.endpoint, server.application_token
            )
            worker, outbox, _provider = self._worker(
                provider_override=provider,
                managed_binding_ids=frozenset({"binding-1"}),
                claim_override=replace(_claim(), target=target),
                source_resolver=connection_resolver,
            )

            self.assertEqual(
                await worker.run_once(), (RulePublicationWorkerOutcome.COMPLETED,)
            )
            connection = await resolve_registered_source_connection.ResolveRegisteredSourceConnection(
                connection_resolver
            ).execute("source-1", "source-rev-1", ConfigurationSourceProvider.CONSUL)
            stored = await provider.read_configuration(connection, target)
            envelope = decode_managed_rule_publication(stored.value)
            native_payload = SentinelRuleVersionJsonEncoder(
                _PROFILE
            ).encode_rule_version(_version())
            self.assertEqual(envelope.binding_id, "binding-1")
            self.assertEqual(envelope.publication_id, "publication-1")
            self.assertEqual(envelope.target_version_id, "version-1")
            self.assertEqual(envelope.publication_sequence, 1)
            self.assertEqual(envelope.rule_payload, native_payload)
            self.assertEqual(
                envelope.payload_sha256, hashlib.sha256(native_payload).hexdigest()
            )
            self.assertTrue(outbox.completed)
        finally:
            await server.close()

    async def test_managed_binding_publishes_exact_envelope_and_keeps_native_digest(
        self,
    ):
        worker, outbox, provider = self._worker(
            managed_binding_ids=frozenset({"binding-1"})
        )

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
        envelope = decode_managed_rule_publication(provider.snapshot.value)
        native_payload = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            _version()
        )
        self.assertEqual(envelope.binding_id, "binding-1")
        self.assertEqual(envelope.publication_id, "publication-1")
        self.assertEqual(envelope.target_version_id, "version-1")
        self.assertEqual(envelope.publication_sequence, 1)
        self.assertEqual(envelope.rule_kind.value, "flow")
        self.assertEqual(envelope.profile_id, _PROFILE)
        self.assertEqual(envelope.rule_payload, native_payload)
        self.assertEqual(
            envelope.payload_sha256, hashlib.sha256(native_payload).hexdigest()
        )
        self.assertEqual(
            self.payload_checksum_writer.checksums[("binding-1", "publication-1")],
            hashlib.sha256(native_payload).hexdigest(),
        )
        self.assertTrue(outbox.completed)

    async def test_managed_binding_adopts_only_the_exact_attested_native_baseline(
        self,
    ):
        native_baseline = b'[]'
        provider = _Provider()
        provider.snapshot = RuleConfigurationSnapshot("revision-1", native_baseline)
        claim = replace(
            _claim(),
            expected_checksum=(
                f"sha256:{hashlib.sha256(native_baseline).hexdigest()}"
            ),
        )
        worker, outbox, provider = self._worker(
            managed_binding_ids=frozenset({"binding-1"}),
            claim_override=claim,
            provider_override=provider,
        )

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
        envelope = decode_managed_rule_publication(provider.snapshot.value)
        self.assertEqual(envelope.publication_id, "publication-1")
        self.assertEqual(
            envelope.rule_payload,
            SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(_version()),
        )
        self.assertEqual(provider.write_calls, 1)
        self.assertTrue(outbox.completed)

    async def test_managed_binding_rejects_a_changed_native_baseline(self):
        provider = _Provider()
        provider.snapshot = RuleConfigurationSnapshot(
            "revision-1", b'[{"changed":true}]'
        )
        claim = replace(_claim(), expected_checksum="sha256:" + "0" * 64)
        worker, outbox, provider = self._worker(
            managed_binding_ids=frozenset({"binding-1"}),
            claim_override=claim,
            provider_override=provider,
        )

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.REJECTED,))
        self.assertEqual(provider.write_calls, 0)
        self.assertTrue(outbox.rejected)

    async def test_managed_binding_accepts_exact_managed_previous_version_baseline(
        self,
    ):
        target_version = _version()
        baseline_version = replace(
            target_version,
            id="version-0",
            checksum="version-checksum-0",
        )
        baseline_payload = SentinelRuleVersionJsonEncoder(_PROFILE).encode_rule_version(
            baseline_version
        )
        baseline_envelope = encode_managed_rule_publication(
            ManagedRulePublicationV1(
                binding_id="binding-1",
                publication_id="publication-0",
                target_version_id=baseline_version.id,
                publication_sequence=1,
                rule_kind=ManagedRuleKind.FLOW,
                profile_id=_PROFILE,
                payload_sha256=hashlib.sha256(baseline_payload).hexdigest(),
                rule_payload=baseline_payload,
            )
        )
        provider = _Provider()
        provider.snapshot = RuleConfigurationSnapshot("revision-1", baseline_envelope)
        claim = replace(
            _claim(),
            expected_version_id=baseline_version.id,
            expected_checksum=(
                f"sha256:{hashlib.sha256(baseline_payload).hexdigest()}"
            ),
        )
        publication = replace(
            _publication(),
            base_version_id=baseline_version.id,
            publication_sequence=2,
        )
        worker, outbox, provider = self._worker(
            managed_binding_ids=frozenset({"binding-1"}),
            claim_override=claim,
            publication_override=publication,
            versions={
                target_version.id: target_version,
                baseline_version.id: baseline_version,
            },
            provider_override=provider,
        )

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertTrue(outbox.completed)
        published = decode_managed_rule_publication(provider.snapshot.value)
        self.assertEqual(published.target_version_id, target_version.id)
        self.assertEqual(published.publication_sequence, 2)

    async def test_validates_writes_reads_back_and_completes(self):
        worker, outbox, provider = self._worker()

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertTrue(outbox.completed)
        self.assertFalse(outbox.rejected)
        self.assertEqual(provider.write_calls, 1)
        self.assertEqual(
            outbox.publication.validation.state, PublicationStage.SUCCEEDED
        )
        self.assertEqual(
            outbox.publication.configuration_write.state, PublicationStage.SUCCEEDED
        )
        self.assertEqual(outbox.publication.read_back.state, PublicationStage.SUCCEEDED)

    async def test_claims_one_operation_at_a_time_even_when_run_limit_is_larger(self):
        worker, outbox, provider = self._worker()

        outcomes = await worker.run_once(limit=5)

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertEqual(outbox.claim_limits, [1, 1])
        self.assertTrue(outbox.completed)
        self.assertEqual(provider.write_calls, 1)

    async def test_rejects_run_limit_outside_supported_batch_range(self):
        worker, outbox, _provider = self._worker()

        with self.assertRaises(ValueError):
            await worker.run_once(limit=101)

        self.assertEqual(outbox.claim_limits, [])

    async def test_renews_active_claim_during_slow_provider_calls(self):
        worker, outbox, provider = self._worker(
            lease_duration=timedelta(milliseconds=60),
            clock=_ElapsedClock(),
            slow_provider=True,
        )

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertGreaterEqual(len(outbox.renewals), 2)
        self.assertTrue(outbox.completed)
        self.assertEqual(provider.write_calls, 1)

    async def test_renewal_failure_stops_before_any_provider_write(self):
        worker, outbox, provider = self._worker(
            lease_duration=timedelta(milliseconds=60),
            clock=_ElapsedClock(),
            slow_provider=True,
        )
        outbox.renewal_error = OSError("outbox unavailable")

        with self.assertRaisesRegex(OSError, "outbox unavailable"):
            await worker.run_once()

        self.assertEqual(provider.write_calls, 0)
        self.assertFalse(outbox.completed)
        self.assertFalse(outbox.rejected)

    async def test_unknown_write_is_reconciled_without_a_second_provider_write(self):
        worker, outbox, provider = self._worker(lose_first_write_reply=True)

        first = await worker.run_once()
        second = await worker.run_once()

        self.assertEqual(first, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(second, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertTrue(outbox.completed)
        self.assertEqual(provider.write_calls, 1)

    async def test_authoritative_external_change_after_unknown_write_is_a_conflict(
        self,
    ):
        provider = _UnknownAfterExternalModificationProvider()
        worker, outbox, _ = self._worker(provider_override=provider)

        first = await worker.run_once()
        recovered = await worker.run_once()

        self.assertEqual(first, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(recovered, (RulePublicationWorkerOutcome.REJECTED,))
        self.assertTrue(outbox.rejected)
        self.assertFalse(outbox.completed)
        self.assertEqual(provider.write_calls, 1)
        self.assertEqual(provider.snapshot.value, b"external configuration")
        self.assertEqual(
            outbox.publication.configuration_write.state,
            PublicationStage.FAILED,
        )
        self.assertEqual(
            outbox.publication.configuration_write.reason,
            PublicationReason.CONFLICT,
        )

    async def test_unknown_write_retries_only_after_authoritative_baseline_read(self):
        worker, outbox, provider = self._worker(
            lose_first_write_reply=True,
            conditional_replay_safe=True,
            leave_baseline_after_unknown=True,
        )

        first = await worker.run_once()
        recovered = await worker.run_once()

        self.assertEqual(first, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(recovered, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertTrue(outbox.completed)
        self.assertEqual(provider.write_calls, 2)

    async def test_conditional_replay_conflict_is_finalized_as_known_conflict(self):
        provider = _ConditionalReplayConflictProvider()
        worker, outbox, _ = self._worker(provider_override=provider)

        unknown = await worker.run_once()
        conflict = await worker.run_once()

        self.assertEqual(unknown, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(conflict, (RulePublicationWorkerOutcome.REJECTED,))
        self.assertTrue(outbox.rejected)
        self.assertFalse(outbox.completed)
        self.assertEqual(provider.write_calls, 2)
        self.assertEqual(provider.snapshot.value, b"external configuration")
        self.assertEqual(
            outbox.publication.configuration_write.state,
            PublicationStage.FAILED,
        )
        self.assertEqual(
            outbox.publication.configuration_write.reason,
            PublicationReason.CONFLICT,
        )

    async def test_unknown_write_does_not_retry_from_non_authoritative_baseline(self):
        worker, outbox, provider = self._worker(
            lose_first_write_reply=True,
            leave_baseline_after_unknown=True,
        )

        first = await worker.run_once()
        recovered = await worker.run_once()

        self.assertEqual(first, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(recovered, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertFalse(outbox.completed)
        self.assertEqual(provider.write_calls, 1)

    async def test_unknown_write_waits_for_eventual_read_visibility_without_replaying(
        self,
    ):
        worker, outbox, provider = self._worker(
            lose_first_write_reply=True,
            stale_reads_after_unknown=1,
        )

        first = await worker.run_once()
        stale_read = await worker.run_once()
        converged_read = await worker.run_once()

        self.assertEqual(first, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(stale_read, (RulePublicationWorkerOutcome.UNKNOWN,))
        self.assertEqual(converged_read, (RulePublicationWorkerOutcome.COMPLETED,))
        self.assertTrue(outbox.completed)
        self.assertFalse(outbox.rejected)
        self.assertEqual(provider.write_calls, 1)

    async def test_changed_baseline_is_rejected_before_provider_write(self):
        worker, outbox, provider = self._worker()
        provider.snapshot = RuleConfigurationSnapshot("revision-1", b"other rules")

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.REJECTED,))
        self.assertTrue(outbox.rejected)
        self.assertEqual(provider.write_calls, 0)
        self.assertEqual(outbox.publication.validation.state, PublicationStage.FAILED)

    async def test_cas_conflict_after_read_does_not_overwrite_external_change(self):
        worker, outbox, provider = self._worker(
            provider_override=_ConcurrentModificationProvider()
        )

        outcomes = await worker.run_once()

        self.assertEqual(outcomes, (RulePublicationWorkerOutcome.REJECTED,))
        self.assertTrue(outbox.rejected)
        self.assertFalse(outbox.completed)
        self.assertEqual(provider.write_calls, 1)
        self.assertEqual(
            provider.snapshot,
            RuleConfigurationSnapshot("external-revision", b"external configuration"),
        )
        self.assertEqual(
            outbox.publication.configuration_write.state, PublicationStage.FAILED
        )
        self.assertEqual(
            outbox.publication.configuration_write.reason,
            PublicationReason.CONFLICT,
        )


if __name__ == "__main__":
    unittest.main()
