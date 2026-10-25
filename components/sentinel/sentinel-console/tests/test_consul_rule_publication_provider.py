"""Contract checks for mapping the Console provider Port to Consul KV."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationProviderConflict,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure import (
    consul_rule_publication_provider,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceSnapshot,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceConflict,
    ConsulRuleSourceWriteReceipt,
)


class _Reader:
    def __init__(self):
        self.key = None
        self.result = ConsulRuleSourceSnapshot("sentinel/prod/rules", b"[]", "12")

    async def read(self, connection, key):
        self.key = key
        return self.result


class _Writer:
    def __init__(self):
        self.command = None
        self.error = None

    async def write(self, command):
        self.command = command
        if self.error is not None:
            raise self.error
        return ConsulRuleSourceWriteReceipt("13")


class ConsulRulePublicationProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reader = _Reader()
        self.writer = _Writer()
        self.provider = consul_rule_publication_provider.ConsulRulePublicationProvider(
            reader=self.reader,
            writer=self.writer,
        )
        self.connection = SourceConnectionInput(
            source_id="source-1",
            expected_revision="source-rev-1",
            provider=ConfigurationSourceProvider.CONSUL,
            endpoint="https://consul.example.test",
            location="dc1",
            authentication_mode=SourceCheckAuthenticationMode.NONE,
        )
        self.target = ConsulRulePublicationTarget(
            binding_id="binding-1",
            source_id="source-1",
            key="sentinel/prod/rules",
            datacenter="dc1",
        )

    async def test_maps_exact_key_revision_and_value(self):
        observed = await self.provider.read_configuration(self.connection, self.target)
        written_revision = await self.provider.write_configuration_if_revision(
            self.connection,
            self.target,
            expected_revision=observed.revision,
            value=b"[candidate]",
        )

        self.assertEqual(self.reader.key, self.target.key)
        self.assertEqual(observed.value, b"[]")
        self.assertEqual(observed.revision, "12")
        self.assertTrue(observed.conditional_replay_safe)
        self.assertEqual(self.writer.command.expected_modify_index, "12")
        self.assertEqual(self.writer.command.value, b"[candidate]")
        self.assertEqual(written_revision, "13")

    async def test_maps_known_consul_cas_conflict_to_business_conflict(self):
        self.writer.error = ConsulRuleSourceConflict

        with self.assertRaises(RulePublicationProviderConflict):
            await self.provider.write_configuration_if_revision(
                self.connection,
                self.target,
                expected_revision="12",
                value=b"[candidate]",
            )


if __name__ == "__main__":
    unittest.main()
