"""Opt-in installed-wheel Console startup acceptance against disposable MySQL."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    ConsoleGuardRecord,
)

_PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
_CONTRACTS_PROJECT_DIRECTORY = (
    _PROJECT_DIRECTORY.parents[2] / "foundation" / "contracts"
)
_RUN_MYSQL_ENV = "SENTINEL_E2E_MYSQL_URL"
_RUN_MYSQL_URL_ENV = "SENTINEL_CONSOLE_TEST_MYSQL_URL"
_RUN_POSTGRES_URL_ENV = "SENTINEL_CONSOLE_TEST_POSTGRES_URL"
_RUN_APACHE_PROXY_ENV = "SENTINEL_CONSOLE_RUN_APACHE_PROXY_ACCEPTANCE"
_RUN_WORKERS_ENV = "SENTINEL_CONSOLE_TEST_WORKERS"
_RUN_CONSUL_URL_ENV = "SENTINEL_E2E_CONSUL_URL"
_RUN_CONSUL_TOKEN_ENV = "SENTINEL_E2E_CONSUL_TOKEN"
_RUN_CONSUL_ACL_ACCEPTANCE_ENV = "SENTINEL_CONSOLE_RUN_CONSUL_ACL_ACCEPTANCE"
_RUN_IDENTITY_ACCEPTANCE_ENV = "SENTINEL_CONSOLE_RUN_IDENTITY_ACCEPTANCE"
_RUN_RULE_BINDING_RECEIPT_ACCEPTANCE_ENV = (
    "SENTINEL_CONSOLE_RUN_RULE_BINDING_RECEIPT_ACCEPTANCE"
)
_ACCEPTANCE_TIMEOUT_SECONDS = 45
_INSTALLED_ADMIN_USERNAME = "installed-first-run-admin"
_INSTALLED_ADMIN_PASSWORD = "synthetic-installed-admin-password-42"


class InstalledCliBootstrapAcceptanceTests(unittest.TestCase):
    """Exercise the packaged console entry point in a disposable Python env."""

    def test_installed_cli_migrates_and_serves_safe_first_run_state(self) -> None:
        database_url = os.environ.get(_RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_e2e_dependencies.sh for isolated MySQL"
            )
        self.assertIsNotNone(os.environ.get("SENTINEL_E2E_MYSQL_HOST"))
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        after_initialize = (
            self._assert_installed_live_consul_probe
            if os.environ.get(_RUN_CONSUL_URL_ENV)
            else None
        )
        self._run_installed_cli_acceptance(
            database_url,
            "mysql",
            after_initialize=after_initialize,
            restart_before_callback=after_initialize is not None,
        )

    def test_installed_cli_postgresql_first_run_with_two_workers(self) -> None:
        database_url = os.environ.get(_RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_postgresql_acceptance.sh for isolated PostgreSQL"
            )
        self.assertIsNotNone(os.environ.get("SENTINEL_E2E_POSTGRES_HOST"))
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        self._run_installed_cli_acceptance(database_url, "postgresql")

    @unittest.skipUnless(
        os.environ.get(_RUN_IDENTITY_ACCEPTANCE_ENV) == "1",
        "requires an explicit disposable SQL account-identity acceptance runner",
    )
    def test_installed_cli_persists_account_commands_and_enforces_view_role(
        self,
    ) -> None:
        database_url = os.environ.get(_RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_e2e_dependencies.sh for isolated MySQL"
            )
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        self._run_installed_cli_acceptance(
            database_url,
            "mysql",
            after_initialize=self._assert_installed_account_workflow,
            restart_before_callback=True,
        )

    @unittest.skipUnless(
        os.environ.get(_RUN_IDENTITY_ACCEPTANCE_ENV) == "1",
        "requires the explicit disposable SQL account-identity acceptance runner",
    )
    def test_installed_cli_postgresql_account_commands_and_enforces_view_role(
        self,
    ) -> None:
        database_url = os.environ.get(_RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_postgresql_acceptance.sh for isolated PostgreSQL"
            )
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        self._run_installed_cli_acceptance(
            database_url,
            "postgresql",
            after_initialize=self._assert_installed_account_workflow,
            restart_before_callback=True,
        )

    @unittest.skipUnless(
        os.environ.get(_RUN_RULE_BINDING_RECEIPT_ACCEPTANCE_ENV) == "1",
        "requires an explicit disposable SQL registration-receipt acceptance runner",
    )
    def test_installed_cli_recovers_rule_binding_receipt_after_session_rotation(
        self,
    ) -> None:
        database_url = os.environ.get(_RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_e2e_dependencies.sh for isolated MySQL"
            )
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        self._run_installed_cli_acceptance(
            database_url,
            "mysql",
            after_initialize=self._assert_installed_rule_binding_receipt,
        )

    @unittest.skipUnless(
        os.environ.get(_RUN_RULE_BINDING_RECEIPT_ACCEPTANCE_ENV) == "1",
        "requires an explicit disposable SQL registration-receipt acceptance runner",
    )
    def test_installed_cli_postgresql_recovers_rule_binding_receipt_after_session_rotation(
        self,
    ) -> None:
        database_url = os.environ.get(_RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_postgresql_acceptance.sh for isolated PostgreSQL"
            )
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        self._run_installed_cli_acceptance(
            database_url,
            "postgresql",
            after_initialize=self._assert_installed_rule_binding_receipt,
        )

    def _run_installed_cli_acceptance(
        self,
        database_url: str,
        database_kind: str,
        *,
        after_initialize: Callable[[int, Path, dict[str, str]], None] | None = None,
        restart_before_callback: bool = False,
        enable_dual_provider_publication: bool = False,
        initial_source: dict[str, object] | None = None,
        service_environment_overrides: dict[str, str] | None = None,
        expected_source_secret: str | None = None,
    ) -> None:

        uv = shutil.which("uv")
        self.assertIsNotNone(uv, "uv is required to build and install the wheel")

        with tempfile.TemporaryDirectory(
            prefix="sentinel-installed-cli-", dir="/private/tmp"
        ) as raw:
            temporary_directory = Path(raw)
            wheel_directory = temporary_directory / "wheelhouse"
            wheel_directory.mkdir()
            environment_directory = temporary_directory / "venv"
            self._build_and_install_wheel(
                uv=uv,
                wheel_directory=wheel_directory,
                environment_directory=environment_directory,
                database_kind=database_kind,
                include_nacos_grpc=enable_dual_provider_publication,
            )
            python = environment_directory / "bin" / "python"
            console = environment_directory / "bin" / "sentinel-console"
            self.assertTrue(console.is_file())
            self._assert_installed_distribution(python, environment_directory)

            runtime_directory = temporary_directory / "runtime"
            runtime_directory.mkdir(mode=0o700)
            service_environment = self._service_environment(
                runtime_directory=runtime_directory,
                database_url=database_url,
                database_kind=database_kind,
                enable_dual_provider_publication=enable_dual_provider_publication,
            )
            if service_environment_overrides is not None:
                service_environment.update(service_environment_overrides)
            self.assertNotIn(
                _RUN_CONSUL_TOKEN_ENV,
                service_environment,
                "test-only ACL token must not be passed to the installed CLI process",
            )
            if os.environ.get(_RUN_APACHE_PROXY_ENV) == "1":
                service_environment["SENTINEL_CONSOLE_TRUSTED_PROXY_CIDRS"] = (
                    "127.0.0.1/32"
                )
            runtime_locator_path = Path(
                service_environment["SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH"]
            )
            self.assertFalse(
                runtime_locator_path.exists(),
                "first-run acceptance must start without a selected database",
            )

            port = self._available_loopback_port()
            service_environment["SENTINEL_CONSOLE_BIND_HOST"] = "127.0.0.1"
            service_environment["SENTINEL_CONSOLE_PORT"] = str(port)
            service_environment["SENTINEL_CONSOLE_WORKERS"] = os.environ.get(
                _RUN_WORKERS_ENV, "2"
            )
            log_path = temporary_directory / "console.log"
            with log_path.open("wb") as log_file:
                process = subprocess.Popen(
                    [str(console), "serve"],
                    cwd=temporary_directory,
                    env=service_environment,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    payload, response_headers = self._wait_for_bootstrap(
                        process=process,
                        port=port,
                        log_path=log_path,
                    )
                    self.assertEqual(
                        payload,
                        {
                            "initialized": False,
                            "setupAvailable": False,
                            "operatorAuthorized": False,
                        },
                    )
                    self.assertEqual(response_headers.get("cache-control"), "no-store")
                    self.assertEqual(
                        response_headers.get("x-request-id"),
                        "installed-cli-bootstrap-acceptance",
                    )
                    self._assert_installed_dashboard_assets(port)
                    self.assertIn("127.0.0.1", log_path.read_text(errors="replace"))
                    self.assertEqual(
                        log_path.read_text(errors="replace").count(
                            "Started server process"
                        ),
                        int(service_environment["SENTINEL_CONSOLE_WORKERS"]),
                    )
                    self._assert_setup_window_closed(
                        console=console,
                        service_environment=service_environment,
                        setup_window_path=Path(
                            service_environment["SENTINEL_CONSOLE_SETUP_WINDOW_PATH"]
                        ),
                    )
                    try:
                        admin_username = self._initialize_through_installed_http(
                            console=console,
                            service_environment=service_environment,
                            port=port,
                            database_url=database_url,
                            database_kind=database_kind,
                            initial_source=initial_source,
                        )
                    except Exception as error:
                        try:
                            post_failure_status, post_failure_body, _ = (
                                self._request_json(
                                    f"http://127.0.0.1:{port}/api/v1/system/bootstrap",
                                    method="GET",
                                    headers={
                                        "x-request-id": "installed-cli-after-failure"
                                    },
                                )
                            )
                        except Exception as probe_error:  # noqa: BLE001 - preserve the initialization failure while collecting diagnostics
                            post_failure_status = type(probe_error).__name__
                            post_failure_body = {}
                        raise AssertionError(
                            "installed Console first-run initialization failed; "
                            f"server_parent_exit={process.poll()}; "
                            f"bootstrap_after_failure={post_failure_status} "
                            f"{post_failure_body!r}; "
                            "service log follows:\n"
                            + log_path.read_text(errors="replace")
                        ) from error
                    self.assertTrue(
                        runtime_locator_path.is_file(),
                        "setup must persist the selected runtime database locator",
                    )
                    self._assert_migrations_and_initialized_guard(database_url)
                    self._assert_initialized_database(
                        database_url,
                        expected_source_secret=(
                            expected_source_secret
                            if expected_source_secret is not None
                            else os.environ.get(_RUN_CONSUL_TOKEN_ENV) or None
                        ),
                    )
                    if restart_before_callback:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        process = subprocess.Popen(
                            [str(console), "serve"],
                            cwd=temporary_directory,
                            env=service_environment,
                            stdout=log_file,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                        )
                        restarted_payload, restarted_headers = self._wait_for_bootstrap(
                            process=process,
                            port=port,
                            log_path=log_path,
                        )
                        self.assertEqual(restarted_payload, {"initialized": True})
                        self.assertEqual(
                            restarted_headers.get("cache-control"), "no-store"
                        )
                        self.assertTrue(runtime_locator_path.is_file())
                    if after_initialize is not None:
                        try:
                            after_initialize(
                                port, temporary_directory, service_environment
                            )
                        except Exception as error:
                            raise AssertionError(
                                "post-initialization acceptance callback failed: "
                                f"{type(error).__name__}: {error}; "
                                "service log follows:\n"
                                + log_path.read_text(errors="replace")
                            ) from error
                    if os.environ.get(_RUN_APACHE_PROXY_ENV) == "1":
                        self._assert_installed_cli_through_apache_proxy(
                            port=port,
                            admin_username=admin_username,
                            log_directory=temporary_directory,
                        )
                    self._assert_setup_window_closed(
                        console=console,
                        service_environment=service_environment,
                        setup_window_path=Path(
                            service_environment["SENTINEL_CONSOLE_SETUP_WINDOW_PATH"]
                        ),
                        expected_absent=False,
                    )
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

    def _build_and_install_wheel(
        self,
        *,
        uv: str,
        wheel_directory: Path,
        environment_directory: Path,
        database_kind: str,
        include_nacos_grpc: bool = False,
    ) -> None:
        subprocess.run(
            [
                uv,
                "build",
                "--wheel",
                "--out-dir",
                str(wheel_directory),
            ],
            cwd=_PROJECT_DIRECTORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        subprocess.run(
            [
                uv,
                "build",
                "--wheel",
                "--out-dir",
                str(wheel_directory),
            ],
            cwd=_CONTRACTS_PROJECT_DIRECTORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        wheels = tuple(wheel_directory.glob("atlas_richie_sentinel_console-*.whl"))
        self.assertEqual(len(wheels), 1, "the isolated build must produce one wheel")
        contracts_wheels = tuple(wheel_directory.glob("atlas_richie_contracts-*.whl"))
        self.assertEqual(
            len(contracts_wheels),
            1,
            "the isolated build must include the repository contracts wheel",
        )
        subprocess.run(
            [
                uv,
                "venv",
                "--python",
                sys.executable,
                str(environment_directory),
            ],
            cwd=temporary_cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        installed_python = environment_directory / "bin" / "python"
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(installed_python),
                (
                    f"{wheels[0]}[{_database_package_extra(database_kind)},server"
                    f"{',nacos-grpc' if include_nacos_grpc else ''}]"
                ),
                str(contracts_wheels[0]),
            ],
            cwd=temporary_cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def _assert_installed_distribution(
        self, python: Path, environment_directory: Path
    ) -> None:
        result = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import atlas_richie.sentinel_console as package; "
                    "print(package.__file__)"
                ),
            ],
            cwd=temporary_cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertTrue(
            Path(result.stdout.strip()).is_relative_to(environment_directory),
            "the service must import the installed wheel, not the checkout",
        )

    def _service_environment(
        self,
        *,
        runtime_directory: Path,
        database_url: str,
        database_kind: str,
        enable_dual_provider_publication: bool = False,
    ) -> dict[str, str]:
        key = lambda byte: base64.b64encode(byte * 32).decode("ascii")
        environment = os.environ.copy()
        environment.pop(_RUN_CONSUL_TOKEN_ENV, None)
        port_key = "POSTGRES" if database_kind == "postgresql" else "MYSQL"
        port_variable = f"SENTINEL_E2E_{port_key}_PORT"
        database_port = environment[port_variable]
        database_targets = f"{database_kind}|127.0.0.1/32|{database_port}"
        certificate_variable = (
            "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
            if database_kind == "postgresql"
            else "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"
        )
        environment.update(
            {
                "SENTINEL_CONSOLE_SETUP_WINDOW_PATH": str(
                    runtime_directory / "setup-window.json"
                ),
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH": str(
                    runtime_directory / "runtime-database.json"
                ),
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID": "test-v1",
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING": (
                    f"test-v1={key(b'r')}"
                ),
                "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH": str(
                    runtime_directory / "bootstrap-authority.json"
                ),
                "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE": (
                    "acceptance-operator-code-" + "x" * 24
                ),
                "SENTINEL_CONSOLE_BOOTSTRAP_FINGERPRINT_KEY": key(b"f"),
                "SENTINEL_CONSOLE_BOOTSTRAP_INITIALIZATION_LOCK_PATH": str(
                    runtime_directory / "bootstrap-initialization.lock"
                ),
                "SENTINEL_CONSOLE_BOOTSTRAP_IDEMPOTENCY_KEY": key(b"i"),
                "SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS": (database_targets),
                "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                    "consul|consul.acceptance.invalid|127.0.0.1/32|8500"
                ),
                "SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS": (
                    "https://console.acceptance.invalid"
                ),
                "SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD": "5",
                "SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS": "300",
                "SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS": "300",
                "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_ACTIVE_KEY_ID": "account-v1",
                "SENTINEL_CONSOLE_ACCOUNT_FINGERPRINT_KEY_RING": (
                    f"account-v1={key(b'a')}"
                ),
                "SENTINEL_CONSOLE_CLIENT_IDENTITY_HMAC_KEY": key(b"c"),
                "SENTINEL_CONSOLE_SOURCE_SECRET_ACTIVE_KEY_ID": "source-secret-v1",
                "SENTINEL_CONSOLE_SOURCE_SECRET_KEY_RING": (
                    f"source-secret-v1={key(b's')}"
                ),
                "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_ACTIVE_KEY_ID": (
                    "source-fingerprint-v1"
                ),
                "SENTINEL_CONSOLE_SOURCE_FINGERPRINT_KEY_RING": (
                    f"source-fingerprint-v1={key(b'p')}"
                ),
                certificate_variable: environment[certificate_variable],
            }
        )
        consul_url = environment.get(_RUN_CONSUL_URL_ENV)
        if consul_url is not None and not enable_dual_provider_publication:
            parsed_consul_url = urlsplit(consul_url)
            if (
                parsed_consul_url.scheme not in {"http", "https"}
                or parsed_consul_url.hostname != "127.0.0.1"
                or parsed_consul_url.username is not None
                or parsed_consul_url.password is not None
                or parsed_consul_url.port is None
                or parsed_consul_url.path not in {"", "/"}
                or parsed_consul_url.query
                or parsed_consul_url.fragment
            ):
                raise AssertionError(
                    f"{_RUN_CONSUL_URL_ENV} must be a plain loopback URL"
                )
            consul_token = os.environ.get(_RUN_CONSUL_TOKEN_ENV)
            if consul_token and parsed_consul_url.scheme != "https":
                raise AssertionError("Consul ACL tokens require verified HTTPS")
            environment["SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS"] = (
                f"consul|127.0.0.1|127.0.0.1/32|{parsed_consul_url.port}"
            )
        if enable_dual_provider_publication:
            consul_port = urlsplit(environment["SENTINEL_E2E_CONSUL_URL"]).port
            if consul_port is None:
                raise AssertionError(
                    "disposable Consul URL must include an explicit port"
                )
            nacos_http_port = environment["SENTINEL_CONSOLE_TEST_NACOS_HTTP_PORT"]
            nacos_grpc_port = environment["SENTINEL_CONSOLE_TEST_NACOS_GRPC_PORT"]
            environment.update(
                {
                    "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                        f"consul|127.0.0.1|127.0.0.1/32|{consul_port};"
                        f"nacos|127.0.0.1|127.0.0.1/32|"
                        f"{nacos_http_port},{nacos_grpc_port}"
                    ),
                    "SENTINEL_CONSOLE_RULE_PUBLICATION_PROVIDERS": "nacos,consul",
                    "SENTINEL_CONSOLE_RULE_PUBLICATION_PROFILE_ID": (
                        "sentinel-profile-v1"
                    ),
                    "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_ACTIVE_KEY_ID": (
                        "acceptance-v1"
                    ),
                    "SENTINEL_CONSOLE_RULE_COMMAND_FINGERPRINT_KEY_RING": (
                        f"acceptance-v1={key(b'q')}"
                    ),
                }
            )
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        return environment

    def _wait_for_bootstrap(
        self,
        *,
        process: subprocess.Popen[bytes],
        port: int,
        log_path: Path,
    ) -> tuple[dict[str, object], dict[str, str]]:
        deadline = time.monotonic() + _ACCEPTANCE_TIMEOUT_SECONDS
        last_error = "service did not answer bootstrap request"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail(
                    "installed Console CLI exited before readiness: "
                    + log_path.read_text(errors="replace")
                )
            request = Request(
                f"http://127.0.0.1:{port}/api/v1/system/bootstrap",
                headers={"x-request-id": "installed-cli-bootstrap-acceptance"},
            )
            try:
                with urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read())
                    return payload, dict(response.headers.items())
            except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = type(error).__name__
                time.sleep(0.2)
        self.fail(
            f"installed Console CLI readiness timed out ({last_error}): "
            + log_path.read_text(errors="replace")
        )

    def _assert_installed_dashboard_assets(self, port: int) -> None:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            html = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Atlas Richie Sentinel Console", html)
            self.assertIn("no-cache", response.headers.get("cache-control", ""))

        asset_paths = re.findall(r"(?:src|href)=\"(/assets/[^\"]+)\"", html)
        fingerprinted_assets = tuple(
            path
            for path in asset_paths
            if re.search(r"-[A-Za-z0-9_-]{8,}\.(?:js|css)$", path)
        )
        self.assertTrue(
            fingerprinted_assets, "installed wheel HTML has no hashed asset"
        )
        asset_url = f"http://127.0.0.1:{port}{fingerprinted_assets[0]}"
        with urlopen(asset_url, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertGreater(int(response.headers.get("content-length", "0")), 0)
            self.assertIn("immutable", response.headers.get("cache-control", ""))

        try:
            urlopen(f"http://127.0.0.1:{port}/api/v1/not-registered", timeout=5)
        except HTTPError as error:
            self.assertEqual(error.code, 404)
            self.assertIn("application/json", error.headers.get("content-type", ""))
            payload = json.loads(error.read())
        else:
            self.fail("unknown installed Console API unexpectedly returned success")
        self.assertEqual(payload["error"]["code"], "not_found")

    def _assert_installed_cli_through_apache_proxy(
        self, *, port: int, admin_username: str, log_directory: Path
    ) -> None:
        httpd = shutil.which("httpd")
        if httpd is None:
            self.skipTest("Apache httpd is required for the opt-in proxy acceptance")
        module_directory = Path("/usr/libexec/apache2")
        module_names = (
            "mpm_prefork",
            "unixd",
            "authz_core",
            "log_config",
            "headers",
            "proxy",
            "proxy_http",
        )
        missing_modules = tuple(
            name
            for name in module_names
            if not (module_directory / f"mod_{name}.so").is_file()
        )
        if missing_modules:
            self.skipTest(
                "Apache proxy modules are unavailable: " + ", ".join(missing_modules)
            )

        proxy_port = self._available_loopback_port()
        with tempfile.TemporaryDirectory(
            prefix="sentinel-apache-proxy-", dir=log_directory
        ) as raw_directory:
            proxy_directory = Path(raw_directory)
            config_path = proxy_directory / "httpd.conf"
            error_log = proxy_directory / "error.log"
            runtime_path = proxy_directory / "run"
            runtime_path.mkdir(mode=0o700)
            module_lines = "\n".join(
                f"LoadModule {name}_module {module_directory / f'mod_{name}.so'}"
                for name in module_names
            )
            config_path.write_text(
                "\n".join(
                    (
                        'ServerRoot "/usr"',
                        "ServerName 127.0.0.1",
                        f"Listen 127.0.0.1:{proxy_port}",
                        f'PidFile "{proxy_directory / "httpd.pid"}"',
                        f'DefaultRuntimeDir "{runtime_path}"',
                        module_lines,
                        f'ErrorLog "{error_log}"',
                        "LogLevel warn",
                        "ProxyRequests Off",
                        "ProxyAddHeaders On",
                        "RequestHeader unset X-Forwarded-For early",
                        f"ProxyPass /api/ http://127.0.0.1:{port}/api/ retry=0",
                        f"ProxyPassReverse /api/ http://127.0.0.1:{port}/api/",
                        f"ProxyPass /assets/ http://127.0.0.1:{port}/assets/ retry=0",
                        f"ProxyPassReverse /assets/ http://127.0.0.1:{port}/assets/",
                        f"ProxyPass /ops/sentinel/ http://127.0.0.1:{port}/ retry=0",
                        f"ProxyPassReverse /ops/sentinel/ http://127.0.0.1:{port}/",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            syntax = subprocess.run(
                [httpd, "-f", str(config_path), "-t"],
                cwd=proxy_directory,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            proxy_log = (proxy_directory / "process.log").open("wb")
            process = subprocess.Popen(
                [httpd, "-f", str(config_path), "-DFOREGROUND"],
                cwd=proxy_directory,
                stdout=proxy_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                self._wait_for_apache_proxy(
                    process=process,
                    proxy_port=proxy_port,
                    proxy_directory=proxy_directory,
                )
                base_url = f"http://127.0.0.1:{proxy_port}"
                with urlopen(base_url + "/ops/sentinel/login", timeout=5) as response:
                    html = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                    self.assertIn("Atlas Richie Sentinel Console", html)
                asset_paths = re.findall(r"(?:src|href)=\"(/assets/[^\"]+)\"", html)
                self.assertTrue(asset_paths, "proxied HTML has no static asset")
                with urlopen(base_url + asset_paths[0], timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(
                        "immutable", response.headers.get("cache-control", "")
                    )

                api_status, api_error, _ = self._request_json(
                    base_url + "/api/v1/not-registered",
                    method="GET",
                    headers={"x-request-id": "apache-proxy-api-miss"},
                )
                self.assertEqual(api_status, 404)
                self.assertEqual(api_error.get("error", {}).get("code"), "not_found")

                csrf_status, _bootstrap, bootstrap_headers = self._request_json(
                    base_url + "/api/v1/system/bootstrap",
                    method="GET",
                    headers={"x-request-id": "apache-proxy-bootstrap"},
                )
                self.assertEqual(csrf_status, 200)
                csrf_nonce = bootstrap_headers.get("x-sentinel-csrf")
                self.assertIsInstance(csrf_nonce, str)
                observed_statuses: list[int] = []
                for index in range(1, 7):
                    status, _body, _headers = self._request_json(
                        base_url + "/api/v1/auth/login",
                        method="POST",
                        headers={
                            "origin": "https://console.acceptance.invalid",
                            "cookie": f"__Host-sentinel_csrf={csrf_nonce}",
                            "x-sentinel-csrf": str(csrf_nonce),
                            "x-forwarded-for": f"198.51.100.{index}",
                            "x-request-id": f"apache-proxy-login-{index}",
                        },
                        body={
                            "username": admin_username,
                            "password": "synthetic-wrong-password-0001",
                        },
                    )
                    observed_statuses.append(status)
                self.assertEqual(observed_statuses, [401, 401, 401, 401, 401, 429])
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                proxy_log.close()

    def _wait_for_apache_proxy(
        self,
        *,
        process: subprocess.Popen[bytes],
        proxy_port: int,
        proxy_directory: Path,
    ) -> None:
        deadline = time.monotonic() + 10
        last_error = "Apache proxy did not answer"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail(
                    "Apache proxy exited during startup: "
                    + (proxy_directory / "error.log").read_text(errors="replace")
                )
            try:
                with urlopen(
                    f"http://127.0.0.1:{proxy_port}/ops/sentinel/login", timeout=1
                ) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError, TimeoutError) as error:
                last_error = type(error).__name__
                time.sleep(0.1)
        self.fail(f"Apache proxy timed out ({last_error})")

    def _assert_migrations_and_initialized_guard(self, database_url: str) -> None:
        async def verify() -> tuple[object, object]:
            engine = create_async_engine(database_url, hide_parameters=True)
            try:
                async with engine.connect() as connection:
                    revision = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    initialized = await connection.scalar(
                        text(
                            "SELECT initialized FROM console_guard "
                            "WHERE singleton_id = 1"
                        )
                    )
                    return revision, initialized
            finally:
                await engine.dispose()

        revision, initialized = asyncio.run(verify())
        self.assertIsInstance(revision, str)
        self.assertGreater(len(revision), 0)
        self.assertEqual(initialized, 1)
        self.assertEqual(ConsoleGuardRecord.__tablename__, "console_guard")

    def _assert_setup_window_closed(
        self,
        *,
        console: Path,
        service_environment: dict[str, str],
        setup_window_path: Path,
        expected_absent: bool = True,
    ) -> None:
        result = subprocess.run(
            [str(console), "setup-window", "status"],
            cwd=temporary_cwd(),
            env=service_environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "setup-window=closed")
        self.assertEqual(setup_window_path.exists(), not expected_absent)

    def _initialize_through_installed_http(
        self,
        *,
        console: Path,
        service_environment: dict[str, str],
        port: int,
        database_url: str,
        database_kind: str,
        initial_source: dict[str, object] | None = None,
    ) -> str:
        opened = subprocess.run(
            [str(console), "setup-window", "open"],
            cwd=temporary_cwd(),
            env=service_environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(opened.stdout.strip(), "setup-window=open")

        origin = "https://console.acceptance.invalid"
        url = f"http://127.0.0.1:{port}"
        bootstrap_status, bootstrap_body, bootstrap_headers = self._request_json(
            url + "/api/v1/system/bootstrap",
            method="GET",
            headers={"x-request-id": "installed-cli-open-bootstrap"},
        )
        self.assertEqual(bootstrap_status, 200)
        self.assertEqual(
            bootstrap_body,
            {
                "initialized": False,
                "setupAvailable": True,
                "operatorAuthorized": False,
            },
        )
        csrf_nonce = bootstrap_headers.get("x-sentinel-csrf")
        self.assertIsInstance(csrf_nonce, str)

        authorize_status, authorize_body, authorize_headers = self._request_json(
            url + "/api/v1/system/bootstrap/authorize",
            method="POST",
            body={
                "operatorCode": service_environment[
                    "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE"
                ]
            },
            headers={
                "origin": origin,
                "cookie": f"__Host-sentinel_csrf={csrf_nonce}",
                "x-sentinel-csrf": csrf_nonce,
                "x-request-id": "installed-cli-authorize",
            },
        )
        self.assertEqual(authorize_status, 200, authorize_body)
        self.assertEqual(authorize_body, {"authorized": True})
        cookies = self._cookies_from(authorize_headers)
        self.assertIn("sentinel_bootstrap", cookies)
        csrf_nonce = authorize_headers.get("x-sentinel-csrf")
        self.assertIsInstance(csrf_nonce, str)
        cookies["__Host-sentinel_csrf"] = csrf_nonce

        database = make_url(database_url)
        database_port = int(
            service_environment[
                f"SENTINEL_E2E_{'POSTGRES' if database_kind == 'postgresql' else 'MYSQL'}_PORT"
            ]
        )
        request_key = "installed-cli-first-run-acceptance"
        admin_username = _INSTALLED_ADMIN_USERNAME
        admin_password = _INSTALLED_ADMIN_PASSWORD
        consul_url = service_environment.get(_RUN_CONSUL_URL_ENV)
        source_endpoint = consul_url or "https://consul.acceptance.invalid:8501"
        source_authentication = {"mode": "none"}
        if consul_token := os.environ.get(_RUN_CONSUL_TOKEN_ENV):
            source_authentication = {"mode": "direct", "aclToken": consul_token}
        default_source: dict[str, object] = {
            "provider": "consul",
            "endpoint": source_endpoint,
            "datacenter": "dc1" if consul_url else "dc-test",
            "authentication": source_authentication,
        }
        initialize_body = {
            "requestKey": request_key,
            "input": {
                "database": {
                    "kind": database_kind,
                    "host": "127.0.0.1",
                    "port": database_port,
                    "database": database.database,
                    "username": database.username,
                    "password": database.password,
                },
                "admin": {
                    "username": admin_username,
                    "password": admin_password,
                },
                "source": initial_source
                if initial_source is not None
                else default_source,
            },
        }
        cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())
        try:
            initialize_status, initialize_receipt, _ = self._request_json(
                url + "/api/v1/system/bootstrap/initialize",
                method="POST",
                body=initialize_body,
                headers={
                    "origin": origin,
                    "cookie": cookie_header,
                    "x-sentinel-csrf": csrf_nonce,
                    "idempotency-key": request_key,
                    "x-request-id": "installed-cli-initialize",
                },
            )
        except TimeoutError:
            # A committed first-run operation may outlive the HTTP client's
            # bounded wait. Recover only through the original grant and key;
            # never replay this destructive one-time initialization command.
            initialize_status, initialize_receipt, _ = self._request_json(
                url + f"/api/v1/system/bootstrap/operations/{request_key}",
                method="GET",
                headers={
                    "cookie": cookie_header,
                    "x-request-id": "installed-cli-initialize-recovery",
                },
            )
        self.assertEqual(initialize_status, 200, initialize_receipt)
        self.assertEqual(initialize_receipt.get("status"), "completed")
        self.assertEqual(initialize_receipt.get("requestKey"), request_key)
        self.assertNotIn(admin_password, json.dumps(initialize_receipt))
        consul_token = os.environ.get(_RUN_CONSUL_TOKEN_ENV)
        self.assertNotIn(consul_token or "\0", json.dumps(initialize_receipt))
        self.assertNotIn(
            service_environment["SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE"],
            json.dumps(initialize_receipt),
        )
        database_password = database.password
        for path_key in (
            "SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH",
            "SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH",
            "SENTINEL_CONSOLE_SETUP_WINDOW_PATH",
        ):
            state_bytes = Path(service_environment[path_key]).read_bytes()
            self.assertNotIn(admin_password.encode(), state_bytes)
            self.assertNotIn(database_password.encode(), state_bytes)
            self.assertNotIn(
                service_environment[
                    "SENTINEL_CONSOLE_BOOTSTRAP_OPERATOR_CODE"
                ].encode(),
                state_bytes,
            )

        operation_status, operation_receipt, _ = self._request_json(
            url + f"/api/v1/system/bootstrap/operations/{request_key}",
            method="GET",
            headers={
                "cookie": cookie_header,
                "x-request-id": "installed-cli-read-initialization-receipt",
            },
        )
        self.assertEqual(operation_status, 200)
        self.assertEqual(operation_receipt, initialize_receipt)

        initialized_status, initialized_body, _ = self._request_json(
            url + "/api/v1/system/bootstrap",
            method="GET",
            headers={
                "cookie": cookie_header,
                "x-request-id": "installed-cli-initialized-bootstrap",
            },
        )
        self.assertEqual(initialized_status, 200)
        self.assertEqual(initialized_body, {"initialized": True})

        rejected_status, rejected_body, _ = self._request_json(
            url + "/api/v1/system/bootstrap/initialize",
            method="POST",
            body=initialize_body,
            headers={
                "origin": origin,
                "cookie": cookie_header,
                "x-sentinel-csrf": csrf_nonce,
                "idempotency-key": request_key,
                "x-request-id": "installed-cli-reinitialize-rejected",
            },
        )
        self.assertEqual(rejected_status, 403)
        self.assertEqual(
            rejected_body.get("error", {}).get("code"), "bootstrap_unauthorized"
        )
        return admin_username

    def _assert_installed_live_consul_probe(
        self,
        port: int,
        temporary_directory: Path,
        service_environment: dict[str, str],
    ) -> None:
        consul_url = service_environment.get(_RUN_CONSUL_URL_ENV)
        self.assertIsInstance(consul_url, str)
        parsed_consul_url = urlsplit(consul_url)
        self.assertIn(parsed_consul_url.scheme, {"http", "https"})
        self.assertEqual(parsed_consul_url.hostname, "127.0.0.1")
        self.assertIsNotNone(parsed_consul_url.port)
        consul_token = os.environ.get(_RUN_CONSUL_TOKEN_ENV)
        expected_authentication_mode = "direct" if consul_token else "none"
        if consul_token:
            self.assertEqual(parsed_consul_url.scheme, "https")

        base_url = f"http://127.0.0.1:{port}"
        origin = "https://console.acceptance.invalid"
        bootstrap_status, _bootstrap_body, bootstrap_headers = self._request_json(
            base_url + "/api/v1/system/bootstrap",
            method="GET",
            headers={"x-request-id": "installed-cli-consul-csrf"},
        )
        self.assertEqual(bootstrap_status, 200)
        csrf_nonce = bootstrap_headers.get("x-sentinel-csrf")
        self.assertIsInstance(csrf_nonce, str)

        login_status, identity, login_headers = self._request_json(
            base_url + "/api/v1/auth/login",
            method="POST",
            body={
                "username": _INSTALLED_ADMIN_USERNAME,
                "password": _INSTALLED_ADMIN_PASSWORD,
            },
            headers={
                "origin": origin,
                "cookie": f"__Host-sentinel_csrf={csrf_nonce}",
                "x-sentinel-csrf": str(csrf_nonce),
                "x-request-id": "installed-cli-consul-admin-login",
            },
        )
        self.assertEqual(login_status, 200, identity)
        self.assertEqual(identity.get("roleId"), "admin")
        cookies = self._cookies_from(login_headers)
        self.assertIn("sentinel_session", cookies)
        csrf_nonce = login_headers.get("x-sentinel-csrf")
        self.assertIsInstance(csrf_nonce, str)
        cookies["__Host-sentinel_csrf"] = str(csrf_nonce)
        cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())

        sources_status, sources_body, _ = self._request_json(
            base_url + "/api/v1/system/sources",
            method="GET",
            headers={
                "cookie": cookie_header,
                "x-request-id": "installed-cli-consul-source-read",
            },
        )
        self.assertEqual(sources_status, 200, sources_body)
        consul_sources = [
            item
            for item in sources_body.get("items", [])
            if item.get("provider") == "consul"
        ]
        self.assertEqual(len(consul_sources), 1, sources_body)
        registered_source = consul_sources[0]
        self.assertEqual(registered_source.get("endpoint"), consul_url)
        self.assertEqual(
            registered_source.get("authenticationMode"),
            expected_authentication_mode,
        )
        self.assertNotIn(consul_token or "\0", json.dumps(sources_body))
        source_id = registered_source["id"]
        revision = registered_source["revision"]

        def check_source(authentication: dict[str, str], request_id: str):
            return self._request_json(
                base_url + "/api/v1/system/sources/check",
                method="POST",
                body={
                    "sourceId": source_id,
                    "expectedRevision": revision,
                    "source": {
                        "provider": "consul",
                        "endpoint": consul_url,
                        "datacenter": "dc1",
                        "authentication": authentication,
                    },
                },
                headers={
                    "origin": origin,
                    "cookie": cookie_header,
                    "x-sentinel-csrf": str(csrf_nonce),
                    "x-request-id": request_id,
                },
            )

        def read_connections(request_id: str) -> list[dict[str, object]]:
            status, body, _ = self._request_json(
                base_url + "/api/v1/system/connections",
                method="GET",
                headers={"cookie": cookie_header, "x-request-id": request_id},
            )
            self.assertEqual(status, 200, body)
            return body.get("items", [])

        before_probe = read_connections("installed-cli-consul-before-probe")
        matching_before = [
            item for item in before_probe if item.get("sourceId") == source_id
        ]
        self.assertEqual(len(matching_before), 1, before_probe)
        self.assertEqual(matching_before[0].get("state"), "unknown")

        candidate_authentication = (
            {"mode": "direct", "aclToken": "synthetic-invalid-consul-token"}
            if consul_token
            else {"mode": "none"}
        )
        candidate_status, candidate_body, _ = check_source(
            candidate_authentication, "installed-cli-consul-candidate-check"
        )
        self.assertEqual(candidate_status, 200, candidate_body)
        if consul_token:
            self.assertEqual(candidate_body.get("status"), "unreachable")
            self.assertEqual(candidate_body.get("reason"), "authentication")
            self.assertNotIn(
                "synthetic-invalid-consul-token", json.dumps(candidate_body)
            )
        else:
            self.assertEqual(candidate_body.get("status"), "reachable")
            self.assertEqual(candidate_body.get("capabilities"), ["read", "watch"])
        self.assertNotIn("token", json.dumps(candidate_body).lower())
        self.assertNotIn(consul_token or "\0", json.dumps(candidate_body))
        after_candidate = read_connections("installed-cli-consul-after-candidate")
        matching_after_candidate = [
            item for item in after_candidate if item.get("sourceId") == source_id
        ]
        self.assertEqual(len(matching_after_candidate), 1, after_candidate)
        self.assertEqual(matching_after_candidate[0].get("state"), "unknown")

        registered_status, registered_body, _ = check_source(
            {"mode": "keep"}, "installed-cli-consul-registered-check"
        )
        self.assertEqual(registered_status, 200, registered_body)
        self.assertEqual(registered_body.get("status"), "reachable")
        self.assertEqual(registered_body.get("capabilities"), ["read", "watch"])
        self.assertNotIn(consul_token or "\0", json.dumps(registered_body))
        after_registered = read_connections("installed-cli-consul-after-registered")
        matching_after_registered = [
            item for item in after_registered if item.get("sourceId") == source_id
        ]
        self.assertEqual(len(matching_after_registered), 1, after_registered)
        self.assertEqual(matching_after_registered[0].get("state"), "available")
        self.assertEqual(
            matching_after_registered[0].get("capabilities"), ["read", "watch"]
        )
        self.assertNotIn(_INSTALLED_ADMIN_PASSWORD, json.dumps(after_registered))
        self.assertNotIn(consul_token or "\0", json.dumps(after_registered))
        if consul_token:
            runtime_state = b"\n".join(
                path.read_bytes()
                for path in (
                    Path(service_environment["SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH"]),
                    Path(
                        service_environment["SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH"]
                    ),
                    Path(service_environment["SENTINEL_CONSOLE_SETUP_WINDOW_PATH"]),
                )
                if path.is_file()
            )
            self.assertNotIn(consul_token.encode(), runtime_state)
            service_log = (temporary_directory / "console.log").read_text(
                errors="replace"
            )
            self.assertNotIn(consul_token, service_log)

    def _assert_installed_live_nacos_probe(
        self,
        port: int,
        temporary_directory: Path,
        service_environment: dict[str, str],
        *,
        endpoint: str,
        password: str,
    ) -> None:
        base_url = f"http://127.0.0.1:{port}"
        origin = "https://console.acceptance.invalid"
        _, _, bootstrap_headers = self._request_json(
            base_url + "/api/v1/system/bootstrap",
            method="GET",
            headers={"x-request-id": "installed-cli-nacos-csrf"},
        )
        csrf_nonce = bootstrap_headers.get("x-sentinel-csrf")
        self.assertIsInstance(csrf_nonce, str)
        login_status, identity, login_headers = self._request_json(
            base_url + "/api/v1/auth/login",
            method="POST",
            body={
                "username": _INSTALLED_ADMIN_USERNAME,
                "password": _INSTALLED_ADMIN_PASSWORD,
            },
            headers={
                "origin": origin,
                "cookie": f"__Host-sentinel_csrf={csrf_nonce}",
                "x-sentinel-csrf": str(csrf_nonce),
                "x-request-id": "installed-cli-nacos-admin-login",
            },
        )
        self.assertEqual(login_status, 200, identity)
        cookies = self._cookies_from(login_headers)
        self.assertIn("sentinel_session", cookies)
        csrf_nonce = login_headers.get("x-sentinel-csrf")
        self.assertIsInstance(csrf_nonce, str)
        cookies["__Host-sentinel_csrf"] = str(csrf_nonce)
        cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())

        sources_status, sources_body, _ = self._request_json(
            base_url + "/api/v1/system/sources",
            method="GET",
            headers={
                "cookie": cookie_header,
                "x-request-id": "installed-cli-nacos-source-read",
            },
        )
        self.assertEqual(sources_status, 200, sources_body)
        nacos_sources = [
            item
            for item in sources_body.get("items", [])
            if item.get("provider") == "nacos"
        ]
        self.assertEqual(len(nacos_sources), 1, sources_body)
        registered_source = nacos_sources[0]
        self.assertEqual(registered_source.get("endpoint"), endpoint)
        self.assertEqual(registered_source.get("authenticationMode"), "direct")
        self.assertNotIn(password, json.dumps(sources_body))
        source_id = registered_source["id"]
        revision = registered_source["revision"]

        def check_source(authentication: dict[str, str], request_id: str):
            return self._request_json(
                base_url + "/api/v1/system/sources/check",
                method="POST",
                body={
                    "sourceId": source_id,
                    "expectedRevision": revision,
                    "source": {
                        "provider": "nacos",
                        "endpoint": endpoint,
                        "namespace": "public",
                        "authentication": authentication,
                    },
                },
                headers={
                    "origin": origin,
                    "cookie": cookie_header,
                    "x-sentinel-csrf": str(csrf_nonce),
                    "x-request-id": request_id,
                },
            )

        def read_connections(request_id: str) -> list[dict[str, object]]:
            status, body, _ = self._request_json(
                base_url + "/api/v1/system/connections",
                method="GET",
                headers={"cookie": cookie_header, "x-request-id": request_id},
            )
            self.assertEqual(status, 200, body)
            return body.get("items", [])

        before_probe = read_connections("installed-cli-nacos-before-probe")
        matching_before = [
            item for item in before_probe if item.get("sourceId") == source_id
        ]
        self.assertEqual(len(matching_before), 1, before_probe)
        self.assertEqual(matching_before[0].get("state"), "unknown")

        bad_password = "synthetic-invalid-nacos-password"
        rejected_status, rejected_body, _ = check_source(
            {"mode": "direct", "username": "nacos", "password": bad_password},
            "installed-cli-nacos-invalid-password",
        )
        self.assertEqual(rejected_status, 200, rejected_body)
        self.assertEqual(rejected_body.get("status"), "unreachable")
        self.assertEqual(rejected_body.get("reason"), "authentication")
        self.assertNotIn(bad_password, json.dumps(rejected_body))
        after_rejected = read_connections("installed-cli-nacos-after-rejected-check")
        matching_after_rejected = [
            item for item in after_rejected if item.get("sourceId") == source_id
        ]
        self.assertEqual(len(matching_after_rejected), 1, after_rejected)
        self.assertEqual(matching_after_rejected[0].get("state"), "unknown")

        accepted_status, accepted_body, _ = check_source(
            {"mode": "keep"}, "installed-cli-nacos-registered-check"
        )
        self.assertEqual(accepted_status, 200, accepted_body)
        self.assertEqual(accepted_body.get("status"), "reachable")
        self.assertEqual(accepted_body.get("capabilities"), ["read"])
        after_accepted = read_connections("installed-cli-nacos-after-accepted-check")
        matching_after_accepted = [
            item for item in after_accepted if item.get("sourceId") == source_id
        ]
        self.assertEqual(len(matching_after_accepted), 1, after_accepted)
        self.assertEqual(matching_after_accepted[0].get("state"), "available")
        self.assertEqual(matching_after_accepted[0].get("capabilities"), ["read"])

        for body in (accepted_body, after_accepted):
            self.assertNotIn(password, json.dumps(body))
        runtime_state = b"\n".join(
            path.read_bytes()
            for path in (
                Path(service_environment["SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH"]),
                Path(service_environment["SENTINEL_CONSOLE_BOOTSTRAP_AUTHORITY_PATH"]),
                Path(service_environment["SENTINEL_CONSOLE_SETUP_WINDOW_PATH"]),
            )
            if path.is_file()
        )
        self.assertNotIn(password.encode(), runtime_state)
        self.assertNotIn(bad_password.encode(), runtime_state)
        service_log = (temporary_directory / "console.log").read_text(errors="replace")
        self.assertNotIn(password, service_log)
        self.assertNotIn(bad_password, service_log)

    def _assert_installed_account_workflow(
        self,
        port: int,
        temporary_directory: Path,
        _service_environment: dict[str, str],
    ) -> None:
        base_url = f"http://127.0.0.1:{port}"
        origin = "https://console.acceptance.invalid"

        def login(username: str, password: str, label: str):
            bootstrap_status, _bootstrap, bootstrap_headers = self._request_json(
                base_url + "/api/v1/system/bootstrap",
                method="GET",
                headers={"x-request-id": f"installed-account-{label}-csrf"},
            )
            self.assertEqual(bootstrap_status, 200)
            csrf_nonce = bootstrap_headers.get("x-sentinel-csrf")
            self.assertIsInstance(csrf_nonce, str)
            login_status, identity, login_headers = self._request_json(
                base_url + "/api/v1/auth/login",
                method="POST",
                body={"username": username, "password": password},
                headers={
                    "origin": origin,
                    "cookie": f"__Host-sentinel_csrf={csrf_nonce}",
                    "x-sentinel-csrf": str(csrf_nonce),
                    "x-request-id": f"installed-account-{label}-login",
                },
            )
            self.assertEqual(login_status, 200, identity)
            cookies = self._cookies_from(login_headers)
            self.assertIn("sentinel_session", cookies)
            csrf_nonce = login_headers.get("x-sentinel-csrf")
            self.assertIsInstance(csrf_nonce, str)
            cookies["__Host-sentinel_csrf"] = str(csrf_nonce)
            return (
                "; ".join(f"{name}={value}" for name, value in cookies.items()),
                str(csrf_nonce),
                identity,
            )

        admin_cookie, admin_csrf, admin_identity = login(
            _INSTALLED_ADMIN_USERNAME,
            _INSTALLED_ADMIN_PASSWORD,
            "admin",
        )
        self.assertEqual(admin_identity.get("roleId"), "admin")
        account_query = "?page=1&pageSize=20&search="
        listed_status, listed_body, _ = self._request_json(
            base_url + "/api/v1/accounts" + account_query,
            method="GET",
            headers={
                "cookie": admin_cookie,
                "x-request-id": "installed-account-admin-list-before",
            },
        )
        self.assertEqual(listed_status, 200, listed_body)
        self.assertEqual(listed_body.get("total"), 1)
        self.assertEqual(listed_body["items"][0].get("builtIn"), True)
        self.assertNotIn("password", json.dumps(listed_body).lower())
        self.assertNotIn("hash", json.dumps(listed_body).lower())

        request_key = "installed-cli-create-viewer"
        viewer_password = "synthetic-installed-viewer-password-51"
        command = {
            "kind": "create",
            "requestKey": request_key,
            "input": {
                "username": "installed-viewer",
                "password": viewer_password,
                "roleId": "view",
            },
        }

        def create_viewer(request_id: str):
            return self._request_json(
                base_url + "/api/v1/accounts/commands",
                method="POST",
                body=command,
                headers={
                    "origin": origin,
                    "cookie": admin_cookie,
                    "x-sentinel-csrf": admin_csrf,
                    "idempotency-key": request_key,
                    "x-request-id": request_id,
                },
            )

        create_status, create_body, _ = create_viewer("installed-account-viewer-create")
        self.assertEqual(create_status, 200, create_body)
        self.assertEqual(create_body.get("status"), "completed")
        self.assertEqual(
            create_body.get("account", {}).get("username"), "installed-viewer"
        )
        self.assertEqual(create_body.get("account", {}).get("roleId"), "view")
        self.assertNotIn(viewer_password, json.dumps(create_body))

        replay_status, replay_body, _ = create_viewer("installed-account-viewer-replay")
        self.assertEqual(replay_status, 200, replay_body)
        self.assertEqual(replay_body, create_body)

        def mutate_account(request_key: str, payload: dict[str, object]):
            return self._request_json(
                base_url + "/api/v1/accounts/commands",
                method="POST",
                body=payload,
                headers={
                    "origin": origin,
                    "cookie": admin_cookie,
                    "x-sentinel-csrf": admin_csrf,
                    "idempotency-key": request_key,
                    "x-request-id": f"installed-account-command-{request_key}",
                },
            )

        viewer_cookie, viewer_csrf, viewer_identity = login(
            "installed-viewer", viewer_password, "viewer"
        )
        self.assertEqual(viewer_identity.get("roleId"), "view")
        denied_read_status, denied_read_body, _ = self._request_json(
            base_url + "/api/v1/accounts" + account_query,
            method="GET",
            headers={
                "cookie": viewer_cookie,
                "x-request-id": "installed-account-viewer-list-denied",
            },
        )
        self.assertEqual(denied_read_status, 403, denied_read_body)
        self.assertEqual(denied_read_body.get("error", {}).get("code"), "forbidden")

        denied_write_command = {
            "kind": "create",
            "requestKey": "installed-cli-viewer-write-denied",
            "input": {
                "username": "must-not-exist",
                "password": "synthetic-denied-password-52",
                "roleId": "admin",
            },
        }
        denied_write_status, denied_write_body, _ = self._request_json(
            base_url + "/api/v1/accounts/commands",
            method="POST",
            body=denied_write_command,
            headers={
                "origin": origin,
                "cookie": viewer_cookie,
                "x-sentinel-csrf": viewer_csrf,
                "idempotency-key": denied_write_command["requestKey"],
                "x-request-id": "installed-account-viewer-create-denied",
            },
        )
        self.assertEqual(denied_write_status, 403, denied_write_body)
        self.assertEqual(denied_write_body.get("error", {}).get("code"), "forbidden")

        viewer_account = create_body.get("account", {})
        self.assertIsInstance(viewer_account, dict)
        viewer_id = viewer_account.get("id")
        self.assertIsInstance(viewer_id, str)
        promote_key = "installed-cli-promote-viewer"
        promote_status, promote_body, _ = mutate_account(
            promote_key,
            {
                "kind": "role",
                "requestKey": promote_key,
                "accountId": viewer_id,
                "revision": "1",
                "roleId": "admin",
            },
        )
        self.assertEqual(promote_status, 200, promote_body)
        self.assertEqual(promote_body.get("status"), "completed")
        self.assertEqual(promote_body.get("account", {}).get("revision"), "2")
        elevated_status, elevated_identity, _ = self._request_json(
            base_url + "/api/v1/auth/me",
            method="GET",
            headers={
                "cookie": viewer_cookie,
                "x-request-id": "installed-account-viewer-role-refreshed",
            },
        )
        self.assertEqual(elevated_status, 200, elevated_identity)
        self.assertEqual(elevated_identity.get("roleId"), "admin")

        disable_key = "installed-cli-disable-viewer"
        disable_status, disable_body, _ = mutate_account(
            disable_key,
            {
                "kind": "status",
                "requestKey": disable_key,
                "accountId": viewer_id,
                "revision": "2",
                "status": "disabled",
            },
        )
        self.assertEqual(disable_status, 200, disable_body)
        self.assertEqual(disable_body.get("status"), "completed")
        self.assertEqual(disable_body.get("account", {}).get("status"), "disabled")
        disabled_session_status, disabled_session_body, _ = self._request_json_value(
            base_url + "/api/v1/auth/me",
            method="GET",
            headers={
                "cookie": viewer_cookie,
                "x-request-id": "installed-account-disabled-session-revoked",
            },
        )
        self.assertEqual(disabled_session_status, 200, disabled_session_body)
        self.assertIsNone(disabled_session_body)

        for key, mutation in (
            (
                "installed-cli-disable-builtin-admin",
                {"kind": "status", "status": "disabled"},
            ),
            (
                "installed-cli-demote-builtin-admin",
                {"kind": "role", "roleId": "view"},
            ),
        ):
            status, body, _ = mutate_account(
                key,
                {
                    **mutation,
                    "requestKey": key,
                    "accountId": admin_identity.get("accountId"),
                    "revision": "1",
                },
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body.get("status"), "rejected")
            self.assertEqual(body.get("reason"), "built_in")

        new_admin_password = "synthetic-installed-admin-password-53"
        password_status, password_body, password_headers = self._request_json(
            base_url + "/api/v1/auth/password",
            method="POST",
            body={
                "currentPassword": _INSTALLED_ADMIN_PASSWORD,
                "newPassword": new_admin_password,
            },
            headers={
                "origin": origin,
                "cookie": admin_cookie,
                "x-sentinel-csrf": admin_csrf,
                "x-request-id": "installed-account-admin-change-password",
            },
        )
        self.assertEqual(password_status, 200, password_body)
        self.assertEqual(password_body.get("sessionDisposition"), "reauthenticate")
        self.assertNotIn(new_admin_password, json.dumps(password_body))
        self.assertIn('sentinel_session=""', password_headers.get("set-cookie", ""))
        stale_session_status, stale_session_body, _ = self._request_json_value(
            base_url + "/api/v1/auth/me",
            method="GET",
            headers={
                "cookie": admin_cookie,
                "x-request-id": "installed-account-admin-session-revoked",
            },
        )
        self.assertEqual(stale_session_status, 200, stale_session_body)
        self.assertIsNone(stale_session_body)
        csrf_status, _csrf_body, csrf_headers = self._request_json(
            base_url + "/api/v1/system/bootstrap",
            method="GET",
            headers={"x-request-id": "installed-account-old-password-csrf"},
        )
        self.assertEqual(csrf_status, 200)
        login_csrf = csrf_headers.get("x-sentinel-csrf")
        self.assertIsInstance(login_csrf, str)
        old_password_status, old_password_body, _ = self._request_json(
            base_url + "/api/v1/auth/login",
            method="POST",
            body={
                "username": _INSTALLED_ADMIN_USERNAME,
                "password": _INSTALLED_ADMIN_PASSWORD,
            },
            headers={
                "origin": origin,
                "cookie": f"__Host-sentinel_csrf={login_csrf}",
                "x-sentinel-csrf": str(login_csrf),
                "x-request-id": "installed-account-admin-old-password-denied",
            },
        )
        self.assertEqual(old_password_status, 401, old_password_body)
        changed_admin_cookie, _, changed_admin_identity = login(
            _INSTALLED_ADMIN_USERNAME,
            new_admin_password,
            "admin-after-password-change",
        )
        self.assertEqual(changed_admin_identity.get("roleId"), "admin")
        changed_session_status, changed_session_body, _ = self._request_json_value(
            base_url + "/api/v1/auth/me",
            method="GET",
            headers={
                "cookie": changed_admin_cookie,
                "x-request-id": "installed-account-admin-new-session",
            },
        )
        self.assertEqual(changed_session_status, 200, changed_session_body)
        self.assertEqual(changed_session_body.get("roleId"), "admin")

        async def read_database_state() -> tuple[
            list[tuple[str, str, str, bool, str]], int
        ]:
            database_url = os.environ.get(_RUN_MYSQL_URL_ENV) or os.environ.get(
                _RUN_POSTGRES_URL_ENV
            )
            self.assertIsNotNone(database_url)
            engine = create_async_engine(database_url, hide_parameters=True)
            try:
                async with engine.connect() as connection:
                    account_rows = (
                        await connection.execute(
                            text(
                                "SELECT username, role_id, status, built_in, password_hash "
                                "FROM console_account ORDER BY username"
                            )
                        )
                    ).all()
                    operation_count = await connection.scalar(
                        text("SELECT COUNT(*) FROM console_account_operation")
                    )
                    return [tuple(row) for row in account_rows], int(operation_count)
            finally:
                await engine.dispose()

        rows, operation_count = asyncio.run(read_database_state())
        self.assertEqual(
            [row[:4] for row in rows],
            [
                ("installed-first-run-admin", "admin", "active", True),
                ("installed-viewer", "admin", "disabled", False),
            ],
        )
        stored_password_hashes = [row[4] for row in rows]
        self.assertTrue(all(stored_password_hashes))
        for secret in (_INSTALLED_ADMIN_PASSWORD, new_admin_password, viewer_password):
            self.assertNotIn(secret, stored_password_hashes)
        self.assertEqual(operation_count, 5)
        service_log = (temporary_directory / "console.log").read_text(errors="replace")
        self.assertNotIn("cartesian product", service_log.lower())
        for secret in (
            _INSTALLED_ADMIN_PASSWORD,
            new_admin_password,
            viewer_password,
            "synthetic-denied-password-52",
        ):
            self.assertNotIn(secret, service_log)

    def _assert_installed_rule_binding_receipt(
        self,
        port: int,
        _temporary_directory: Path,
        _service_environment: dict[str, str],
    ) -> None:
        base_url = f"http://127.0.0.1:{port}"
        origin = "https://console.acceptance.invalid"

        def login(label: str) -> tuple[str, str]:
            bootstrap_status, _bootstrap, bootstrap_headers = self._request_json(
                base_url + "/api/v1/system/bootstrap",
                method="GET",
                headers={"x-request-id": f"installed-rule-receipt-{label}-csrf"},
            )
            self.assertEqual(bootstrap_status, 200)
            csrf_nonce = bootstrap_headers.get("x-sentinel-csrf")
            self.assertIsInstance(csrf_nonce, str)
            login_status, identity, login_headers = self._request_json(
                base_url + "/api/v1/auth/login",
                method="POST",
                body={
                    "username": _INSTALLED_ADMIN_USERNAME,
                    "password": _INSTALLED_ADMIN_PASSWORD,
                },
                headers={
                    "origin": origin,
                    "cookie": f"__Host-sentinel_csrf={csrf_nonce}",
                    "x-sentinel-csrf": str(csrf_nonce),
                    "x-request-id": f"installed-rule-receipt-{label}-login",
                },
            )
            self.assertEqual(login_status, 200, identity)
            self.assertEqual(identity.get("roleId"), "admin")
            cookies = self._cookies_from(login_headers)
            self.assertIn("sentinel_session", cookies)
            next_csrf = login_headers.get("x-sentinel-csrf")
            self.assertIsInstance(next_csrf, str)
            cookies["__Host-sentinel_csrf"] = str(next_csrf)
            cookie_header = "; ".join(
                f"{name}={value}" for name, value in cookies.items()
            )
            return cookie_header, str(next_csrf)

        original_cookie, original_csrf = login("original")
        sources_status, sources_body, _ = self._request_json(
            base_url + "/api/v1/system/sources",
            method="GET",
            headers={
                "cookie": original_cookie,
                "x-request-id": "installed-rule-receipt-sources",
            },
        )
        self.assertEqual(sources_status, 200, sources_body)
        source = next(
            (
                item
                for item in sources_body.get("items", [])
                if isinstance(item, dict) and item.get("provider") == "consul"
            ),
            None,
        )
        self.assertIsNotNone(source, sources_body)
        assert isinstance(source, dict)

        request_key = "installed-cli-rule-binding-registration"
        binding_id = "installed-cli-rule-binding"
        command = {
            "requestKey": request_key,
            "bindingId": binding_id,
            "environmentId": "acceptance",
            "appId": "installed-console",
            "kind": "flow",
            "profile": "sentinel-flow-v1",
            "sourceId": source["id"],
            "sourceRevision": source["revision"],
            "target": {
                "provider": "consul",
                "datacenter": "dc1",
                "key": f"sentinel/rules/{binding_id}.json",
            },
        }
        register_status, registered, _ = self._request_json(
            base_url + "/api/v1/rulesets",
            method="POST",
            body=command,
            headers={
                "origin": origin,
                "cookie": original_cookie,
                "x-sentinel-csrf": original_csrf,
                "idempotency-key": request_key,
                "x-request-id": "installed-rule-receipt-register",
            },
        )
        self.assertEqual(register_status, 201, registered)
        self.assertEqual(registered.get("id"), binding_id)

        rotated_cookie, _rotated_csrf = login("rotated")
        replay_status, replay_body, _ = self._request_json(
            base_url + "/api/v1/rulesets",
            method="POST",
            body=command,
            headers={
                "origin": origin,
                "cookie": rotated_cookie,
                "x-sentinel-csrf": original_csrf,
                "idempotency-key": request_key,
                "x-request-id": "installed-rule-receipt-replay",
            },
        )
        self.assertEqual(replay_status, 403, replay_body)

        receipt_status, receipt, _ = self._request_json(
            base_url
            + f"/api/v1/rulesets/{binding_id}/registration-operations/{request_key}",
            method="GET",
            headers={
                "cookie": rotated_cookie,
                "x-request-id": "installed-rule-receipt-read",
            },
        )
        self.assertEqual(receipt_status, 200, receipt)
        self.assertEqual(receipt.get("status"), "completed")
        self.assertEqual(receipt.get("binding", {}).get("id"), binding_id)

    def _assert_initialized_database(
        self, database_url: str, *, expected_source_secret: str | None = None
    ) -> None:
        async def verify() -> tuple[int, int, int, int, int, object, object, object]:
            engine = create_async_engine(database_url, hide_parameters=True)
            try:
                async with engine.connect() as connection:
                    account = (
                        await connection.execute(
                            text(
                                "SELECT username, role_id, status, built_in, password_hash "
                                "FROM console_account"
                            )
                        )
                    ).one()
                    source_credential = await connection.scalar(
                        text("SELECT credential_payload FROM console_registered_source")
                    )
                    return (
                        int(
                            await connection.scalar(
                                text(
                                    "SELECT initialized FROM console_guard "
                                    "WHERE singleton_id = 1"
                                )
                            )
                        ),
                        int(
                            await connection.scalar(
                                text("SELECT COUNT(*) FROM console_account")
                            )
                        ),
                        int(
                            await connection.scalar(
                                text("SELECT COUNT(*) FROM console_registered_source")
                            )
                        ),
                        int(
                            await connection.scalar(
                                text(
                                    "SELECT COUNT(*) FROM console_initialization_operation"
                                )
                            )
                        ),
                        int(
                            await connection.scalar(
                                text("SELECT COUNT(*) FROM console_audit_event")
                            )
                        ),
                        account.username,
                        account.password_hash,
                        source_credential,
                    )
            finally:
                await engine.dispose()

        (
            initialized,
            accounts,
            sources,
            operations,
            audits,
            username,
            password_hash,
            source_credential,
        ) = asyncio.run(verify())
        self.assertEqual(
            (initialized, accounts, sources, operations, audits), (1, 1, 1, 1, 1)
        )
        self.assertEqual(username, "installed-first-run-admin")
        self.assertNotEqual(password_hash, "synthetic-installed-admin-password-42")
        if expected_source_secret is None:
            self.assertIsNone(source_credential)
        else:
            self.assertIsInstance(source_credential, bytes)
            self.assertNotIn(expected_source_secret.encode(), source_credential)

    def _request_json(
        self,
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object], object]:
        status, payload, headers = self._request_json_value(
            url, method=method, headers=headers, body=body
        )
        self.assertIsInstance(payload, dict)
        return status, payload, headers

    def _request_json_value(
        self,
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        body: dict[str, object] | None = None,
    ) -> tuple[int, object, object]:
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=(
                {"content-type": "application/json", **headers}
                if body is not None
                else headers
            ),
            method=method,
        )
        try:
            response = urlopen(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            payload = json.loads(response.read())
            return response.status, payload, response.headers

    @staticmethod
    def _cookies_from(headers: object) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for value in headers.get_all("Set-Cookie", []):
            parsed = SimpleCookie()
            parsed.load(value)
            cookies.update({name: morsel.value for name, morsel in parsed.items()})
        return cookies

    @staticmethod
    def _available_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])


@unittest.skipUnless(
    os.environ.get(_RUN_CONSUL_ACL_ACCEPTANCE_ENV) == "1",
    "requires the explicit disposable ACL-enabled Consul acceptance runner",
)
class InstalledCliConsulAclAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """Exercise installed-wheel source credentials and TLS against real Consul ACL."""

    async def test_installed_cli_uses_persisted_acl_source_over_verified_tls(
        self,
    ) -> None:
        from consul_acl_test_support import DisposableConsulAclServer

        database_url = os.environ.get(_RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_e2e_dependencies.sh for MySQL")
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        consul = DisposableConsulAclServer("sentinel/acceptance/installed-cli.json")
        await consul.start()
        try:
            token = consul.create_source_probe_token()
            with tempfile.TemporaryDirectory(
                prefix="sentinel-installed-consul-ca-", dir="/private/tmp"
            ) as raw:
                ca_path = Path(raw) / "consul-test-ca.pem"
                ca_path.write_text(consul.client_ca_pem, encoding="ascii")
                with patch.dict(
                    os.environ,
                    {
                        _RUN_CONSUL_URL_ENV: consul.endpoint,
                        _RUN_CONSUL_TOKEN_ENV: token,
                        "SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE": str(
                            ca_path
                        ),
                    },
                ):
                    runner = InstalledCliBootstrapAcceptanceTests()
                    consul.write_management_value(consul.key, b"acceptance value")
                    await asyncio.to_thread(
                        runner._run_installed_cli_acceptance,
                        database_url,
                        "mysql",
                        after_initialize=runner._assert_installed_live_consul_probe,
                        restart_before_callback=True,
                    )
            self.assertTrue(
                any(
                    request_token == token
                    for _, request_token in consul.observed_requests
                )
            )
            self.assertTrue(
                any(
                    request_token == "synthetic-invalid-consul-token"
                    for _, request_token in consul.observed_requests
                )
            )
            self.assertTrue(
                all(token not in path for path, _ in consul.observed_requests)
            )
        finally:
            await consul.close()

    async def test_installed_cli_postgresql_reads_and_checks_persisted_acl_source(
        self,
    ) -> None:
        from consul_acl_test_support import DisposableConsulAclServer

        database_url = os.environ.get(_RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest(
                "run through with_disposable_postgresql_acceptance.sh for PostgreSQL"
            )
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        consul = DisposableConsulAclServer("sentinel/acceptance/installed-cli.json")
        await consul.start()
        try:
            token = consul.create_source_probe_token()
            with tempfile.TemporaryDirectory(
                prefix="sentinel-installed-consul-ca-", dir="/private/tmp"
            ) as raw:
                ca_path = Path(raw) / "consul-test-ca.pem"
                ca_path.write_text(consul.client_ca_pem, encoding="ascii")
                with patch.dict(
                    os.environ,
                    {
                        _RUN_CONSUL_URL_ENV: consul.endpoint,
                        _RUN_CONSUL_TOKEN_ENV: token,
                        "SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE": str(
                            ca_path
                        ),
                    },
                ):
                    runner = InstalledCliBootstrapAcceptanceTests()
                    consul.write_management_value(consul.key, b"acceptance value")
                    await asyncio.to_thread(
                        runner._run_installed_cli_acceptance,
                        database_url,
                        "postgresql",
                        after_initialize=runner._assert_installed_live_consul_probe,
                        restart_before_callback=True,
                    )
            self.assertTrue(
                any(
                    request_token == token
                    for _, request_token in consul.observed_requests
                )
            )
            self.assertTrue(
                any(
                    request_token == "synthetic-invalid-consul-token"
                    for _, request_token in consul.observed_requests
                )
            )
            self.assertTrue(
                all(token not in path for path, _ in consul.observed_requests)
            )
        finally:
            await consul.close()


def temporary_cwd() -> str:
    """Use a neutral working directory so imports cannot resolve to the checkout."""
    return tempfile.gettempdir()


def _database_package_extra(database_kind: str) -> str:
    """Map the wire/database name to the package's optional driver extra."""
    return "postgres" if database_kind == "postgresql" else database_kind


if __name__ == "__main__":
    unittest.main()
