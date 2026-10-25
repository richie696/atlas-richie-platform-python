"""Composition tests for the existing SQL identity use cases."""

from __future__ import annotations

import ssl
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from atlas_richie.sentinel_console import app as console_app
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_target_policy import (
    MonitoringTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    identity_composition,
    login_attempt_configuration,
    metrics_observation_catalog_reader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.incident_event_adapter import (
    SQLAlchemyIncidentEventAdapter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_fleet_overview_reader import (
    SQLAlchemyMetricsFleetOverviewReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_reader import (
    SQLAlchemyMetricsHistoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_instance_catalog_reader import (
    SQLAlchemyMetricsInstanceCatalogReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_instance_observation_reader import (
    SQLAlchemyMetricsInstanceObservationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
    SqlAlchemyRuleBindingDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.security import (
    registered_source_keys,
)
from atlas_richie.sentinel_console.infrastructure.security.account_command_keys import (
    AccountCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.client_identity_key import (
    ClientIdentityKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.rule_command_keys import (
    RuleCommandKeyConfiguration,
)


class SqlIdentityCompositionTests(unittest.TestCase):
    def test_composes_instance_detail_reader_by_default(self) -> None:
        runtime = unittest.mock.Mock()
        with (
            patch.object(
                identity_composition,
                "compose_sql_identity_runtime",
                return_value=runtime,
            ),
            patch.object(console_app, "build_app") as build_app,
        ):
            identity_composition.build_sql_identity_app(
                object(),
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 60, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "current", {"current": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
                session_ttl=timedelta(hours=8),
                setup_window_reader=object(),
                allowed_browser_origins=frozenset({"https://console.example.test"}),
            )

        self.assertIsInstance(
            build_app.call_args.kwargs["instance_observation_reader"],
            SQLAlchemyMetricsInstanceObservationReader,
        )

    def test_monitoring_probe_composition_is_explicit_and_injected(self) -> None:
        engine = object()
        runtime = unittest.mock.Mock()
        probe, receipt_store, checker = object(), object(), object()
        rules = (
            MonitoringTargetRule.create(
                "prometheus.example.test", ("192.0.2.0/24",), frozenset({9090})
            ),
        )
        with (
            patch.object(
                identity_composition,
                "compose_sql_identity_runtime",
                return_value=runtime,
            ),
            patch.object(
                identity_composition,
                "compose_prometheus_http_adapter",
                return_value=probe,
            ) as probe_factory,
            patch.object(
                identity_composition,
                "SQLAlchemyMonitoringProbeReceiptStore",
                return_value=receipt_store,
            ) as receipt_factory,
            patch.object(
                identity_composition,
                "CheckMonitoringSource",
                return_value=checker,
            ) as checker_factory,
            patch.object(console_app, "build_app") as build_app,
        ):
            identity_composition.build_sql_identity_app(
                engine,
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 60, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "current", {"current": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
                session_ttl=timedelta(hours=8),
                setup_window_reader=object(),
                bootstrap_operator_verifier=object(),
                bootstrap_authorization_authority=object(),
                allowed_browser_origins=frozenset({"https://console.example.test"}),
                monitoring_target_rules=rules,
                monitoring_fingerprint_key=b"monitoring-fingerprint-key-000000000000",
            )
        probe_factory.assert_called_once_with(rules, ssl_context=None)
        receipt_factory.assert_called_once()
        checker_factory.assert_called_once_with(
            probe,
            receipt_store,
            fingerprint_key=b"monitoring-fingerprint-key-000000000000",
        )
        self.assertIs(build_app.call_args.kwargs["monitoring_source_checker"], checker)
        self.assertIs(
            build_app.call_args.kwargs["monitoring_probe_receipt_reader"],
            receipt_store,
        )

    def test_registered_source_checker_composition_receives_deployment_tls_trust(
        self,
    ) -> None:
        engine = object()
        runtime = unittest.mock.Mock()
        checker = object()
        context = ssl.create_default_context()
        rules = (
            identity_composition.RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.NACOS,
                "nacos.example.test",
                ("192.0.2.0/24",),
                frozenset({8848}),
            ),
        )
        with (
            patch.object(
                identity_composition,
                "compose_sql_identity_runtime",
                return_value=runtime,
            ),
            patch.object(
                identity_composition,
                "compose_provider_registered_source_checker",
                return_value=checker,
            ) as checker_factory,
            patch.object(console_app, "build_app") as build_app,
        ):
            identity_composition.build_sql_identity_app(
                engine,
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 60, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "current", {"current": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
                session_ttl=timedelta(hours=8),
                setup_window_reader=object(),
                bootstrap_operator_verifier=object(),
                bootstrap_authorization_authority=object(),
                allowed_browser_origins=frozenset({"https://console.example.test"}),
                registered_source_target_rules=rules,
                registered_source_ssl_context=context,
            )

        checker_factory.assert_called_once_with(rules, ssl_context=context)
        self.assertIs(build_app.call_args.kwargs["registered_source_checker"], checker)

    def test_sql_identity_composition_defaults_to_durable_system_audit_reader(
        self,
    ) -> None:
        engine = object()
        runtime = unittest.mock.Mock()
        audit_reader = object()
        with (
            patch.object(
                identity_composition,
                "compose_sql_identity_runtime",
                return_value=runtime,
            ),
            patch.object(
                identity_composition,
                "SqlAlchemySystemAuditReader",
                return_value=audit_reader,
            ) as sql_audit_reader,
            patch.object(console_app, "build_app") as build_app,
        ):
            identity_composition.build_sql_identity_app(
                engine,
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 60, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "current", {"current": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
                session_ttl=timedelta(hours=8),
                setup_window_reader=object(),
                bootstrap_operator_verifier=object(),
                bootstrap_authorization_authority=object(),
                allowed_browser_origins=frozenset({"https://console.example.test"}),
            )

        sql_audit_reader.assert_called_once_with(engine)
        self.assertIs(build_app.call_args.kwargs["system_audit_reader"], audit_reader)
        self.assertIsInstance(
            build_app.call_args.kwargs["metrics_reader"], SQLAlchemyMetricsHistoryReader
        )
        self.assertIsInstance(
            build_app.call_args.kwargs["instance_catalog_reader"],
            SQLAlchemyMetricsInstanceCatalogReader,
        )
        observation_catalog_reader = build_app.call_args.kwargs[
            "observation_catalog_reader"
        ]
        self.assertIsInstance(
            observation_catalog_reader,
            metrics_observation_catalog_reader.SQLAlchemyMetricsObservationCatalogReader,
        )
        self.assertIsInstance(
            build_app.call_args.kwargs["fleet_overview_reader"],
            SQLAlchemyMetricsFleetOverviewReader,
        )
        incident_timeline_reader = build_app.call_args.kwargs[
            "incident_timeline_reader"
        ]
        self.assertIsInstance(incident_timeline_reader, SQLAlchemyIncidentEventAdapter)
        self.assertIs(
            build_app.call_args.kwargs["incident_evidence_reader"],
            incident_timeline_reader,
        )

    def test_bootstrap_configuration_supplies_both_authorization_ports(self) -> None:
        engine = object()
        runtime = unittest.mock.Mock()
        authority = object()
        configuration = unittest.mock.Mock()
        configuration.create_authority.return_value = authority

        with (
            patch.object(
                identity_composition,
                "compose_sql_identity_runtime",
                return_value=runtime,
            ),
            patch.object(console_app, "build_app") as build_app,
        ):
            identity_composition.build_sql_identity_app(
                engine,
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 60, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "current", {"current": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
                session_ttl=timedelta(hours=8),
                setup_window_reader=object(),
                bootstrap_authorization_configuration=configuration,
                bootstrap_operator_verifier=None,
                allowed_browser_origins=frozenset({"https://console.example.test"}),
            )

        configuration.create_authority.assert_called_once()
        self.assertIs(
            build_app.call_args.kwargs["bootstrap_operator_verifier"], authority
        )
        self.assertIs(
            build_app.call_args.kwargs["bootstrap_authorization_authority"],
            authority,
        )

    def test_lazy_database_composition_requires_bootstrap_coordinator_ports(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "complete bootstrap coordinator"):
            identity_composition.build_sql_identity_app(
                object(),
                attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                    5, 60, 300
                ),
                account_command_keys=AccountCommandKeyConfiguration(
                    "current", {"current": b"a" * 32}
                ),
                client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
                session_ttl=timedelta(hours=8),
                setup_window_reader=object(),
                bootstrap_operator_verifier=object(),
                bootstrap_authorization_authority=object(),
                allowed_browser_origins=frozenset(),
                runtime_database_provider=object(),
            )

    def test_assembles_all_identity_services_with_one_password_hasher(self) -> None:
        engine = object()
        attempt_limit = login_attempt_configuration.LoginAttemptLimitConfiguration(
            5, 60, 300
        )
        account_keys = AccountCommandKeyConfiguration("current", {"current": b"a" * 32})
        identity_key = ClientIdentityKeyConfiguration(b"b" * 32)
        ttl = timedelta(hours=8)

        with (
            patch.object(identity_composition, "PasswordHashService") as hasher,
            patch.object(
                identity_composition, "SqlAlchemyAccountDirectoryReader"
            ) as directory_reader,
            patch.object(
                identity_composition, "SqlAlchemyCurrentSessionReader"
            ) as session_reader,
            patch.object(
                identity_composition, "SqlAlchemyCurrentSessionRevoker"
            ) as session_revoker,
            patch.object(identity_composition, "compose_sql_login") as login,
            patch.object(
                identity_composition, "compose_sql_account_commands"
            ) as account_commands,
            patch.object(
                identity_composition, "SqlAlchemyOwnPasswordCredentialReader"
            ) as password_reader,
            patch.object(
                identity_composition, "SqlAlchemyOwnPasswordWriter"
            ) as password_writer,
            patch.object(
                identity_composition, "SqlAlchemyLoginAttemptLimiter"
            ) as attempt_limiter,
            patch.object(identity_composition, "ChangeOwnPassword") as own_password,
        ):
            runtime = identity_composition.compose_sql_identity_runtime(
                engine,
                attempt_limit=attempt_limit,
                account_command_keys=account_keys,
                client_identity_key=identity_key,
                session_ttl=ttl,
            )

        hasher.assert_called_once_with()
        login.assert_called_once_with(
            engine,
            attempt_limit=attempt_limit,
            session_ttl=ttl,
            password_hasher=hasher.return_value,
            additional_login_attempt_dialect_adapters=(),
        )
        account_commands.assert_called_once_with(
            engine, account_keys, password_hasher=hasher.return_value
        )
        own_password.assert_called_once_with(
            reader=password_reader.return_value,
            writer=password_writer.return_value,
            password_hasher=hasher.return_value,
            attempt_limiter=attempt_limiter.return_value,
            attempt_hmac_key=b"b" * 32,
        )
        attempt_limiter.assert_called_once()
        self.assertIs(attempt_limiter.call_args.args[0], engine)
        self.assertIs(runtime.account_directory_reader, directory_reader.return_value)
        self.assertIs(runtime.current_session_reader, session_reader.return_value)
        self.assertIs(runtime.current_session_revoker, session_revoker.return_value)
        self.assertIs(runtime.login_service, login.return_value)
        self.assertIs(runtime.account_command_service, account_commands.return_value)
        self.assertIs(runtime.own_password_service, own_password.return_value)
        self.assertEqual(runtime.client_identity_hmac_key, b"b" * 32)

    def test_build_sql_identity_app_registers_identity_contracts(self) -> None:
        app = identity_composition.build_sql_identity_app(
            SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
            attempt_limit=login_attempt_configuration.LoginAttemptLimitConfiguration(
                5, 60, 300
            ),
            account_command_keys=AccountCommandKeyConfiguration(
                "current", {"current": b"a" * 32}
            ),
            client_identity_key=ClientIdentityKeyConfiguration(b"b" * 32),
            session_ttl=timedelta(hours=8),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            bootstrap_authorization_authority=object(),
            allowed_browser_origins=frozenset({"https://console.example.test"}),
        )

        paths = {route.path for route in app.routes}
        self.assertTrue(
            {
                "/api/v1/auth/login",
                "/api/v1/auth/me",
                "/api/v1/auth/logout",
                "/api/v1/auth/password",
                "/api/v1/accounts",
                "/api/v1/accounts/commands",
                "/api/v1/system/audit",
            }.issubset(paths)
        )

    def test_builds_identity_routes_with_deployment_bootstrap_authorities(self) -> None:
        engine = object()
        runtime = unittest.mock.Mock()
        setup_window = object()
        operator_verifier = object()
        initialization_authority = object()
        initialization_coordinator = object()
        initialization_operations = object()
        database_checker = object()
        origins = frozenset({"https://console.example.test"})
        source_keys = registered_source_keys.RegisteredSourceKeyConfiguration(
            "secret-current",
            {"secret-current": b"s" * 32},
            "fingerprint-current",
            {"fingerprint-current": b"f" * 32},
        )
        attempt_limit = login_attempt_configuration.LoginAttemptLimitConfiguration(
            5, 60, 300
        )
        account_keys = AccountCommandKeyConfiguration("current", {"current": b"a" * 32})
        identity_key = ClientIdentityKeyConfiguration(b"b" * 32)
        bootstrap_checker = object()
        source_checker = object()
        credential_reference_resolver = object()
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
        rule_command_keys = RuleCommandKeyConfiguration(
            "rule-current", {"rule-current": b"r" * 32}
        )
        binding_reader = object()

        with (
            patch.object(
                identity_composition,
                "compose_sql_identity_runtime",
                return_value=runtime,
            ),
            patch.object(
                identity_composition,
                "SqlAlchemyBootstrapInitializationReader",
            ) as bootstrap_reader,
            patch.object(
                identity_composition, "compose_registered_source_store"
            ) as source_store,
            patch.object(
                identity_composition, "SqlAlchemyRuleDraftReader"
            ) as rule_draft_reader,
            patch.object(
                identity_composition, "SqlAlchemyRuleVersionReader"
            ) as rule_version_reader,
            patch.object(
                identity_composition, "SqlAlchemyRulePublicationReader"
            ) as rule_publication_reader,
            patch.object(
                identity_composition, "SqlAlchemyRulePublicationReceiptStore"
            ) as publication_receipt_store,
            patch.object(
                identity_composition, "SqlAlchemyRuleValidationReceiptStore"
            ) as validation_receipt_store,
            patch.object(
                identity_composition, "compose_sql_rule_mutation_authority"
            ) as rule_mutation_composition,
            patch.object(
                identity_composition, "install_runtime_database_lifecycle"
            ) as install_database_lifecycle,
            patch.object(console_app, "build_app") as build_app,
        ):
            runtime_database_provider = object()
            result = identity_composition.build_sql_identity_app(
                engine,
                attempt_limit=attempt_limit,
                account_command_keys=account_keys,
                client_identity_key=identity_key,
                session_ttl=timedelta(hours=8),
                setup_window_reader=setup_window,
                bootstrap_operator_verifier=operator_verifier,
                bootstrap_authorization_authority=initialization_authority,
                allowed_browser_origins=origins,
                bootstrap_initialization_reader=initialization_coordinator,
                bootstrap_initializer=initialization_coordinator,
                bootstrap_initialization_operation_reader=initialization_operations,
                bootstrap_database_checker=database_checker,
                runtime_database_provider=runtime_database_provider,
                registered_source_keys=source_keys,
                bootstrap_source_checker=bootstrap_checker,
                registered_source_checker=source_checker,
                source_credential_reference_resolver=credential_reference_resolver,
                system_connections_reader=connections_reader,
                system_audit_reader=audit_reader,
                system_protocols_reader=protocols_reader,
                observation_catalog_reader=observation_catalog_reader,
                instance_catalog_reader=instance_catalog_reader,
                instance_observation_reader=instance_observation_reader,
                metrics_reader=metrics_reader,
                fleet_overview_reader=fleet_overview_reader,
                incident_timeline_reader=incident_timeline_reader,
                incident_evidence_reader=incident_evidence_reader,
                rule_command_keys=rule_command_keys,
                rule_mutation_binding_reader=binding_reader,
            )

        bootstrap_reader.assert_not_called()
        source_store.assert_called_once_with(engine, source_keys)
        rule_draft_reader.assert_called_once_with(engine)
        rule_version_reader.assert_called_once_with(engine)
        rule_publication_reader.assert_called_once_with(engine)
        publication_receipt_store.assert_called_once_with(engine)
        validation_receipt_store.assert_called_once_with(engine)
        rule_mutation_composition.assert_called_once_with(
            engine, rule_command_keys, binding_reader=binding_reader
        )
        self.assertIsInstance(
            build_app.call_args.kwargs["rule_binding_reader"],
            SqlAlchemyRuleBindingDirectoryReader,
        )
        build_app.assert_called_once()
        app_arguments = build_app.call_args.kwargs
        for name, value in (
            ("bootstrap_initialization_reader", initialization_coordinator),
            ("setup_window_reader", setup_window),
            ("bootstrap_operator_verifier", operator_verifier),
            ("bootstrap_authorization_authority", initialization_authority),
            ("bootstrap_initializer", initialization_coordinator),
            ("bootstrap_initialization_operation_reader", initialization_operations),
            ("bootstrap_database_checker", database_checker),
            ("bootstrap_source_checker", bootstrap_checker),
            ("source_credential_reference_resolver", credential_reference_resolver),
            ("system_connections_reader", connections_reader),
            ("system_audit_reader", audit_reader),
            ("system_protocols_reader", protocols_reader),
            ("observation_catalog_reader", observation_catalog_reader),
            ("instance_catalog_reader", instance_catalog_reader),
            ("instance_observation_reader", instance_observation_reader),
            ("metrics_reader", metrics_reader),
            ("fleet_overview_reader", fleet_overview_reader),
            ("incident_timeline_reader", incident_timeline_reader),
            ("incident_evidence_reader", incident_evidence_reader),
            ("registered_source_checker", source_checker),
            ("registered_sources_reader", source_store.return_value),
            ("registered_source_credential_resolver", source_store.return_value),
            ("registered_source_probe_recorder", source_store.return_value),
            ("registered_source_mutation_authority", source_store.return_value),
            ("rule_draft_reader", rule_draft_reader.return_value),
            ("rule_draft_detail_reader", rule_draft_reader.return_value),
            ("rule_set_version_reader", rule_version_reader.return_value),
            ("rule_set_version_detail_reader", rule_version_reader.return_value),
            ("rule_publication_reader", rule_publication_reader.return_value),
            ("rule_publication_detail_reader", rule_publication_reader.return_value),
            ("rule_publication_receipt_reader", publication_receipt_store.return_value),
            ("rule_mutation_authority", rule_mutation_composition.return_value),
            (
                "rule_validation_receipt_writer",
                validation_receipt_store.return_value,
            ),
        ):
            with self.subTest(name=name):
                self.assertIs(app_arguments[name], value)
        self.assertIsInstance(
            app_arguments["rule_candidate_profile_validator"],
            identity_composition.SentinelRuleCandidateValidatorRegistry,
        )
        self.assertIsInstance(
            app_arguments["current_session_reader"], unittest.mock.Mock
        )
        self.assertIsInstance(
            app_arguments["rule_binding_reader"], SqlAlchemyRuleBindingDirectoryReader
        )
        self.assertIsInstance(
            app_arguments["rule_publication_target_reader"],
            identity_composition.SqlAlchemyRulePublicationTargetReader,
        )
        self.assertIsInstance(
            app_arguments["rule_activation_plan_reader"],
            identity_composition.SqlAlchemyRuleActivationPlanReader,
        )
        install_database_lifecycle.assert_called_once_with(
            build_app.return_value, runtime_database_provider
        )
        self.assertIs(result, build_app.return_value)


if __name__ == "__main__":
    unittest.main()
