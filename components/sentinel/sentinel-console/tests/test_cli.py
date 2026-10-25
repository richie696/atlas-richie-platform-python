"""Command-level checks for safe setup-window operations and server wiring."""

from __future__ import annotations

import base64
import os
import ssl
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from atlas_richie.sentinel_console.cli import create_application, main


class SentinelConsoleCliTests(unittest.TestCase):
    def test_docs_command_lists_installed_operator_references(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["docs"])

        self.assertEqual(status, 0)
        self.assertIn("quickstart", output.getvalue())
        self.assertIn("reference", output.getvalue())

    def test_docs_command_prints_bundled_quickstart(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["docs", "quickstart"])

        self.assertEqual(status, 0)
        self.assertIn("首次安装与初始化", output.getvalue())
        self.assertIn("SENTINEL_CONSOLE_MONITORING_TARGETS", output.getvalue())

    def test_docs_reference_uses_installed_package_metadata(self):
        output = StringIO()
        with (
            patch(
                "atlas_richie.sentinel_console.operator_documentation.metadata.metadata"
            ) as package_metadata,
            redirect_stdout(output),
        ):
            package_metadata.return_value.get_payload.return_value = (
                "# Package README\n"
            )
            status = main(["docs", "reference"])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "# Package README\n")
        package_metadata.assert_called_once_with("atlas-richie-sentinel-console")

    def test_incident_expiration_cli_runs_once_and_disposes_engine(self):
        locator = object()
        observations = {}

        class FakeLocatorStore:
            async def read(self):
                return locator

        class FakeLocatorConfiguration:
            def create_store(self):
                return FakeLocatorStore()

        class FakeEngine:
            disposed = False

            async def dispose(self):
                self.disposed = True

        class FakeIncidentStore:
            pass

        class FakeExpiration:
            def __init__(self, store):
                self.store = store

            async def execute(self, now):
                observations["store"] = self.store
                observations["now"] = now
                return 3

        engine = FakeEngine()
        incident_store = FakeIncidentStore()
        output = StringIO()
        with (
            patch(
                "atlas_richie.sentinel_console.cli.RuntimeDatabaseLocatorConfiguration.from_environment",
                return_value=FakeLocatorConfiguration(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli._optional_absolute_file",
                return_value=None,
            ),
            patch(
                "atlas_richie.sentinel_console.cli.create_database_engine_from_locator",
                return_value=engine,
            ) as create_engine,
            patch(
                "atlas_richie.sentinel_console.cli.SQLAlchemyIncidentEventAdapter",
                return_value=incident_store,
            ),
            patch(
                "atlas_richie.sentinel_console.cli.ExpireIncidentHistory",
                side_effect=FakeExpiration,
            ),
            redirect_stdout(output),
        ):
            status = main(["incident-events", "expire"])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip(), "expired-incidents=3")
        self.assertTrue(engine.disposed)
        self.assertIs(create_engine.call_args.args[0], locator)
        self.assertIs(observations["store"], incident_store)
        self.assertIsNotNone(observations["now"].tzinfo)

    def test_incident_expiration_cli_fails_closed_without_runtime_locator(self):
        class FakeLocatorStore:
            async def read(self):
                return None

        class FakeLocatorConfiguration:
            def create_store(self):
                return FakeLocatorStore()

        error = StringIO()
        with (
            patch(
                "atlas_richie.sentinel_console.cli.RuntimeDatabaseLocatorConfiguration.from_environment",
                return_value=FakeLocatorConfiguration(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli._optional_absolute_file",
                return_value=None,
            ),
            patch(
                "atlas_richie.sentinel_console.cli.create_database_engine_from_locator"
            ) as create_engine,
            redirect_stderr(error),
        ):
            status = main(["incident-events", "expire"])

        self.assertEqual(status, 2)
        self.assertIn("runtime database is not configured", error.getvalue())
        create_engine.assert_not_called()

    def test_metrics_reporter_enroll_cli_never_echoes_identity_or_fingerprint(self):
        class FakeManagement:
            async def enroll(self, binding):
                self.binding = binding
                return binding

        class FakeRuntimeProvider:
            async def start(self):
                return True

            async def dispose(self):
                return None

        management = FakeManagement()
        runtime_provider = FakeRuntimeProvider()
        fingerprint = "a" * 64
        output = StringIO()
        arguments = [
            "metrics-reporter",
            "enroll",
            "--principal",
            "spiffe://sentinel.test/reporter/test",
            "--certificate-sha256",
            fingerprint,
            "--reporter-id",
            "reporter-test",
            "--environment-id",
            "test",
            "--app-id",
            "orders",
            "--instance-id",
            "orders-1",
            "--process-id",
            "worker-0",
        ]
        with (
            patch(
                "atlas_richie.sentinel_console.cli.RuntimeDatabaseLocatorConfiguration.from_environment",
                return_value=object(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli._optional_absolute_file",
                return_value=None,
            ),
            patch(
                "atlas_richie.sentinel_console.cli.build_metrics_reporter_admin",
                return_value=(management, runtime_provider),
            ),
            redirect_stdout(output),
        ):
            status = main(arguments)

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip(), "reporter-enrolled")
        self.assertNotIn(fingerprint, output.getvalue())
        self.assertEqual(management.binding.reporter_id, "reporter-test")

    def test_metrics_reporter_revoke_cli_distinguishes_unknown_principal(self):
        class FakeManagement:
            async def revoke(self, principal):
                self.principal = principal
                return False

        class FakeRuntimeProvider:
            async def start(self):
                return True

            async def dispose(self):
                return None

        management = FakeManagement()
        runtime_provider = FakeRuntimeProvider()
        output = StringIO()
        with (
            patch(
                "atlas_richie.sentinel_console.cli.RuntimeDatabaseLocatorConfiguration.from_environment",
                return_value=object(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli._optional_absolute_file",
                return_value=None,
            ),
            patch(
                "atlas_richie.sentinel_console.cli.build_metrics_reporter_admin",
                return_value=(management, runtime_provider),
            ),
            redirect_stdout(output),
        ):
            status = main(
                [
                    "metrics-reporter",
                    "revoke",
                    "--principal",
                    "spiffe://sentinel.test/reporter/missing",
                ]
            )

        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue().strip(), "reporter-not-found")

    def test_setup_window_is_closed_by_default_and_opens_with_remote_code(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            window_path = Path(temporary) / "setup-window.json"
            authority_path = Path(temporary) / "operator-authority.json"
            environment = {
                "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(window_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(authority_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE": "operator-code-" + "x" * 24,
                "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": base64.b64encode(
                    b"f" * 32
                ).decode("ascii"),
                "SENTINEL_CONSOLE_BIND_HOST": "0.0.0.0",
                "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "https://console.example.test",
            }
            output = StringIO()
            with (
                patch.dict(os.environ, environment, clear=True),
                redirect_stdout(output),
            ):
                status = main(["setup-window", "status"])
            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue().strip(), "setup-window=closed")
            self.assertFalse(window_path.exists())

            output = StringIO()
            with (
                patch.dict(os.environ, environment, clear=True),
                redirect_stdout(output),
            ):
                status = main(["setup-window", "open"])
            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue().strip(), "setup-window=open")
            self.assertTrue(window_path.exists())
            self.assertFalse(authority_path.exists())

            with (
                patch.dict(
                    os.environ,
                    {"SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(window_path)},
                    clear=True,
                ),
                redirect_stdout(StringIO()),
            ):
                status = main(["setup-window", "close"])
            self.assertEqual(status, 0)

    def test_setup_window_opens_without_operator_code_for_local_only_install(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            window_path = Path(temporary) / "setup-window.json"
            authority_path = Path(temporary) / "operator-authority.json"
            environment = {
                "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(window_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(authority_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": base64.b64encode(
                    b"l" * 32
                ).decode("ascii"),
                "SENTINEL_CONSOLE_BIND_HOST": "127.0.0.1",
                "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": (
                    "http://localhost:8000,http://127.0.0.1:8000"
                ),
            }
            output = StringIO()
            with (
                patch.dict(os.environ, environment, clear=True),
                redirect_stdout(output),
            ):
                status = main(["setup-window", "open"])

            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue().strip(), "setup-window=open")
            self.assertTrue(window_path.exists())
            self.assertFalse(authority_path.exists())

    def test_setup_window_open_fails_closed_without_operator_credential(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            environment = {
                "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(
                    Path(temporary) / "setup-window.json"
                ),
                "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(
                    Path(temporary) / "authority.json"
                ),
                "SENTINEL_CONSOLE_BIND_HOST": "0.0.0.0",
                "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "https://console.example.test",
                "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": base64.b64encode(
                    b"r" * 32
                ).decode("ascii"),
            }
            error = StringIO()
            with (
                patch.dict(os.environ, environment, clear=True),
                redirect_stderr(error),
            ):
                status = main(["setup-window", "open"])

            self.assertEqual(status, 2)
            self.assertIn("configuration is incomplete", error.getvalue())
            self.assertFalse((Path(temporary) / "setup-window.json").exists())

    def test_server_uses_loopback_default_and_disables_implicit_proxy_rewriting(
        self,
    ) -> None:
        server = Mock()
        fake_uvicorn = types.SimpleNamespace(run=server)
        with (
            patch.dict(sys.modules, {"uvicorn": fake_uvicorn}),
            patch(
                "atlas_richie.sentinel_console.cli.FirstRunSqlIdentityConfiguration.from_environment",
                return_value=object(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli.build_first_run_sql_identity_app",
                return_value=object(),
            ) as build_app,
        ):
            status = main(["serve"])

        self.assertEqual(status, 0)
        server.assert_called_once()
        self.assertEqual(
            server.call_args.args,
            ("atlas_richie.sentinel_console.cli:create_application",),
        )
        self.assertTrue(server.call_args.kwargs["factory"])
        self.assertEqual(server.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(server.call_args.kwargs["workers"], 1)
        self.assertFalse(server.call_args.kwargs["proxy_headers"])
        self.assertEqual(server.call_args.kwargs["timeout_worker_healthcheck"], 30)
        build_app.assert_not_called()

    def test_server_uses_explicit_deployment_bind_host_and_port(self) -> None:
        server = Mock()
        fake_uvicorn = types.SimpleNamespace(run=server)
        environment = {
            "SENTINEL_CONSOLE_BIND_HOST": "0.0.0.0",
            "SENTINEL_CONSOLE_PORT": "5196",
            "SENTINEL_CONSOLE_WORKERS": "4",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.dict(sys.modules, {"uvicorn": fake_uvicorn}),
            patch(
                "atlas_richie.sentinel_console.cli.FirstRunSqlIdentityConfiguration.from_environment",
                return_value=object(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli.build_first_run_sql_identity_app",
                return_value=object(),
            ),
        ):
            status = main(["serve"])

        self.assertEqual(status, 0)
        self.assertEqual(server.call_args.kwargs["host"], "0.0.0.0")
        self.assertEqual(server.call_args.kwargs["port"], 5196)
        self.assertEqual(server.call_args.kwargs["workers"], 4)
        self.assertTrue(server.call_args.kwargs["factory"])
        self.assertFalse(server.call_args.kwargs["proxy_headers"])

    def test_server_rejects_invalid_explicit_port_before_starting_uvicorn(self) -> None:
        server = Mock()
        fake_uvicorn = types.SimpleNamespace(run=server)
        configuration = {
            "SENTINEL_CONSOLE_BIND_HOST": "0.0.0.0",
            "SENTINEL_CONSOLE_PORT": "65536",
        }
        error = StringIO()
        with (
            patch.dict(os.environ, configuration, clear=True),
            patch.dict(sys.modules, {"uvicorn": fake_uvicorn}),
            patch(
                "atlas_richie.sentinel_console.cli.FirstRunSqlIdentityConfiguration.from_environment",
                return_value=object(),
            ),
            patch(
                "atlas_richie.sentinel_console.cli.build_first_run_sql_identity_app",
                return_value=object(),
            ),
            redirect_stderr(error),
        ):
            status = main(["serve"])

        self.assertEqual(status, 2)
        self.assertIn("Console port is invalid", error.getvalue())
        server.assert_not_called()

    def test_server_rejects_invalid_worker_count_before_starting_uvicorn(self) -> None:
        server = Mock()
        fake_uvicorn = types.SimpleNamespace(run=server)
        error = StringIO()
        with (
            patch.dict(
                os.environ,
                {"SENTINEL_CONSOLE_WORKERS": "0"},
                clear=True,
            ),
            patch.dict(sys.modules, {"uvicorn": fake_uvicorn}),
            patch(
                "atlas_richie.sentinel_console.cli.FirstRunSqlIdentityConfiguration.from_environment",
                return_value=object(),
            ),
            redirect_stderr(error),
        ):
            status = main(["serve"])

        self.assertEqual(status, 2)
        self.assertIn("Console worker count is invalid", error.getvalue())
        server.assert_not_called()

    def test_application_factory_builds_from_worker_process_environment(self) -> None:
        configuration = object()
        app = object()
        with (
            patch(
                "atlas_richie.sentinel_console.cli.FirstRunSqlIdentityConfiguration.from_environment",
                return_value=configuration,
            ),
            patch(
                "atlas_richie.sentinel_console.cli.build_first_run_sql_identity_app",
                return_value=app,
            ) as build_app,
        ):
            result = create_application()

        self.assertIs(result, app)
        build_app.assert_called_once_with(configuration)

    def test_metrics_server_requires_tls_files_and_uses_client_auth(self) -> None:
        class FakeConfig:
            pass

        async def fake_serve(app: object, configuration: FakeConfig) -> None:
            return None

        fake_anycorn = types.ModuleType("anycorn")
        fake_config = types.ModuleType("anycorn.config")
        fake_anyio = types.ModuleType("anyio")
        fake_run = Mock()
        fake_anyio.run = fake_run
        fake_anycorn.serve = fake_serve
        fake_config.Config = FakeConfig

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            certificate = Path(temporary) / "collector-cert.pem"
            private_key = Path(temporary) / "collector-key.pem"
            client_ca = Path(temporary) / "reporter-ca.pem"
            for path in (certificate, private_key, client_ca):
                path.write_text("test-only", encoding="utf-8")
            environment = {
                "SENTINEL_CONSOLE_METRICS_SERVER_CERTIFICATE": str(certificate),
                "SENTINEL_CONSOLE_METRICS_SERVER_PRIVATE_KEY": str(private_key),
                "SENTINEL_CONSOLE_METRICS_CLIENT_CA_CERTIFICATE": str(client_ca),
                "SENTINEL_CONSOLE_METRICS_BIND_HOST": "127.0.0.1",
                "SENTINEL_CONSOLE_METRICS_PORT": "18443",
            }
            app = object()
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.dict(
                    sys.modules,
                    {
                        "anycorn": fake_anycorn,
                        "anycorn.config": fake_config,
                        "anyio": fake_anyio,
                    },
                ),
                patch(
                    "atlas_richie.sentinel_console.cli.RuntimeDatabaseLocatorConfiguration.from_environment",
                    return_value=object(),
                ),
                patch(
                    "atlas_richie.sentinel_console.cli.build_metrics_collector_app",
                    return_value=app,
                ) as build_app,
            ):
                status = main(["serve-metrics"])

        self.assertEqual(status, 0)
        build_app.assert_called_once()
        self.assertIsNone(build_app.call_args.kwargs["postgresql_root_certificate"])
        self.assertIsInstance(
            build_app.call_args.kwargs["mysql_ssl_context"], ssl.SSLContext
        )
        fake_run.assert_called_once()
        self.assertIs(fake_run.call_args.args[0], fake_serve)
        self.assertIs(fake_run.call_args.args[1], app)
        server_configuration = fake_run.call_args.args[2]
        self.assertEqual(server_configuration.bind, ["127.0.0.1:18443"])
        self.assertEqual(server_configuration.certfile, str(certificate))
        self.assertEqual(server_configuration.keyfile, str(private_key))
        self.assertEqual(server_configuration.ca_certs, str(client_ca))
        self.assertEqual(server_configuration.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(server_configuration.alpn_protocols, ["h2", "http/1.1"])

    def test_metrics_server_rejects_missing_client_ca_before_startup(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            certificate = Path(temporary) / "collector-cert.pem"
            private_key = Path(temporary) / "collector-key.pem"
            certificate.touch()
            private_key.touch()
            error = StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "SENTINEL_CONSOLE_METRICS_SERVER_CERTIFICATE": str(certificate),
                        "SENTINEL_CONSOLE_METRICS_SERVER_PRIVATE_KEY": str(private_key),
                    },
                    clear=True,
                ),
                redirect_stderr(error),
            ):
                status = main(["serve-metrics"])

        self.assertEqual(status, 2)
        self.assertIn("TLS configuration is incomplete", error.getvalue())


if __name__ == "__main__":
    unittest.main()
