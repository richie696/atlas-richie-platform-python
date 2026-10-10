"""Command-level checks for safe setup-window operations and server wiring."""

from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from atlas_richie.sentinel_console.cli import main


class SentinelConsoleCliTests(unittest.TestCase):
    def test_setup_window_is_closed_by_default_and_requires_operator_code_to_open(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            window_path = Path(temporary) / "setup-window.json"
            authority_path = Path(temporary) / "operator-authority.json"
            environment = {
                "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(window_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(authority_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE": "operator-code-"
                + "x" * 24,
                "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": base64.b64encode(
                    b"f" * 32
                ).decode("ascii"),
            }
            output = StringIO()
            with patch.dict(os.environ, environment, clear=True):
                with redirect_stdout(output):
                    status = main(["setup-window", "status"])
            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue().strip(), "setup-window=closed")
            self.assertFalse(window_path.exists())

            output = StringIO()
            with patch.dict(os.environ, environment, clear=True):
                with redirect_stdout(output):
                    status = main(["setup-window", "open"])
            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue().strip(), "setup-window=open")
            self.assertTrue(window_path.exists())
            self.assertFalse(authority_path.exists())

            with patch.dict(
                os.environ,
                {"SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(window_path)},
                clear=True,
            ):
                with redirect_stdout(StringIO()):
                    status = main(["setup-window", "close"])
            self.assertEqual(status, 0)

    def test_setup_window_open_fails_closed_without_operator_credential(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            environment = {
                "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(
                    Path(temporary) / "setup-window.json"
                ),
                "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(
                    Path(temporary) / "authority.json"
                ),
            }
            error = StringIO()
            with patch.dict(os.environ, environment, clear=True):
                with redirect_stderr(error):
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
            ),
        ):
            status = main(["serve"])

        self.assertEqual(status, 0)
        server.assert_called_once()
        self.assertEqual(server.call_args.kwargs["host"], "127.0.0.1")
        self.assertFalse(server.call_args.kwargs["proxy_headers"])


if __name__ == "__main__":
    unittest.main()
