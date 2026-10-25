"""Provider router contracts for frozen publication targets."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationProviderRejected,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure import (
    rule_publication_provider_router as provider_router,
)


class _Adapter:
    def __init__(self, provider: ConfigurationSourceProvider) -> None:
        self.supported_providers = frozenset({provider})
        self.read_calls = 0
        self.write_calls = 0

    async def read_configuration(self, connection, target):
        self.read_calls += 1
        return RuleConfigurationSnapshot("index-1", b"[]")

    async def write_configuration_if_revision(
        self, connection, target, *, expected_revision, value
    ):
        self.write_calls += 1
        return "index-2"


class RulePublicationProviderRouterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.nacos = _Adapter(ConfigurationSourceProvider.NACOS)
        self.consul = _Adapter(ConfigurationSourceProvider.CONSUL)
        self.router = provider_router.RulePublicationProviderRouter(
            {
                ConfigurationSourceProvider.NACOS: self.nacos,
                ConfigurationSourceProvider.CONSUL: self.consul,
            }
        )

    async def test_routes_by_frozen_target_and_connection_provider(self) -> None:
        connection = _connection(ConfigurationSourceProvider.CONSUL)
        target = ConsulRulePublicationTarget(
            binding_id="binding-1", source_id="source-1", key="rules/prod"
        )

        snapshot = await self.router.read_configuration(connection, target)
        receipt = await self.router.write_configuration_if_revision(
            connection, target, expected_revision="index-1", value=b"[{}]"
        )

        self.assertEqual(snapshot, RuleConfigurationSnapshot("index-1", b"[]"))
        self.assertEqual(receipt, "index-2")
        self.assertEqual(self.consul.read_calls, 1)
        self.assertEqual(self.consul.write_calls, 1)
        self.assertEqual(self.nacos.read_calls, 0)
        self.assertEqual(self.nacos.write_calls, 0)

    async def test_unconfigured_or_mismatched_provider_fails_closed(self) -> None:
        nacos_connection = _connection(ConfigurationSourceProvider.NACOS)
        nacos_target = NacosRulePublicationTarget(
            binding_id="binding-1",
            source_id="source-1",
            namespace="public",
            group="DEFAULT_GROUP",
            data_id="flow-rules",
        )
        consul_only_router = provider_router.RulePublicationProviderRouter(
            {ConfigurationSourceProvider.CONSUL: self.consul}
        )
        with self.assertRaises(RulePublicationProviderRejected):
            await consul_only_router.read_configuration(nacos_connection, nacos_target)
        with self.assertRaises(RulePublicationProviderRejected):
            await self.router.read_configuration(
                _connection(ConfigurationSourceProvider.CONSUL), nacos_target
            )
        self.assertEqual(self.nacos.read_calls, 0)


def _connection(provider: ConfigurationSourceProvider) -> SourceConnectionInput:
    return SourceConnectionInput(
        source_id="source-1",
        expected_revision="source-rev-1",
        provider=provider,
        endpoint="https://provider.example.test",
        location="public",
        authentication_mode=SourceCheckAuthenticationMode.NONE,
    )


if __name__ == "__main__":
    unittest.main()
