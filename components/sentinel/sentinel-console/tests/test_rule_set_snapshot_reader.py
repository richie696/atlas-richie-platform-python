from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, datetime

from atlas_richie.contracts.rules.managed_publication.v1.managed_publication import (
    ManagedRuleKind,
    ManagedRulePublicationV1,
    encode_managed_rule_publication,
)
from atlas_richie.sentinel_console.application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotInvalid,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotTargetMissing,
    RuleSetSnapshotUnsupportedProfile,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.rule_set_snapshot_reader import (
    RegisteredRuleSetSnapshotReader,
)

_NOW = datetime(2026, 10, 15, 7, 0, 0, 123000, tzinfo=UTC)
_FLOW_RULES = b'[{"resource":"POST /api/orders","limitApp":"default","grade":1,"count":25,"strategy":0,"controlBehavior":0,"clusterMode":false}]'


class _BindingReader:
    def __init__(self, binding: RuleBinding | None) -> None:
        self.binding = binding

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        return self.binding if self.binding and self.binding.id == binding_id else None


class _TargetReader:
    def __init__(self, target: VersionedRulePublicationTarget | None) -> None:
        self.target = target

    async def read_rule_publication_target(self, binding_id: str):
        if self.target is None or self.target.target.binding_id != binding_id:
            return None
        return self.target


class _ConnectionResolver:
    async def execute(self, source_id: str, source_revision: str, provider):
        return (source_id, source_revision, provider)


class _ProviderAdapter:
    def __init__(self, value: bytes | None, revision: str | None = None) -> None:
        self.value = value
        self.revision = "17" if value is not None and revision is None else revision

    async def read(self, _connection, _target):
        return self.value, self.revision


class RuleSetSnapshotReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.binding = RuleBinding(
            id="flow-binding",
            environment_id="e2e-live",
            app_id="sentinel-dashboard-e2e",
            kind=RuleKind.FLOW,
            profile="sentinel-python-v1",
            source_id="consul-test",
            source_label="Consul test",
            location="consul://sentinel/e2e/flow",
        )
        target = ConsulRulePublicationTarget(
            binding_id=self.binding.id,
            source_id=self.binding.source_id,
            key="sentinel/e2e/flow",
        )
        self.versioned_target = VersionedRulePublicationTarget(
            revision="target-r1", source_revision="source-r1", target=target
        )

    def _reader(self, value, *, binding=None):
        selected_binding = binding or self.binding
        return RegisteredRuleSetSnapshotReader(
            binding_reader=_BindingReader(selected_binding),
            target_reader=_TargetReader(self.versioned_target),
            connection_resolver=_ConnectionResolver(),
            provider_adapters={
                ConfigurationSourceProvider.CONSUL: _ProviderAdapter(value)
            },
            clock=lambda: _NOW,
        )

    async def test_reads_exact_native_array_with_stable_record_identity(self) -> None:
        first = await self._reader(_FLOW_RULES).read_rule_set_snapshot(self.binding.id)
        second = await self._reader(_FLOW_RULES).read_rule_set_snapshot(self.binding.id)

        self.assertEqual(len(first.records), 1)
        self.assertEqual(first.records[0].rule.resource, "POST /api/orders")
        self.assertEqual(first.records[0].id, second.records[0].id)
        self.assertEqual(
            first.checksum, f"sha256:{hashlib.sha256(_FLOW_RULES).hexdigest()}"
        )
        self.assertEqual(first.source_revision, "17")
        self.assertEqual(first.as_of, _NOW)

    async def test_java_and_go_flow_profiles_project_to_the_same_catalog_semantics(
        self,
    ) -> None:
        java_binding = replace(self.binding, profile="sentinel-java-v1")
        go_binding = replace(self.binding, profile="sentinel-go-v1")
        rust_binding = replace(self.binding, profile="sentinel-rust-v1")
        java = await self._reader(
            b'[{"resource":"GET /api/hello","grade":1,"count":3,"strategy":0,"controlBehavior":0,"limitApp":"default"}]',
            binding=java_binding,
        ).read_rule_set_snapshot(self.binding.id)
        go = await self._reader(
            b'[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000,"tokenCalculateStrategy":0,"controlBehavior":0,"relationStrategy":0,"refResource":""}]',
            binding=go_binding,
        ).read_rule_set_snapshot(self.binding.id)
        rust_count = await self._reader(
            b'[ {"resource":"GET /api/hello","grade":1,"count":3,"strategy":0,"controlBehavior":0,"limitApp":"default"} ]',
            binding=rust_binding,
        ).read_rule_set_snapshot(self.binding.id)
        rust_threshold = await self._reader(
            b'[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000,"tokenCalculateStrategy":0,"controlBehavior":0,"relationStrategy":0,"refResource":""}]',
            binding=rust_binding,
        ).read_rule_set_snapshot(self.binding.id)

        self.assertEqual(java.records[0].rule, go.records[0].rule)
        self.assertEqual(java.records[0].rule, rust_count.records[0].rule)
        self.assertEqual(java.records[0].rule, rust_threshold.records[0].rule)
        self.assertEqual(java.records[0].rule.resource, "GET /api/hello")
        self.assertEqual(java.records[0].rule.count, 3)
        self.assertEqual(java.records[0].rule.grade.value, 1)

    async def test_cross_language_flow_profiles_accept_explicit_empty_but_reject_unknown_semantics(
        self,
    ) -> None:
        for profile, native_rule in (
            (
                "sentinel-java-v1",
                b'[{"resource":"orders","grade":1,"count":3,"unknown":true}]',
            ),
            (
                "sentinel-go-v1",
                b'[{"resource":"orders","threshold":3,"statIntervalInMs":500}]',
            ),
            (
                "sentinel-rust-v1",
                b'[{"resource":"orders","grade":1,"count":3,"clusterMode":true}]',
            ),
        ):
            binding = replace(self.binding, profile=profile)
            empty = await self._reader(b"[]", binding=binding).read_rule_set_snapshot(
                self.binding.id
            )
            self.assertEqual(empty.records, ())
            with self.assertRaises(RuleSetSnapshotInvalid):
                await self._reader(native_rule, binding=binding).read_rule_set_snapshot(
                    self.binding.id
                )

    async def test_cross_language_profiles_fail_closed_for_unmodeled_rule_families(
        self,
    ) -> None:
        for profile in ("sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"):
            binding = replace(self.binding, profile=profile, kind=RuleKind.DEGRADE)
            with self.subTest(profile=profile):
                with self.assertRaises(RuleSetSnapshotUnsupportedProfile):
                    await self._reader(b"[]", binding=binding).read_rule_set_snapshot(
                        self.binding.id
                    )

    async def test_absent_provider_key_is_not_a_verified_empty_snapshot(self) -> None:
        with self.assertRaises(RuleSetSnapshotTargetMissing):
            await self._reader(None).read_rule_set_snapshot(self.binding.id)

    async def test_missing_key_and_confirmed_empty_array_keep_distinct_provider_fact(
        self,
    ) -> None:
        configured_empty = await self._reader(b"[]").read_rule_set_snapshot(
            self.binding.id
        )

        self.assertEqual(configured_empty.records, ())
        self.assertEqual(configured_empty.source_revision, "17")

    async def test_value_and_revision_must_be_present_together(self) -> None:
        reader = RegisteredRuleSetSnapshotReader(
            binding_reader=_BindingReader(self.binding),
            target_reader=_TargetReader(self.versioned_target),
            connection_resolver=_ConnectionResolver(),
            provider_adapters={
                ConfigurationSourceProvider.CONSUL: _ProviderAdapter(None, "17")
            },
            clock=lambda: _NOW,
        )

        with self.assertRaises(RuleSetSnapshotAuthorityUnavailable):
            await reader.read_rule_set_snapshot(self.binding.id)

    async def test_managed_envelope_is_unwrapped_without_deployment_allowlist(self) -> None:
        envelope = ManagedRulePublicationV1(
            binding_id=self.binding.id,
            publication_id="publish-17",
            target_version_id="version-17",
            publication_sequence=17,
            rule_kind=ManagedRuleKind.FLOW,
            profile_id=self.binding.profile,
            payload_sha256=hashlib.sha256(_FLOW_RULES).hexdigest(),
            rule_payload=_FLOW_RULES,
        )
        value = encode_managed_rule_publication(envelope)

        snapshot = await self._reader(value).read_rule_set_snapshot(
            self.binding.id
        )

        self.assertEqual(snapshot.version_id, "version-17")
        self.assertEqual(snapshot.records[0].rule.resource, "POST /api/orders")

    async def test_managed_envelope_metadata_must_match_the_exact_binding(self) -> None:
        envelope = ManagedRulePublicationV1(
            binding_id="other-binding",
            publication_id="publish-17",
            target_version_id="version-17",
            publication_sequence=17,
            rule_kind=ManagedRuleKind.FLOW,
            profile_id=self.binding.profile,
            payload_sha256=hashlib.sha256(_FLOW_RULES).hexdigest(),
            rule_payload=_FLOW_RULES,
        )

        with self.assertRaises(RuleSetSnapshotInvalid):
            await self._reader(encode_managed_rule_publication(envelope)).read_rule_set_snapshot(
                self.binding.id
            )

    async def test_managed_envelope_profile_kind_and_payload_must_match(self) -> None:
        envelope = ManagedRulePublicationV1(
            binding_id=self.binding.id,
            publication_id="publish-17",
            target_version_id="version-17",
            publication_sequence=17,
            rule_kind=ManagedRuleKind.FLOW,
            profile_id=self.binding.profile,
            payload_sha256=hashlib.sha256(_FLOW_RULES).hexdigest(),
            rule_payload=_FLOW_RULES,
        )
        for candidate in (
            replace(envelope, profile_id="sentinel-java-v1"),
            replace(envelope, rule_kind=ManagedRuleKind.DEGRADE),
        ):
            with self.subTest(profile=candidate.profile_id, kind=candidate.rule_kind):
                with self.assertRaises(RuleSetSnapshotInvalid):
                    await self._reader(
                        encode_managed_rule_publication(candidate)
                    ).read_rule_set_snapshot(self.binding.id)

    async def test_malformed_provider_value_fails_closed_without_raw_data(self) -> None:
        with self.assertRaises(RuleSetSnapshotAuthorityUnavailable):
            await self._reader(b'{"secret":"must-not-leak"}').read_rule_set_snapshot(
                self.binding.id
            )

    async def test_missing_binding_is_not_misreported_as_empty_rules(self) -> None:
        reader = RegisteredRuleSetSnapshotReader(
            binding_reader=_BindingReader(None),
            target_reader=_TargetReader(self.versioned_target),
            connection_resolver=_ConnectionResolver(),
            provider_adapters={
                ConfigurationSourceProvider.CONSUL: _ProviderAdapter(_FLOW_RULES)
            },
            clock=lambda: _NOW,
        )

        with self.assertRaises(RuleSetSnapshotNotFound):
            await reader.read_rule_set_snapshot(self.binding.id)


if __name__ == "__main__":
    unittest.main()
