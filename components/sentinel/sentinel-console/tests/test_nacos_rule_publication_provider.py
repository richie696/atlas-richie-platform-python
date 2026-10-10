"""Port mapping contracts for the Nacos publication adapter."""

from __future__ import annotations

import hashlib
import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationProviderConflict,
    RulePublicationProviderRejected,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_publication_provider import (
    NacosRulePublicationProvider,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceSnapshot,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceConflict,
    NacosRuleSourceWriteReceipt,
)


def _md5(value: bytes) -> str:
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


class _Reader:
    def __init__(self):
        self.target = None

    async def read(self, connection, target):
        self.target = target
        return NacosRuleSourceSnapshot(
            namespace=target.namespace,
            group=target.group,
            data_id=target.data_id,
            value=b"[]",
            md5=_md5(b"[]"),
        )


class _Writer:
    def __init__(self):
        self.command = None
        self.error = None

    async def write(self, command):
        self.command = command
        if self.error:
            raise self.error
        return NacosRuleSourceWriteReceipt(_md5(b"candidate"))


class NacosRulePublicationProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reader = _Reader()
        self.writer = _Writer()
        self.provider = NacosRulePublicationProvider(
            reader=self.reader,
            writer=self.writer,
        )
        self.connection = SourceConnectionInput(
            source_id="source-1",
            expected_revision="source-revision-1",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint="https://nacos.example.test:8848",
            location="tenant-a",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        self.target = NacosRulePublicationTarget(
            binding_id="binding-1",
            source_id="source-1",
            namespace="tenant-a",
            group="SENTINEL_GROUP",
            data_id="sentinel-rules.json",
        )

    async def test_maps_md5_baseline_target_and_receipt(self):
        snapshot = await self.provider.read_configuration(
            self.connection, self.target
        )
        revision = await self.provider.write_configuration_if_revision(
            self.connection,
            self.target,
            expected_revision=snapshot.revision,
            value=b"candidate",
        )

        self.assertEqual(self.reader.target, self.target)
        self.assertEqual(snapshot.revision, _md5(b"[]"))
        self.assertEqual(self.writer.command.expected_md5, _md5(b"[]"))
        self.assertEqual(self.writer.command.value, b"candidate")
        self.assertEqual(revision, _md5(b"candidate"))

    async def test_rejects_absent_config_without_blanking_cas_token(self):
        with self.assertRaises(RulePublicationProviderRejected):
            await self.provider.write_configuration_if_revision(
                self.connection,
                self.target,
                expected_revision=None,
                value=b"candidate",
            )
        self.assertIsNone(self.writer.command)

    async def test_maps_conflict_without_leaking_provider_exception(self):
        self.writer.error = NacosRuleSourceConflict
        with self.assertRaises(RulePublicationProviderConflict):
            await self.provider.write_configuration_if_revision(
                self.connection,
                self.target,
                expected_revision=_md5(b"[]"),
                value=b"candidate",
            )


if __name__ == "__main__":
    unittest.main()
