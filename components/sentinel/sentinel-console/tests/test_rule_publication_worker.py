"""Focused lifecycle tests for durable publication execution and recovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import asyncio
import unittest

from atlas_richie.sentinel_console.application.read_rule_publication import (
    ReadRulePublication,
)
from atlas_richie.sentinel_console.application.read_rule_version import ReadRuleVersion
from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application import (
    resolve_registered_source_connection,
)
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationProviderConflict,
    RulePublicationProviderOutcomeUnknown,
    RulePublishWorkClaim,
)
from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RulePublicationWorkerOutcome,
    RunRulePublicationWorker,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    PublicationPhase,
    PublicationPhaseName,
    PublicationReason,
    PublicationStage,
    RulePublication,
    advance_publication_phase,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import (
    FlowControlBehavior,
    FlowGrade,
    FlowStrategy,
    FlowRuleValue,
    RuleRecord,
)
from atlas_richie.sentinel_console.domain.rule_versions import RuleSetVersion
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

    async def claim_ready(
        self, *, now, lease_expires_at, supported_providers, limit=1
    ):
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
        return self.versions[version_id]


class _SourceResolver:
    async def resolve_credentials(self, source_id, source_revision, provider):
        return SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=provider,
            endpoint="https://nacos.example.test",
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


class _Provider:
    supported_providers = frozenset({ConfigurationSourceProvider.NACOS})

    def __init__(
        self,
        *,
        lose_first_write_reply: bool = False,
        stale_reads_after_unknown: int = 0,
    ):
        self.snapshot = RuleConfigurationSnapshot(None, None)
        self.lose_first_write_reply = lose_first_write_reply
        self.stale_reads_after_unknown = stale_reads_after_unknown
        self._eventual_snapshot: RuleConfigurationSnapshot | None = None
        self.write_calls = 0

    async def read_configuration(self, connection, target):
        if self._eventual_snapshot is not None:
            if self.stale_reads_after_unknown > 0:
                self.stale_reads_after_unknown -= 1
                return RuleConfigurationSnapshot(None, None)
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
            self._eventual_snapshot = RuleConfigurationSnapshot("revision-2", value)
            raise RulePublicationProviderOutcomeUnknown
        self.snapshot = RuleConfigurationSnapshot("revision-2", value)
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
    ):
        claim = _claim()
        publication = _publication()
        outbox = _Outbox(claim, publication)
        provider_type = _SlowReadProvider if slow_provider else _Provider
        provider = provider_override or provider_type(
            lose_first_write_reply=lose_first_write_reply,
            stale_reads_after_unknown=stale_reads_after_unknown,
        )
        version = _version()
        worker = RunRulePublicationWorker(
            outbox=outbox,
            publication_reader=ReadRulePublication(_PublicationReader(outbox)),
            version_reader=ReadRuleVersion(_VersionReader({version.id: version})),
            source_connection_resolver=(
                resolve_registered_source_connection.ResolveRegisteredSourceConnection(
                    _SourceResolver()
                )
            ),
            payload_encoder=SentinelRuleVersionJsonEncoder(_PROFILE),
            provider=provider,
            clock=clock or _Clock(),
            lease_duration=lease_duration,
        )
        return worker, outbox, provider

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

    async def test_unknown_write_waits_for_eventual_read_visibility_without_replaying(self):
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
            RuleConfigurationSnapshot(
                "external-revision", b"external configuration"
            ),
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
