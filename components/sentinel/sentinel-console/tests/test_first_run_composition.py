"""Composition tests for the production first-run ASGI dependency graph."""

from __future__ import annotations

import ssl
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from atlas_richie.sentinel_console.application.bootstrap_database_check import (
    BootstrapDatabaseKind,
)
from atlas_richie.sentinel_console.application.run_rule_activation_plan_worker import (
    RunRuleActivationPlanWorker,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_connector import (
    BootstrapDatabaseConnector,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetPolicy,
    BootstrapDatabaseTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcTlsCredentials,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    first_run_composition,
)
from atlas_richie.sentinel_console.infrastructure.persistence.bootstrap_authorization_file_authority import (
    BootstrapAuthorizationConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.first_run_composition import (
    FirstRunSqlIdentityConfiguration,
    build_first_run_sql_identity_app,
)
from atlas_richie.sentinel_console.infrastructure.persistence.login_attempt_configuration import (
    LoginAttemptLimitConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_work_queue import (
    SqlAlchemyRuleActivationPlanWorkQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
    SqlAlchemyRuleBindingDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_store import (
    SqlAlchemyRuleMutationStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.setup_window_configuration import (
    SetupWindowConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.rule_set_snapshot_reader import (
    RegisteredRuleSetSnapshotReader,
)
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.registered_source_keys import (
    RegisteredSourceKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.rule_command_keys import (
    RuleCommandKeyConfiguration,
)


class FirstRunCompositionTests(unittest.TestCase):
    def test_composes_one_first_run_application_without_connecting(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            directory = Path(temporary)
            protocols_reader = object()
            connections_reader = object()
            audit_reader = object()
            observation_catalog_reader = object()
            instance_catalog_reader = object()
            instance_observation_reader = object()
            metrics_reader = object()
            fleet_overview_reader = object()
            incident_timeline_reader = object()
            incident_evidence_reader = object()
            rule_mutation_binding_reader = object()
            rule_command_keys = RuleCommandKeyConfiguration(
                "rule-active", {"rule-active": b"r" * 32}
            )
            publication_worker = object()
            activation_plan_worker = object()
            migration_adapter = object()
            registered_source_checker = object()
            registered_source_ssl_context = ssl.create_default_context()
            configuration = FirstRunSqlIdentityConfiguration(
                setup_window=SetupWindowConfiguration(directory / "setup.json"),
                runtime_locator=RuntimeDatabaseLocatorConfiguration(
                    directory / "runtime.json", "active", {"active": b"r" * 32}
                ),
                bootstrap_authorization=BootstrapAuthorizationConfiguration(
                    directory / "authorization.json",
                    "operator-code-" + "x" * 24,
                    b"b" * 32,
                ),
                initialization_lock_path=directory / "initialize.lock",
                database_target_policy=BootstrapDatabaseTargetPolicy(
                    [
                        BootstrapDatabaseTargetRule.create(
                            BootstrapDatabaseKind.POSTGRESQL,
                            "10.0.0.0/8",
                            frozenset({5432}),
                        )
                    ]
                ),
                bootstrap_idempotency_key=b"i" * 32,
                login_attempt_limit=LoginAttemptLimitConfiguration(5, 300, 300),
                account_command_keys=AccountCommandKeyConfiguration(
                    "active", {"active": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
                registered_source_keys=RegisteredSourceKeyConfiguration(
                    "source-active",
                    {"source-active": b"s" * 32},
                    "fingerprint-active",
                    {"fingerprint-active": b"f" * 32},
                ),
                allowed_browser_origins=frozenset({"https://console.example"}),
                registered_source_ssl_context=registered_source_ssl_context,
                registered_source_target_rules=(
                    first_run_composition.RegisteredSourceTargetRule.create(
                        first_run_composition.ConfigurationSourceProvider.CONSUL,
                        "consul.example.test",
                        ("192.0.2.0/24",),
                        frozenset({8500}),
                    ),
                ),
                system_protocols_reader=protocols_reader,
                system_connections_reader=connections_reader,
                system_audit_reader=audit_reader,
                observation_catalog_reader=observation_catalog_reader,
                instance_catalog_reader=instance_catalog_reader,
                instance_observation_reader=instance_observation_reader,
                metrics_reader=metrics_reader,
                fleet_overview_reader=fleet_overview_reader,
                incident_timeline_reader=incident_timeline_reader,
                incident_evidence_reader=incident_evidence_reader,
                rule_publication_worker=publication_worker,
                rule_activation_plan_worker=activation_plan_worker,
                rule_command_keys=rule_command_keys,
                rule_mutation_binding_reader=rule_mutation_binding_reader,
                migration_dialect_adapters=(migration_adapter,),
            )

            with (
                patch.object(
                    first_run_composition,
                    "compose_provider_registered_source_checker",
                    return_value=registered_source_checker,
                ) as checker_factory,
                patch.object(
                    first_run_composition, "build_sql_identity_app"
                ) as identity_builder,
                patch.object(
                    first_run_composition,
                    "SqlAlchemyBootstrapInitializationCoordinator",
                    wraps=(
                        first_run_composition.SqlAlchemyBootstrapInitializationCoordinator
                    ),
                ) as coordinator_factory,
            ):
                identity_builder.return_value = object()
                build_first_run_sql_identity_app(configuration)
            self.assertIs(
                checker_factory.call_args.kwargs["ssl_context"],
                registered_source_ssl_context,
            )
            self.assertEqual(
                coordinator_factory.call_args.kwargs["migration_dialect_adapters"],
                (migration_adapter,),
            )
            self.assertIs(
                identity_builder.call_args.kwargs["registered_source_checker"],
                registered_source_checker,
            )
            self.assertIsInstance(
                identity_builder.call_args.kwargs["bootstrap_database_checker"],
                BootstrapDatabaseConnector,
            )
            self.assertIs(
                identity_builder.call_args.kwargs["system_protocols_reader"],
                protocols_reader,
            )
            self.assertIs(
                identity_builder.call_args.kwargs["system_connections_reader"],
                connections_reader,
            )
            self.assertIs(
                identity_builder.call_args.kwargs["system_audit_reader"],
                audit_reader,
            )
            for name, reader in (
                ("observation_catalog_reader", observation_catalog_reader),
                ("instance_catalog_reader", instance_catalog_reader),
                ("instance_observation_reader", instance_observation_reader),
                ("metrics_reader", metrics_reader),
                ("fleet_overview_reader", fleet_overview_reader),
                ("incident_timeline_reader", incident_timeline_reader),
                ("incident_evidence_reader", incident_evidence_reader),
            ):
                self.assertIs(identity_builder.call_args.kwargs[name], reader)
            self.assertIs(
                identity_builder.call_args.kwargs["rule_publication_worker"],
                publication_worker,
            )
            self.assertIs(
                identity_builder.call_args.kwargs["rule_activation_plan_worker"],
                activation_plan_worker,
            )
            mutation_authority = identity_builder.call_args.kwargs[
                "rule_mutation_authority"
            ]
            self.assertIsInstance(mutation_authority, SqlAlchemyRuleMutationStore)
            self.assertIs(
                mutation_authority._binding_reader, rule_mutation_binding_reader
            )
            self.assertIsNone(identity_builder.call_args.kwargs["rule_command_keys"])
            self.assertIsNone(
                identity_builder.call_args.kwargs["rule_mutation_binding_reader"]
            )

            read_only_managed_configuration = replace(
                configuration,
                rule_publication_worker=None,
                rule_publication_providers=None,
                rule_publication_profile_id=None,
                rule_command_keys=None,
                rule_mutation_binding_reader=None,
                managed_rule_binding_ids=frozenset({"binding-managed-read-only"}),
            )
            with patch.object(
                first_run_composition, "build_sql_identity_app"
            ) as read_only_identity_builder:
                read_only_identity_builder.return_value = object()
                build_first_run_sql_identity_app(read_only_managed_configuration)

            read_only_reader = read_only_identity_builder.call_args.kwargs[
                "rule_set_snapshot_reader"
            ]
            self.assertIsInstance(read_only_reader, RegisteredRuleSetSnapshotReader)
            self.assertIsNone(
                read_only_identity_builder.call_args.kwargs["rule_publication_worker"]
            )
            composed_binding_reader = identity_builder.call_args.kwargs[
                "rule_binding_reader"
            ]
            self.assertIsInstance(
                composed_binding_reader, SqlAlchemyRuleBindingDirectoryReader
            )
            self.assertIs(
                identity_builder.call_args.kwargs["rule_binding_scope_reader"],
                composed_binding_reader,
            )
            self.assertIs(composed_binding_reader._engine, identity_builder.call_args.args[0])

            default_sql_configuration = replace(
                configuration, rule_mutation_binding_reader=None
            )
            with patch.object(
                first_run_composition, "build_sql_identity_app"
            ) as identity_builder:
                identity_builder.return_value = object()
                build_first_run_sql_identity_app(default_sql_configuration)
            default_authority = identity_builder.call_args.kwargs[
                "rule_mutation_authority"
            ]
            self.assertIsInstance(default_authority, SqlAlchemyRuleMutationStore)
            default_reader = default_authority._binding_reader
            self.assertIsInstance(default_reader, SqlAlchemyRuleBindingDirectoryReader)
            self.assertIs(default_reader._engine, identity_builder.call_args.args[0])

            app = build_first_run_sql_identity_app(configuration)

            route_paths = {route.path for route in app.routes}
            self.assertIn("/api/v1/system/bootstrap/authorize", route_paths)
            self.assertIn("/api/v1/system/bootstrap", route_paths)
            self.assertFalse((directory / "setup.json").exists())
            self.assertFalse((directory / "runtime.json").exists())
            self.assertFalse((directory / "authorization.json").exists())

    def test_explicit_publication_worker_is_composed_without_provider_io(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            directory = Path(temporary)
            source_ssl_context = ssl.create_default_context()
            configuration = FirstRunSqlIdentityConfiguration(
                setup_window=SetupWindowConfiguration(directory / "setup.json"),
                runtime_locator=RuntimeDatabaseLocatorConfiguration(
                    directory / "runtime.json", "active", {"active": b"r" * 32}
                ),
                bootstrap_authorization=BootstrapAuthorizationConfiguration(
                    directory / "authorization.json",
                    "operator-code-" + "x" * 24,
                    b"b" * 32,
                ),
                initialization_lock_path=directory / "initialize.lock",
                database_target_policy=BootstrapDatabaseTargetPolicy(
                    [
                        BootstrapDatabaseTargetRule.create(
                            BootstrapDatabaseKind.POSTGRESQL,
                            "10.0.0.0/8",
                            frozenset({5432}),
                        )
                    ]
                ),
                bootstrap_idempotency_key=b"i" * 32,
                login_attempt_limit=LoginAttemptLimitConfiguration(5, 300, 300),
                account_command_keys=AccountCommandKeyConfiguration(
                    "active", {"active": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
                registered_source_keys=RegisteredSourceKeyConfiguration(
                    "source-active",
                    {"source-active": b"s" * 32},
                    "fingerprint-active",
                    {"fingerprint-active": b"f" * 32},
                ),
                allowed_browser_origins=frozenset({"https://console.example"}),
                registered_source_ssl_context=source_ssl_context,
                registered_source_target_rules=(
                    first_run_composition.RegisteredSourceTargetRule.create(
                        first_run_composition.ConfigurationSourceProvider.CONSUL,
                        "consul.example.test",
                        ("192.0.2.0/24",),
                        frozenset({8501}),
                    ),
                ),
                rule_command_keys=RuleCommandKeyConfiguration(
                    "rule-active", {"rule-active": b"k" * 32}
                ),
                rule_publication_providers=(
                    first_run_composition.ConfigurationSourceProvider.CONSUL,
                ),
                rule_publication_profile_id="sentinel-profile-v1",
            )
            worker = object()
            with self.assertRaisesRegex(
                ValueError, "requires an enabled Nacos provider"
            ):
                replace(
                    configuration,
                    nacos_grpc_tls_credentials=NacosGrpcTlsCredentials(
                        root_certificates=b"deployment-ca"
                    ),
                )
            with (
                patch.object(
                    first_run_composition,
                    "create_rule_publication_worker",
                    return_value=worker,
                ) as worker_factory,
                patch.object(
                    first_run_composition, "build_sql_identity_app"
                ) as app_builder,
            ):
                app_builder.return_value = object()
                build_first_run_sql_identity_app(configuration)

            self.assertIs(
                app_builder.call_args.kwargs["rule_publication_worker"], worker
            )
            snapshot_reader = app_builder.call_args.kwargs[
                "rule_set_snapshot_reader"
            ]
            self.assertIsInstance(snapshot_reader, RegisteredRuleSetSnapshotReader)
            self.assertEqual(
                set(snapshot_reader._provider_adapters),
                {first_run_composition.ConfigurationSourceProvider.CONSUL},
            )
            self.assertEqual(
                worker_factory.call_args.kwargs["profile_id"],
                "sentinel-profile-v1",
            )
            self.assertIs(
                worker_factory.call_args.kwargs["ssl_context"],
                source_ssl_context,
            )
            policy = worker_factory.call_args.kwargs["target_policies"][
                first_run_composition.ConfigurationSourceProvider.CONSUL
            ]
            self.assertEqual(
                len(policy._rules),
                1,
            )
            self.assertEqual(policy._rules[0].hostname, "consul.example.test")

            read_only_configuration = replace(
                configuration,
                rule_publication_providers=None,
                rule_publication_profile_id=None,
            )
            with (
                patch.object(
                    first_run_composition,
                    "create_rule_publication_worker",
                ) as disabled_worker_factory,
                patch.object(
                    first_run_composition, "build_sql_identity_app"
                ) as read_only_app_builder,
            ):
                read_only_app_builder.return_value = object()
                build_first_run_sql_identity_app(read_only_configuration)

            disabled_worker_factory.assert_not_called()
            read_only_snapshot_reader = read_only_app_builder.call_args.kwargs[
                "rule_set_snapshot_reader"
            ]
            self.assertIsInstance(
                read_only_snapshot_reader, RegisteredRuleSetSnapshotReader
            )
            self.assertEqual(
                set(read_only_snapshot_reader._provider_adapters),
                {first_run_composition.ConfigurationSourceProvider.CONSUL},
            )
            self.assertIsNone(
                read_only_app_builder.call_args.kwargs["rule_publication_worker"]
            )

            mutation_authority = app_builder.call_args.kwargs["rule_mutation_authority"]
            activation_worker = app_builder.call_args.kwargs[
                "rule_activation_plan_worker"
            ]
            self.assertIsInstance(activation_worker, RunRuleActivationPlanWorker)
            self.assertIs(activation_worker._publication_enqueuer, mutation_authority)
            self.assertIsInstance(
                activation_worker._work_queue, SqlAlchemyRuleActivationPlanWorkQueue
            )
            self.assertEqual(
                worker_factory.call_args.kwargs[
                    "credential_resolver"
                ].__class__.__name__,
                "SqlAlchemyRegisteredSourceStore",
            )

            grpc_credentials = NacosGrpcTlsCredentials(
                root_certificates=b"deployment-ca",
                private_key=b"deployment-key",
                certificate_chain=b"deployment-certificate",
            )
            nacos_configuration = replace(
                configuration,
                registered_source_target_rules=(
                    first_run_composition.RegisteredSourceTargetRule.create(
                        first_run_composition.ConfigurationSourceProvider.NACOS,
                        "nacos.example.test",
                        ("192.0.2.0/24",),
                        frozenset({8848, 9848}),
                    ),
                ),
                rule_publication_providers=(
                    first_run_composition.ConfigurationSourceProvider.NACOS,
                ),
                nacos_grpc_tls_credentials=grpc_credentials,
            )
            with (
                patch.object(
                    first_run_composition,
                    "create_rule_publication_worker",
                    return_value=worker,
                ) as nacos_worker_factory,
                patch.object(
                    first_run_composition, "build_sql_identity_app"
                ) as app_builder,
            ):
                app_builder.return_value = object()
                build_first_run_sql_identity_app(nacos_configuration)

            self.assertIs(
                nacos_worker_factory.call_args.kwargs["grpc_tls_credentials"],
                grpc_credentials,
            )
            self.assertEqual(
                set(app_builder.call_args.kwargs["rule_set_snapshot_reader"]._provider_adapters),
                {first_run_composition.ConfigurationSourceProvider.NACOS},
            )

            both_provider_configuration = replace(
                configuration,
                registered_source_target_rules=(
                    first_run_composition.RegisteredSourceTargetRule.create(
                        first_run_composition.ConfigurationSourceProvider.NACOS,
                        "nacos.example.test",
                        ("192.0.2.0/24",),
                        frozenset({8848, 9848}),
                    ),
                    first_run_composition.RegisteredSourceTargetRule.create(
                        first_run_composition.ConfigurationSourceProvider.CONSUL,
                        "consul.example.test",
                        ("198.51.100.0/24",),
                        frozenset({8501}),
                    ),
                ),
                rule_publication_providers=(
                    first_run_composition.ConfigurationSourceProvider.NACOS,
                    first_run_composition.ConfigurationSourceProvider.CONSUL,
                ),
                nacos_grpc_tls_credentials=grpc_credentials,
            )
            with (
                patch.object(
                    first_run_composition,
                    "create_rule_publication_worker",
                    return_value=worker,
                ) as multi_provider_factory,
                patch.object(
                    first_run_composition, "build_sql_identity_app"
                ) as app_builder,
            ):
                app_builder.return_value = object()
                build_first_run_sql_identity_app(both_provider_configuration)

            provider_policies = multi_provider_factory.call_args.kwargs[
                "target_policies"
            ]
            self.assertEqual(
                set(provider_policies),
                {
                    first_run_composition.ConfigurationSourceProvider.NACOS,
                    first_run_composition.ConfigurationSourceProvider.CONSUL,
                },
            )
            self.assertEqual(
                set(app_builder.call_args.kwargs["rule_set_snapshot_reader"]._provider_adapters),
                set(provider_policies),
            )
            self.assertEqual(
                provider_policies[
                    first_run_composition.ConfigurationSourceProvider.NACOS
                ]
                ._rules[0]
                .hostname,
                "nacos.example.test",
            )
            self.assertEqual(
                provider_policies[
                    first_run_composition.ConfigurationSourceProvider.CONSUL
                ]
                ._rules[0]
                .hostname,
                "consul.example.test",
            )

    def test_requires_absolute_initialization_lock_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "lock path must be absolute"):
            FirstRunSqlIdentityConfiguration(
                setup_window=SetupWindowConfiguration(Path("/tmp/setup.json")),
                runtime_locator=RuntimeDatabaseLocatorConfiguration(
                    Path("/tmp/runtime.json"), "active", {"active": b"r" * 32}
                ),
                bootstrap_authorization=BootstrapAuthorizationConfiguration(
                    Path("/tmp/authorization.json"),
                    "operator-code-" + "x" * 24,
                    b"b" * 32,
                ),
                initialization_lock_path=Path("relative.lock"),
                database_target_policy=BootstrapDatabaseTargetPolicy(
                    [
                        BootstrapDatabaseTargetRule.create(
                            BootstrapDatabaseKind.POSTGRESQL,
                            "10.0.0.0/8",
                            frozenset({5432}),
                        )
                    ]
                ),
                bootstrap_idempotency_key=b"i" * 32,
                login_attempt_limit=LoginAttemptLimitConfiguration(5, 300, 300),
                account_command_keys=AccountCommandKeyConfiguration(
                    "active", {"active": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"c" * 32),
                registered_source_keys=RegisteredSourceKeyConfiguration(
                    "source-active",
                    {"source-active": b"s" * 32},
                    "fingerprint-active",
                    {"fingerprint-active": b"f" * 32},
                ),
                allowed_browser_origins=frozenset({"https://console.example"}),
            )


if __name__ == "__main__":
    unittest.main()
