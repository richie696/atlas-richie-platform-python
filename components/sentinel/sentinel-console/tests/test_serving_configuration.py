"""Configuration-file resolution, precedence and CLI wiring for serve."""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from atlas_richie.sentinel_console.cli import main
from atlas_richie.sentinel_console.infrastructure.persistence.bootstrap_authorization_file_authority import (
    loopback_bootstrap_without_code_allowed,
)
from atlas_richie.sentinel_console.infrastructure.serving_file_configuration import (
    BIND_HOST_ENVIRONMENT,
    DEFAULT_BIND_HOST,
    DEFAULT_PORT,
    DEFAULT_WORKERS,
    PORT_ENVIRONMENT,
    WORKERS_ENVIRONMENT,
    parse_port_text,
    read_serving_file,
    resolve_serving_configuration,
)

_ENVIRONMENT_KEYS = (BIND_HOST_ENVIRONMENT, PORT_ENVIRONMENT, WORKERS_ENVIRONMENT)
_LOOPBACK_ORIGINS = {"SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": "http://127.0.0.1:8000"}


class ServingFileReadingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def write_file(self, content: str) -> Path:
        path = self.directory / "sentinel-console.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_full_file_is_returned(self):
        path = self.write_file('bind_host = "10.20.1.5"\nport = 9001\nworkers = 2\n')
        self.assertEqual(
            read_serving_file(path),
            {"bind_host": "10.20.1.5", "port": 9001, "workers": 2},
        )

    def test_single_key_files_are_returned(self):
        for content, expected in (
            ("port = 8100\n", {"port": 8100}),
            ('bind_host = "0.0.0.0"\n', {"bind_host": "0.0.0.0"}),
            ("workers = 4\n", {"workers": 4}),
        ):
            with self.subTest(content=content):
                self.assertEqual(
                    read_serving_file(self.write_file(content)), expected
                )

    def test_empty_file_yields_no_values(self):
        self.assertEqual(read_serving_file(self.write_file("")), {})

    def test_missing_file_is_rejected_with_path(self):
        missing = self.directory / "absent.toml"
        with self.assertRaises(ValueError) as raised:
            read_serving_file(missing)
        self.assertIn("does not exist", str(raised.exception))
        self.assertIn(str(missing), str(raised.exception))

    def test_malformed_toml_is_rejected_with_path(self):
        path = self.write_file("port =\n")
        with self.assertRaises(ValueError) as raised:
            read_serving_file(path)
        self.assertIn("not valid TOML", str(raised.exception))
        self.assertIn(str(path), str(raised.exception))

    def test_unknown_key_is_rejected_with_allowed_keys(self):
        path = self.write_file("potr = 8100\n")
        with self.assertRaises(ValueError) as raised:
            read_serving_file(path)
        message = str(raised.exception)
        self.assertIn("unknown keys potr", message)
        self.assertIn("bind_host, port, workers", message)

    def test_unknown_table_is_rejected_as_unknown_key(self):
        path = self.write_file("[server]\nport = 8100\n")
        with self.assertRaises(ValueError) as raised:
            read_serving_file(path)
        self.assertIn("unknown keys server", str(raised.exception))


class ServingResolutionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def config_path(self, content: str) -> Path:
        path = self.directory / "sentinel-console.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def resolve(self, **overrides):
        return resolve_serving_configuration(
            environ=overrides.pop("environ", {}), **overrides
        )

    def test_defaults_when_nothing_is_set(self):
        configuration = self.resolve()
        self.assertEqual(
            (configuration.bind_host, configuration.port, configuration.workers),
            (DEFAULT_BIND_HOST, DEFAULT_PORT, DEFAULT_WORKERS),
        )

    def test_file_values_apply_when_alone(self):
        path = self.config_path('bind_host = "10.20.1.5"\nport = 9001\nworkers = 2\n')
        configuration = self.resolve(config_path=path)
        self.assertEqual(
            (configuration.bind_host, configuration.port, configuration.workers),
            ("10.20.1.5", 9001, 2),
        )

    def test_environment_overrides_file(self):
        path = self.config_path('bind_host = "10.20.1.5"\nport = 9001\nworkers = 2\n')
        configuration = self.resolve(
            config_path=path,
            environ={
                BIND_HOST_ENVIRONMENT: "127.0.0.2",
                PORT_ENVIRONMENT: "7777",
                WORKERS_ENVIRONMENT: "3",
            },
        )
        self.assertEqual(
            (configuration.bind_host, configuration.port, configuration.workers),
            ("127.0.0.2", 7777, 3),
        )

    def test_command_line_overrides_environment(self):
        configuration = self.resolve(
            cli_bind_host="192.168.1.10",
            cli_port=8123,
            cli_workers=5,
            environ={
                BIND_HOST_ENVIRONMENT: "127.0.0.2",
                PORT_ENVIRONMENT: "7777",
                WORKERS_ENVIRONMENT: "3",
            },
        )
        self.assertEqual(
            (configuration.bind_host, configuration.port, configuration.workers),
            ("192.168.1.10", 8123, 5),
        )

    def test_command_line_overrides_file_without_environment(self):
        path = self.config_path('bind_host = "10.20.1.5"\nport = 9001\n')
        configuration = self.resolve(cli_port=6000, config_path=path)
        self.assertEqual(
            (configuration.bind_host, configuration.port, configuration.workers),
            ("10.20.1.5", 6000, 1),
        )

    def test_parameters_resolve_independently(self):
        path = self.config_path("workers = 4\n")
        configuration = self.resolve(
            cli_bind_host="192.168.1.10",
            config_path=path,
            environ={PORT_ENVIRONMENT: "7777"},
        )
        self.assertEqual(
            (configuration.bind_host, configuration.port, configuration.workers),
            ("192.168.1.10", 7777, 4),
        )

    def test_environment_port_text_keeps_historical_validation(self):
        with self.assertRaises(ValueError) as raised:
            self.resolve(environ={PORT_ENVIRONMENT: "99999"})
        self.assertEqual(str(raised.exception), "Console port is invalid")

    def test_command_line_port_range_is_validated(self):
        for value in (0, 65_536, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as raised:
                    self.resolve(cli_port=value)
                self.assertIn(
                    "Console port is invalid (command line)", str(raised.exception)
                )

    def test_command_line_worker_count_is_validated(self):
        with self.assertRaises(ValueError):
            self.resolve(cli_workers=0)

    def test_command_line_bind_host_must_be_clean(self):
        with self.assertRaises(ValueError):
            self.resolve(cli_bind_host=" 0.0.0.0 ")

    def test_file_type_and_range_errors_carry_the_file_path(self):
        for content, label in (
            ("bind_host = 5\n", "bind host integer"),
            ('bind_host = ""\n', "bind host empty"),
            ('bind_host = " 0.0.0.0 "\n', "bind host padded"),
            ('port = "8100"\n', "port string"),
            ("port = true\n", "port boolean"),
            ("port = 0\n", "port zero"),
            ("port = 65536\n", "port above range"),
            ("workers = 0\n", "workers zero"),
            ("workers = 1.5\n", "workers float"),
        ):
            with self.subTest(label=label):
                path = self.config_path(content)
                with self.assertRaises(ValueError) as raised:
                    self.resolve(config_path=path)
                self.assertIn(f"file {path}", str(raised.exception))

    def test_historical_parse_port_text_semantics(self):
        for bad in ("0", "65536", "-1", "80 0", "0x50", "99999"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_port_text(bad)
        self.assertEqual(parse_port_text("8000"), 8000)


class ServeCommandWiringTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        saved = {
            key: os.environ[key] for key in _ENVIRONMENT_KEYS if key in os.environ
        }
        for key in _ENVIRONMENT_KEYS:
            os.environ.pop(key, None)
        self.addCleanup(os.environ.update, saved)
        for key, value in _LOOPBACK_ORIGINS.items():
            saved_origin = os.environ.get(key)
            self.addCleanup(
                (lambda k, previous: lambda: (
                    os.environ.pop(k, None) if previous is None else os.environ.__setitem__(k, previous)
                ))(key, saved_origin)
            )
            os.environ[key] = value
        self.uvicorn = types.ModuleType("uvicorn")
        self.uvicorn.run = Mock(return_value=None)

    def config_path(self, content: str) -> Path:
        path = self.directory / "sentinel-console.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def run_serve(self, arguments):
        with (
            patch.dict(sys.modules, {"uvicorn": self.uvicorn}),
            patch(
                "atlas_richie.sentinel_console.cli.FirstRunSqlIdentityConfiguration.from_environment",
                return_value=object(),
            ),
        ):
            return main(arguments)

    def test_serve_reads_file_and_exports_resolved_bind_host(self):
        path = self.config_path('bind_host = "10.20.1.5"\nport = 9001\nworkers = 2\n')
        status = self.run_serve(["serve", "--config", str(path)])
        self.assertEqual(status, 0)
        (call,) = self.uvicorn.run.call_args_list
        self.assertEqual(call.kwargs["host"], "10.20.1.5")
        self.assertEqual(call.kwargs["port"], 9001)
        self.assertEqual(call.kwargs["workers"], 2)
        self.assertEqual(os.environ[BIND_HOST_ENVIRONMENT], "10.20.1.5")

    def test_serve_flags_override_environment_and_file(self):
        path = self.config_path('bind_host = "10.20.1.5"\nport = 9001\n')
        os.environ[PORT_ENVIRONMENT] = "7777"
        status = self.run_serve(
            ["serve", "--config", str(path), "--host", "0.0.0.0", "--port", "8123"]
        )
        self.assertEqual(status, 0)
        (call,) = self.uvicorn.run.call_args_list
        self.assertEqual(call.kwargs["host"], "0.0.0.0")
        self.assertEqual(call.kwargs["port"], 8123)
        self.assertEqual(os.environ[BIND_HOST_ENVIRONMENT], "0.0.0.0")

    def test_serve_environment_overrides_file_port(self):
        path = self.config_path("port = 8888\n")
        os.environ[PORT_ENVIRONMENT] = "7777"
        status = self.run_serve(["serve", "--config", str(path)])
        self.assertEqual(status, 0)
        (call,) = self.uvicorn.run.call_args_list
        self.assertEqual(call.kwargs["port"], 7777)

    def test_serve_without_config_keeps_historical_defaults(self):
        status = self.run_serve(["serve"])
        self.assertEqual(status, 0)
        (call,) = self.uvicorn.run.call_args_list
        self.assertEqual(call.kwargs["host"], "127.0.0.1")
        self.assertEqual(call.kwargs["port"], 8000)
        self.assertEqual(call.kwargs["workers"], 1)
        self.assertEqual(os.environ[BIND_HOST_ENVIRONMENT], "127.0.0.1")

    def test_serve_missing_config_file_fails_closed(self):
        missing = self.directory / "absent.toml"
        error = StringIO()
        with redirect_stderr(error):
            status = self.run_serve(["serve", "--config", str(missing)])
        self.assertEqual(status, 2)
        self.assertIn(
            "sentinel-console: Console configuration file does not exist",
            error.getvalue(),
        )
        self.assertIn(str(missing), error.getvalue())
        self.uvicorn.run.assert_not_called()

    def test_serve_rejects_unknown_config_key(self):
        path = self.config_path("potr = 8100\n")
        error = StringIO()
        with redirect_stderr(error):
            status = self.run_serve(["serve", "--config", str(path)])
        self.assertEqual(status, 2)
        self.assertIn("unknown keys potr", error.getvalue())
        self.uvicorn.run.assert_not_called()

    def test_serve_rejects_out_of_range_flag_port(self):
        error = StringIO()
        with redirect_stderr(error):
            status = self.run_serve(["serve", "--port", "0"])
        self.assertEqual(status, 2)
        self.assertIn("Console port is invalid (command line)", error.getvalue())
        self.uvicorn.run.assert_not_called()

    def test_serve_loopback_file_binding_allows_code_free_gate(self):
        path = self.config_path('bind_host = "127.0.0.1"\n')
        status = self.run_serve(["serve", "--config", str(path)])
        self.assertEqual(status, 0)
        self.assertTrue(loopback_bootstrap_without_code_allowed(os.environ))

    def test_serve_non_loopback_file_binding_blocks_code_free_gate(self):
        path = self.config_path('bind_host = "0.0.0.0"\n')
        status = self.run_serve(["serve", "--config", str(path)])
        self.assertEqual(status, 0)
        self.assertEqual(os.environ[BIND_HOST_ENVIRONMENT], "0.0.0.0")
        self.assertFalse(loopback_bootstrap_without_code_allowed(os.environ))

    def test_serve_non_loopback_environment_binding_blocks_code_free_gate(self):
        os.environ[BIND_HOST_ENVIRONMENT] = "0.0.0.0"
        status = self.run_serve(["serve"])
        self.assertEqual(status, 0)
        self.assertFalse(loopback_bootstrap_without_code_allowed(os.environ))


class SetupWindowConfigWiringTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        saved = {
            key: os.environ[key] for key in _ENVIRONMENT_KEYS if key in os.environ
        }
        for key in _ENVIRONMENT_KEYS:
            os.environ.pop(key, None)
        self.addCleanup(os.environ.update, saved)

    def test_setup_window_status_with_config_exports_resolved_bind_host(self):
        path = self.directory / "sentinel-console.toml"
        path.write_text('bind_host = "10.20.1.5"\n', encoding="utf-8")

        class FakeStore:
            async def read_snapshot(self):
                return SimpleNamespace(is_open=False, revision=3)

        class FakeConfiguration:
            def create_store(self):
                return FakeStore()

        output = StringIO()
        with (
            patch(
                "atlas_richie.sentinel_console.cli.SetupWindowConfiguration.from_environment",
                return_value=FakeConfiguration(),
            ),
            redirect_stdout(output),
        ):
            status = main(["setup-window", "status", "--config", str(path)])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip(), "setup-window=closed")
        self.assertEqual(os.environ[BIND_HOST_ENVIRONMENT], "10.20.1.5")

    def test_setup_window_without_config_leaves_environment_untouched(self):
        class FakeStore:
            async def read_snapshot(self):
                return SimpleNamespace(is_open=False, revision=3)

        class FakeConfiguration:
            def create_store(self):
                return FakeStore()

        output = StringIO()
        with (
            patch(
                "atlas_richie.sentinel_console.cli.SetupWindowConfiguration.from_environment",
                return_value=FakeConfiguration(),
            ),
            redirect_stdout(output),
        ):
            status = main(["setup-window", "status"])

        self.assertEqual(status, 0)
        self.assertNotIn(BIND_HOST_ENVIRONMENT, os.environ)


if __name__ == "__main__":
    unittest.main()
