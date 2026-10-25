"""Deployment environment parsing for first-run Console composition."""

from __future__ import annotations

import base64
import ssl
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from unittest.mock import call, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.persistence.first_run_composition import (
    FirstRunSqlIdentityConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.database_engine_adapters import (
    default_database_engine_adapters,
)
from atlas_richie.sentinel_console.infrastructure.bootstrap_database_targets import (
    BootstrapDatabaseTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.monitoring_target_policy import (
    MonitoringTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.security.rule_command_keys import (
    RuleCommandKeyConfiguration,
)


def _base64_key(value: bytes) -> str:
    return base64.b64encode(value * 32).decode("ascii")


def _environment() -> dict[str, str]:
    return {
        "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": "/private/tmp/console/setup.json",
        "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": "/private/tmp/console/runtime.json",
        "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": "locator-v1",
        "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
            f"locator-v1={_base64_key(b'r')}"
        ),
        "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": "/private/tmp/console/authority.json",
        "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE": "operator-code-" + "x" * 24,
        "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": _base64_key(b"f"),
        "SENTINEL_CONSOLE_BOOTSTRAP_INITIALIZATION_LOCK_PATH": "/private/tmp/console/initialize.lock",
        "SENTINEL_CONSOLE_BOOTSTRAP_IDEMPOTENCY_KEY": _base64_key(b"i"),
        "SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS": (
            "postgresql|10.20.0.0/16|5432;mysql|10.21.0.0/16|3306"
        ),
        "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
            "nacos|nacos.internal|10.30.0.0/16|8848;"
            "consul|consul.internal|10.31.0.0/16|8500"
        ),
        "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "https://console.example",
        "SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS": "10.0.0.0/8",
        "SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD": "5",
        "SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS": "300",
        "SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS": "300",
        "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_ACTIVE_KEY_ID": "account-v1",
        "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_KEY_RING": (
            f"account-v1={_base64_key(b'a')}"
        ),
        "SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY": _base64_key(b"c"),
        "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID": "source-secret-v1",
        "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": (
            f"source-secret-v1={_base64_key(b's')}"
        ),
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID": "source-fingerprint-v1",
        "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING": (
            f"source-fingerprint-v1={_base64_key(b'p')}"
        ),
    }


class FirstRunDeploymentConfigurationTests(unittest.TestCase):
    def test_database_adapter_registry_is_an_explicit_composition_input(self) -> None:
        registry = default_database_engine_adapters()
        check_adapter = object()
        migration_adapter = object()

        class FutureDatabaseKind(StrEnum):
            FUTURE = "future"

        target_rule = BootstrapDatabaseTargetRule.create(
            FutureDatabaseKind.FUTURE, "10.40.0.0/16", frozenset({7443})
        )

        configuration = FirstRunSqlIdentityConfiguration.from_environment(
            _environment(),
            database_adapter_registry=registry,
            bootstrap_database_check_adapters=(check_adapter,),
            additional_database_target_rules=(target_rule,),
            migration_dialect_adapters=(migration_adapter,),
        )

        self.assertIs(configuration.database_adapter_registry, registry)
        self.assertEqual(
            configuration.bootstrap_database_check_adapters, (check_adapter,)
        )
        self.assertEqual(configuration.migration_dialect_adapters, (migration_adapter,))
        self.assertIn(target_rule, configuration.database_target_policy._rules)

    def test_loads_explicit_network_security_and_key_configuration(self) -> None:
        configuration = FirstRunSqlIdentityConfiguration.from_environment(
            _environment()
        )

        self.assertEqual(len(configuration.database_target_policy._rules), 2)
        self.assertEqual(len(configuration.registered_source_target_rules), 2)
        self.assertEqual(
            configuration.allowed_browser_origins,
            frozenset({"https://console.example"}),
        )
        self.assertEqual(
            len(configuration.client_address_resolver.trusted_proxy_networks), 1
        )
        self.assertEqual(configuration.mysql_ssl_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(configuration.mysql_ssl_context.check_hostname)
        self.assertNotIn("operator-code-", repr(configuration))
        self.assertNotIn("account-v1=", repr(configuration))

    def test_loopback_install_composes_without_operator_code_but_remote_does_not(
        self,
    ) -> None:
        environment = _environment()
        environment.pop("SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE")
        environment.pop("SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS")
        environment["SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS"] = (
            "http://127.0.0.1:8000,http://localhost:8000"
        )

        local = FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertTrue(local.bootstrap_authorization.allow_loopback_without_code)

        remote_environment = {
            **environment,
            "SENTINEL_CONSOLE_BIND_HOST": "0.0.0.0",
        }
        with self.assertRaisesRegex(ValueError, "deployment configuration"):
            FirstRunSqlIdentityConfiguration.from_environment(remote_environment)

    def test_monitoring_target_grants_are_optional_and_deployment_owned(self) -> None:
        environment = _environment()
        without_grant = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertIsNone(without_grant.monitoring_target_rules)

        environment["SENTINEL_CONSOLE_MONITORING_TARGETS"] = (
            "127.0.0.1|127.0.0.0/8|9090|loopback-http"
        )
        configured = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertEqual(len(configured.monitoring_target_rules or ()), 1)
        self.assertIsInstance(configured.monitoring_target_rules[0], MonitoringTargetRule)

    def test_monitoring_target_grants_fail_closed_for_unsafe_http_scope(self) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_MONITORING_TARGETS"] = (
            "prometheus.example|8.8.8.8/32|9090|private-http"
        )

        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(environment)

    def test_loads_rule_command_keys_only_with_host_owned_exact_binding_reader(
        self,
    ) -> None:
        environment = _environment()
        rule_key = b"rule-command-deployment-key-" + b"r" * 32
        environment["SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"] = (
            "rule-v1"
        )
        environment["SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING"] = (
            f"rule-v1={base64.b64encode(rule_key).decode('ascii')}"
        )
        binding_reader = object()

        configuration = FirstRunSqlIdentityConfiguration.from_environment(
            environment, rule_mutation_binding_reader=binding_reader
        )

        self.assertIsInstance(
            configuration.rule_command_keys, RuleCommandKeyConfiguration
        )
        self.assertEqual(
            configuration.rule_command_keys.fingerprint_keys["rule-v1"], rule_key
        )
        self.assertIs(configuration.rule_mutation_binding_reader, binding_reader)
        self.assertNotIn(rule_key.decode("ascii"), repr(configuration))

        standard_sql = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertIsInstance(
            standard_sql.rule_command_keys, RuleCommandKeyConfiguration
        )
        self.assertIsNone(standard_sql.rule_mutation_binding_reader)

    def test_rule_publication_is_disabled_unless_provider_is_explicit(self) -> None:
        environment = _environment()
        disabled = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertIsNone(disabled.rule_publication_providers)
        self.assertIsNone(disabled.rule_publication_profile_id)

        rule_key = b"rule-command-deployment-key-" + b"r" * 32
        environment.update(
            {
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": "rule-v1",
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                    f"rule-v1={base64.b64encode(rule_key).decode('ascii')}"
                ),
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "consul",
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": "sentinel-profile-v1",
            }
        )
        configured = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertEqual(
            configured.rule_publication_providers,
            (ConfigurationSourceProvider.CONSUL,),
        )
        self.assertEqual(configured.rule_publication_profile_id, "sentinel-profile-v1")

    def test_managed_publication_is_explicitly_allowlisted_by_binding(self) -> None:
        environment = _environment()
        environment.update(
            {
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": "rule-v1",
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                    f"rule-v1={_base64_key(b'r')}"
                ),
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos",
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": "sentinel-profile-v1",
                "SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS": "binding-a,binding-b",
            }
        )

        configured = FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertEqual(
            configured.managed_rule_binding_ids,
            frozenset({"binding-a", "binding-b"}),
        )

        environment["SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS"] = (
            "binding-a,binding-a"
        )
        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        environment["SENTINEL_CONSOLE_MANAGED_RULE_BINDING_IDS"] = "binding-a"
        environment.pop("SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS")
        environment.pop("SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID")
        read_only = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertEqual(read_only.managed_rule_binding_ids, frozenset({"binding-a"}))
        self.assertIsNone(read_only.rule_publication_providers)
        self.assertIsNone(read_only.rule_publication_profile_id)

    def test_loads_both_rule_publication_providers_and_legacy_singleton(self) -> None:
        environment = _environment()
        environment.update(
            {
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": "rule-v1",
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                    f"rule-v1={_base64_key(b'r')}"
                ),
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos,consul",
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": "sentinel-profile-v1",
            }
        )
        configured = FirstRunSqlIdentityConfiguration.from_environment(environment)
        self.assertEqual(
            configured.rule_publication_providers,
            (ConfigurationSourceProvider.NACOS, ConfigurationSourceProvider.CONSUL),
        )

        legacy_environment = _environment()
        legacy_environment.update(
            {
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": "rule-v1",
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                    f"rule-v1={_base64_key(b'r')}"
                ),
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDER": "consul",
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": "sentinel-profile-v1",
            }
        )
        self.assertEqual(
            FirstRunSqlIdentityConfiguration.from_environment(
                legacy_environment
            ).rule_publication_providers,
            (ConfigurationSourceProvider.CONSUL,),
        )

    def test_rejects_ambiguous_or_unauthorized_multi_provider_configuration(
        self,
    ) -> None:
        base = _environment()
        base.update(
            {
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": "rule-v1",
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                    f"rule-v1={_base64_key(b'r')}"
                ),
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": "sentinel-profile-v1",
            }
        )
        for values in (
            {
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos,nacos",
            },
            {
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos, consul",
            },
            {
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos,unknown",
            },
            {
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos,consul",
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDER": "consul",
            },
            {
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos,consul",
                "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                    "consul|consul.internal|10.31.0.0/16|8500"
                ),
            },
        ):
            with (
                self.subTest(values=values),
                self.assertRaisesRegex(ValueError, "configuration is incomplete"),
            ):
                FirstRunSqlIdentityConfiguration.from_environment({**base, **values})

    def test_rejects_incomplete_or_unapproved_publication_configuration(self) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS"] = "consul"
        environment["SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID"] = (
            "sentinel-profile-v1"
        )
        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        environment["SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"] = (
            "rule-v1"
        )
        environment["SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING"] = (
            f"rule-v1={_base64_key(b'r')}"
        )
        environment["SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS"] = "unknown"
        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        environment["SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS"] = "nacos"
        environment["SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS"] = (
            "consul|consul.internal|10.31.0.0/16|8500"
        )
        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(environment)

    def test_rejects_invalid_key_ring_or_reader_without_rule_command_keys(self) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"] = (
            "rule-v1"
        )
        environment["SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING"] = (
            f"rule-v1={_base64_key(b'r')}"
        )

        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(
                _environment(), rule_mutation_binding_reader=object()
            )
        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(
                {
                    **environment,
                    "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": "bad",
                },
                rule_mutation_binding_reader=object(),
            )

    def test_direct_configuration_enforces_one_rule_mutation_composition_path(
        self,
    ) -> None:
        configuration = FirstRunSqlIdentityConfiguration.from_environment(
            _environment()
        )
        keys = RuleCommandKeyConfiguration("rule-v1", {"rule-v1": b"r" * 32})

        composed = replace(configuration, rule_command_keys=keys)
        self.assertIsNone(composed.rule_mutation_binding_reader)
        with self.assertRaisesRegex(ValueError, "requires rule-command keys"):
            replace(configuration, rule_mutation_binding_reader=object())
        with self.assertRaisesRegex(ValueError, "either a rule mutation authority"):
            replace(
                configuration,
                rule_mutation_authority=object(),
                rule_command_keys=keys,
                rule_mutation_binding_reader=object(),
            )

    def test_accepts_absolute_private_database_ca_paths(self) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"] = (
            "/etc/sentinel/postgres-ca.pem"
        )
        environment["SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"] = (
            "/etc/sentinel/mysql-ca.pem"
        )
        environment["SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE"] = (
            "/etc/sentinel/source-ca.pem"
        )
        environment["SENTINEL_CONSOLE_DASHBOARD_BASE_PATH"] = "/ops/sentinel/"

        database_context = ssl.create_default_context()
        source_context = ssl.create_default_context()
        with patch(
            "atlas_richie.sentinel_console.infrastructure.persistence."
            "first_run_composition.ssl.create_default_context",
            side_effect=[database_context, source_context],
        ) as create_context:
            configuration = FirstRunSqlIdentityConfiguration.from_environment(
                environment
            )

        self.assertEqual(
            configuration.postgresql_root_certificate,
            "/etc/sentinel/postgres-ca.pem",
        )
        create_context.assert_has_calls(
            [
                call(cafile="/etc/sentinel/mysql-ca.pem"),
                call(cafile="/etc/sentinel/source-ca.pem"),
            ]
        )
        self.assertEqual(configuration.mysql_ssl_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(configuration.mysql_ssl_context.check_hostname)
        self.assertIs(configuration.registered_source_ssl_context, source_context)
        self.assertEqual(configuration.dashboard_base_path, "/ops/sentinel/")

    def test_rejects_relative_database_ca_path_without_echoing_path(self) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"] = "secrets/mysql-ca.pem"

        with self.assertRaisesRegex(
            ValueError, "configuration is incomplete or invalid"
        ) as error:
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertNotIn("secrets/mysql-ca.pem", str(error.exception))

    def test_rejects_relative_registered_source_ca_path_without_echoing_path(
        self,
    ) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE"] = (
            "secrets/source-ca.pem"
        )

        with self.assertRaisesRegex(
            ValueError, "configuration is incomplete or invalid"
        ) as error:
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertNotIn("secrets/source-ca.pem", str(error.exception))

    def test_loads_registered_source_ca_bundle_as_verified_tls_trust(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Sentinel test CA")]
        )
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .sign(private_key, hashes.SHA256())
        )
        with tempfile.TemporaryDirectory(prefix="sentinel-source-ca-") as temporary:
            certificate_path = Path(temporary) / "source-ca.pem"
            certificate_path.write_bytes(
                certificate.public_bytes(serialization.Encoding.PEM)
            )
            environment = _environment()
            environment["SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE"] = str(
                certificate_path
            )

            configuration = FirstRunSqlIdentityConfiguration.from_environment(
                environment
            )

        self.assertIsNotNone(configuration.registered_source_ssl_context)
        self.assertEqual(
            configuration.registered_source_ssl_context.verify_mode,
            ssl.CERT_REQUIRED,
        )
        self.assertTrue(configuration.registered_source_ssl_context.check_hostname)
        self.assertIn(
            certificate.public_bytes(serialization.Encoding.DER),
            configuration.registered_source_ssl_context.get_ca_certs(binary_form=True),
        )

    def test_loads_nacos_grpc_trust_and_mutual_tls_material_from_files(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sentinel-nacos-grpc-tls-"
        ) as temporary:
            directory = Path(temporary)
            ca_path = directory / "nacos-ca.pem"
            certificate_path = directory / "console-client.pem"
            key_path = directory / "console-client-key.pem"
            ca_path.write_bytes(b"nacos-test-ca")
            certificate_path.write_bytes(b"nacos-client-certificate")
            key_path.write_bytes(b"nacos-client-private-key")
            rule_key = b"rule-command-deployment-key-" + b"r" * 32
            environment = _environment()
            command_key_id_env = (
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"
            )
            publication_profile_env = "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID"
            environment.update(
                {
                    "SENTINEL_CONSOLE_NACOS_GRPC_ROOT_CERTIFICATE": str(ca_path),
                    "SENTINEL_CONSOLE_NACOS_GRPC_CLIENT_CERTIFICATE": str(
                        certificate_path
                    ),
                    "SENTINEL_CONSOLE_NACOS_GRPC_CLIENT_PRIVATE_KEY": str(key_path),
                    "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                        "nacos|nacos.internal|10.30.0.0/16|8848,9848"
                    ),
                    command_key_id_env: "rule-v1",
                    "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                        f"rule-v1={base64.b64encode(rule_key).decode('ascii')}"
                    ),
                    "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos",
                    publication_profile_env: "sentinel-profile-v1",
                }
            )

            configuration = FirstRunSqlIdentityConfiguration.from_environment(
                environment
            )

        credentials = configuration.nacos_grpc_tls_credentials
        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.root_certificates, b"nacos-test-ca")
        self.assertEqual(credentials.certificate_chain, b"nacos-client-certificate")
        self.assertEqual(credentials.private_key, b"nacos-client-private-key")
        self.assertNotIn("nacos-client-private-key", repr(configuration))
        self.assertNotIn("nacos-client-private-key", repr(credentials))

    def test_rejects_partial_nacos_grpc_client_identity(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sentinel-nacos-grpc-tls-"
        ) as temporary:
            certificate_path = Path(temporary) / "client.pem"
            certificate_path.write_bytes(b"client-certificate")
            environment = _environment()
            command_key_id_env = (
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID"
            )
            publication_profile_env = "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID"
            environment.update(
                {
                    "SENTINEL_CONSOLE_NACOS_GRPC_CLIENT_CERTIFICATE": str(
                        certificate_path
                    ),
                    "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                        "nacos|nacos.internal|10.30.0.0/16|8848,9848"
                    ),
                    command_key_id_env: "rule-v1",
                    "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                        f"rule-v1={_base64_key(b'r')}"
                    ),
                    "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos",
                    publication_profile_env: "sentinel-profile-v1",
                }
            )

            with self.assertRaisesRegex(
                ValueError, "configuration is incomplete"
            ) as error:
                FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertNotIn("client.pem", str(error.exception))

    def test_rejects_nacos_grpc_tls_material_for_consul_provider(self) -> None:
        environment = _environment()
        environment.update(
            {
                "SENTINEL_CONSOLE_NACOS_GRPC_ROOT_CERTIFICATE": (
                    "/etc/sentinel/nacos-ca.pem"
                ),
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": "rule-v1",
                "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": _base64_key(b"r"),
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "consul",
                "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": "sentinel-profile-v1",
            }
        )

        with self.assertRaisesRegex(ValueError, "configuration is incomplete"):
            FirstRunSqlIdentityConfiguration.from_environment(environment)

    def test_rejects_wildcard_database_target_with_generic_error(self) -> None:
        environment = _environment()
        environment["SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS"] = (
            "postgresql|0.0.0.0/0|5432"
        )

        with self.assertRaisesRegex(
            ValueError, "configuration is incomplete or invalid"
        ) as error:
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertNotIn("operator-code-", str(error.exception))

    def test_missing_required_secret_is_not_reported_by_value(self) -> None:
        environment = _environment()
        environment.pop("SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE")

        with self.assertRaisesRegex(
            ValueError, "configuration is incomplete or invalid"
        ) as error:
            FirstRunSqlIdentityConfiguration.from_environment(environment)

        self.assertNotIn("operator-code-", str(error.exception))

    def test_rejects_overlapping_local_authority_paths(self) -> None:
        configuration = FirstRunSqlIdentityConfiguration.from_environment(
            _environment()
        )

        with self.assertRaisesRegex(ValueError, "state paths must be distinct"):
            replace(
                configuration,
                initialization_lock_path=configuration.setup_window.path,
            )

    def test_rejects_non_positive_session_lifetime(self) -> None:
        configuration = FirstRunSqlIdentityConfiguration.from_environment(
            _environment()
        )

        with self.assertRaisesRegex(ValueError, "session lifetime must be positive"):
            replace(configuration, session_ttl=timedelta(0))


if __name__ == "__main__":
    unittest.main()
