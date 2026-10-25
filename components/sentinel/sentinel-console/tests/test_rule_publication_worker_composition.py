"""Production publication-worker composition contracts without provider I/O."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RunRulePublicationWorker,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcTlsCredentials,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    rule_publication_worker_composition,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_engine_provider import (
    RuntimeDatabaseEngineBridge,
    RuntimeDatabaseEngineProvider,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)


class RulePublicationWorkerCompositionTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_sql_worker_routes_only_enabled_provider_adapters(self) -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(engine)
        try:
            nacos_policy = _target_policy(
                ConfigurationSourceProvider.NACOS,
                "nacos.example.test",
                frozenset({8848, 9848}),
            )
            consul_policy = _target_policy(
                ConfigurationSourceProvider.CONSUL,
                "consul.example.test",
                frozenset({8501}),
            )
            worker = rule_publication_worker_composition.create_rule_publication_worker(
                engine,
                target_policies={
                    ConfigurationSourceProvider.NACOS: nacos_policy,
                    ConfigurationSourceProvider.CONSUL: consul_policy,
                },
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            )

            self.assertEqual(
                worker._supported_providers,
                frozenset(
                    {
                        ConfigurationSourceProvider.NACOS,
                        ConfigurationSourceProvider.CONSUL,
                    }
                ),
            )
            self.assertEqual(await worker.run_once(), ())
        finally:
            await engine.dispose()

    async def test_worker_rejects_invalid_provider_identity(self) -> None:
        provider = RuntimeDatabaseEngineProvider(_UnconfiguredLocatorStore())
        bridge = RuntimeDatabaseEngineBridge(provider)
        with self.assertRaisesRegex(TypeError, "provider identity is invalid"):
            rule_publication_worker_composition.create_rule_publication_worker(
                bridge,
                target_policies={"mystery": object()},
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
            )
        await provider.dispose()

    async def test_worker_rejects_nacos_tls_without_nacos_adapter(self) -> None:
        provider = RuntimeDatabaseEngineProvider(_UnconfiguredLocatorStore())
        bridge = RuntimeDatabaseEngineBridge(provider)
        with self.assertRaisesRegex(ValueError, "requires a Nacos publication adapter"):
            rule_publication_worker_composition.create_rule_publication_worker(
                bridge,
                target_policies={
                    ConfigurationSourceProvider.CONSUL: _target_policy(
                        ConfigurationSourceProvider.CONSUL,
                        "consul.example.test",
                        frozenset({8501}),
                    )
                },
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                grpc_tls_credentials=NacosGrpcTlsCredentials(
                    root_certificates=b"private-ca"
                ),
            )
        await provider.dispose()

    async def test_consul_worker_composes_and_reads_empty_sql_outbox(self) -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(engine)
        try:
            policy = RegisteredSourceTargetPolicy(
                (
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.CONSUL,
                        "consul.example.test",
                        ("192.0.2.0/24",),
                        frozenset({8501}),
                    ),
                )
            )
            create_worker = rule_publication_worker_composition.create_consul_rule_publication_worker
            worker = create_worker(
                engine,
                target_policy=policy,
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            )

            self.assertEqual(await worker.run_once(), ())
        finally:
            await engine.dispose()

    async def test_consul_worker_accepts_lazy_runtime_engine_bridge(self) -> None:
        provider = RuntimeDatabaseEngineProvider(_UnconfiguredLocatorStore())
        bridge = RuntimeDatabaseEngineBridge(provider)
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.CONSUL,
                    "consul.example.test",
                    ("192.0.2.0/24",),
                    frozenset({8501}),
                ),
            )
        )

        worker = (
            rule_publication_worker_composition.create_consul_rule_publication_worker(
                bridge,
                target_policy=policy,
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            )
        )

        self.assertIsInstance(worker, RunRulePublicationWorker)
        await provider.dispose()

    async def test_nacos_worker_composes_without_contacting_provider(self) -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await upgrade_database(engine)
        try:
            policy = RegisteredSourceTargetPolicy(
                (
                    RegisteredSourceTargetRule.create(
                        ConfigurationSourceProvider.NACOS,
                        "nacos.example.test",
                        ("192.0.2.0/24",),
                        frozenset({8848, 9848}),
                    ),
                )
            )
            worker = rule_publication_worker_composition.create_nacos_rule_publication_worker(
                engine,
                target_policy=policy,
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            )

            self.assertIsInstance(worker, RunRulePublicationWorker)
            self.assertEqual(await worker.run_once(), ())
        finally:
            await engine.dispose()

    async def test_nacos_worker_accepts_lazy_runtime_engine_bridge(self) -> None:
        provider = RuntimeDatabaseEngineProvider(_UnconfiguredLocatorStore())
        bridge = RuntimeDatabaseEngineBridge(provider)
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "nacos.example.test",
                    ("192.0.2.0/24",),
                    frozenset({8848, 9848}),
                ),
            )
        )

        worker = (
            rule_publication_worker_composition.create_nacos_rule_publication_worker(
                bridge,
                target_policy=policy,
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            )
        )

        self.assertIsInstance(worker, RunRulePublicationWorker)
        await provider.dispose()

    async def test_nacos_worker_injects_deployment_owned_grpc_tls_credentials(
        self,
    ) -> None:
        provider = RuntimeDatabaseEngineProvider(_UnconfiguredLocatorStore())
        bridge = RuntimeDatabaseEngineBridge(provider)
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    "nacos.example.test",
                    ("192.0.2.0/24",),
                    frozenset({8848, 9848}),
                ),
            )
        )
        credentials = NacosGrpcTlsCredentials(root_certificates=b"private-ca")
        grpc_client = object()

        with patch.object(
            rule_publication_worker_composition,
            "NacosGrpcTransport",
            return_value=grpc_client,
        ) as create_grpc_transport:
            worker = rule_publication_worker_composition.create_nacos_rule_publication_worker(
                bridge,
                target_policy=policy,
                credential_resolver=_UnusedCredentialResolver(),
                credential_reference_resolver=None,
                profile_id="sentinel-profile-v1",
                grpc_tls_credentials=credentials,
                clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
            )

        create_grpc_transport.assert_called_once_with(credentials)
        self.assertIsInstance(worker, RunRulePublicationWorker)
        await provider.dispose()


class _UnusedCredentialResolver:
    async def resolve_credentials(self, source_id, source_revision, provider):
        raise AssertionError("empty outbox must not resolve source credentials")


class _UnconfiguredLocatorStore:
    async def read(self):
        return None


def _target_policy(
    provider: ConfigurationSourceProvider,
    hostname: str,
    ports: frozenset[int],
) -> RegisteredSourceTargetPolicy:
    return RegisteredSourceTargetPolicy(
        (
            RegisteredSourceTargetRule.create(
                provider,
                hostname,
                ("192.0.2.0/24",),
                ports,
            ),
        )
    )


if __name__ == "__main__":
    unittest.main()
