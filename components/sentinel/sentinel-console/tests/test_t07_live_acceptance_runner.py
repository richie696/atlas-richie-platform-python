"""Safety and source-execution contracts for the T07.1 live runner."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
_RUNNER = _TOOLS / ".t07_live_acceptance_run.sh"
_PROTOCOL_ACCEPTANCE = _TOOLS / ".t07_protocol_incident_acceptance.sh"
_DETACHED_RUNNER = _TOOLS / ".t07_spawn_detached.mjs"


class T07LiveAcceptanceRunnerTests(unittest.TestCase):
    """Keep the runner on current source and scoped to owned dependencies."""

    def test_runner_refuses_to_start_without_owner_verified_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            docker_log = root / "docker.log"
            fake_docker = root / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            environment = os.environ.copy()
            for name in (
                "SENTINEL_E2E_DOCKER_RUN_ID",
                "SENTINEL_E2E_MYSQL_CONTAINER",
                "SENTINEL_E2E_MYSQL_DATABASE",
                "SENTINEL_E2E_MYSQL_USER",
                "SENTINEL_E2E_MYSQL_PASSWORD",
                "SENTINEL_E2E_MYSQL_PORT",
                "SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE",
                "SENTINEL_E2E_CONSUL_URL",
            ):
                environment.pop(name, None)
            environment["DOCKER_BIN"] = str(fake_docker)
            environment["FAKE_DOCKER_LOG"] = str(docker_log)

            result = subprocess.run(
                ["bash", str(_RUNNER)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=10,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run through with_disposable_e2e_dependencies.sh", result.stderr)
            self.assertFalse(docker_log.exists())

    def test_runner_uses_workspace_source_without_release_install_or_account_mutation(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")

        self.assertIn('uv_args=(run --project "$console_root"', source)
        self.assertIn('"$uv_bin" "${uv_args[@]}" sentinel-console serve', source)
        self.assertIn('"$uv_bin" "${uv_args[@]}" sentinel-console serve-metrics', source)
        self.assertIn("E2E runtime: source checkout via uv", source)
        self.assertNotIn("uv build --wheel", source)
        self.assertNotIn("uv pip install", source)
        self.assertNotIn("console_wheel", source)
        self.assertIn('"$SENTINEL_E2E_MYSQL_CONTAINER"', source)
        self.assertIn('[[ "$mysql_owner_run_id" != "$SENTINEL_E2E_DOCKER_RUN_ID" ]]', source)
        self.assertNotIn("ALTER USER", source)

    def test_runner_uses_current_dashboard_source_without_packaging_assets(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")

        self.assertIn('dashboard_root="$repo_root/components/sentinel/dashboard-prototype"', source)
        self.assertIn('"$node_bin" node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$ui_port" --strictPort', source)
        self.assertNotIn("SENTINEL_DASHBOARD_CLIENT_BUILD_DIR", source)
        self.assertNotIn("SENTINEL_CONSOLE_WEB_OUTPUT_DIR", source)
        self.assertNotIn("staging_console", source)
        self.assertIn('export SENTINEL_E2E_LIVE_MYSQL_CONSUL=1', source)
        self.assertIn('export SENTINEL_E2E_TEST_FILE="${SENTINEL_E2E_TEST_FILE:-live-bootstrap.e2e.test.mjs}"', source)
        self.assertIn("MySQL\\\\+Consul", source)

    def test_mock_browser_suite_uses_an_isolated_mock_vite_server(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")

        self.assertIn('mock_port="${SENTINEL_T07_MOCK_UI_PORT:-$(available_loopback_port)}"', source)
        self.assertIn("env -u VITE_CONSOLE_API_BASE_URL -u SENTINEL_CONSOLE_API_PROXY_TARGET", source)
        self.assertIn('VITE_CONSOLE_MODE=mock "$node_bin" node_modules/vite/bin/vite.js', source)
        self.assertIn('BASE_URL="http://localhost:${mock_port}"', source)
        self.assertIn("-u SENTINEL_E2E_TEST_FILE -u SENTINEL_E2E_TEST_FILES -u SENTINEL_E2E_TEST_NAME", source)
        self.assertIn("-u SENTINEL_E2E_LIVE -u SENTINEL_E2E_LIVE_SOURCE", source)
        self.assertIn("export SENTINEL_E2E_HEADLESS=1", source)
        self.assertIn("SENTINEL_E2E_HEADLESS=1 SENTINEL_E2E_KEEP_EDGE=0", source)
        self.assertIn('if [[ "${SENTINEL_T07_SKIP_MOCK_E2E:-0}" == 1 ]]; then', source)
        self.assertIn("export VITE_CONSOLE_MODE=live", source)
        self.assertIn('kill "$mock_preview_pid"', source)

        mock_suite = source.index('BASE_URL="http://localhost:${mock_port}"')
        mock_cleanup = source.index('mock_preview_pid=""', mock_suite)
        live_bootstrap_suite = source.index('"$node_bin" scripts/test/run-edge-e2e.mjs', mock_cleanup)
        live_identity_suite = source.index("SENTINEL_E2E_TEST_FILE=live-identity.e2e.test.mjs")
        self.assertLess(mock_suite, live_identity_suite)
        self.assertLess(live_bootstrap_suite, live_identity_suite)

    def test_live_runner_can_verify_durable_protocol_incident_lifecycle_in_one_run(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")
        protocol = _PROTOCOL_ACCEPTANCE.read_text(encoding="utf-8")

        self.assertIn('if [[ "${SENTINEL_T07_PROTOCOL_INCIDENTS:-0}" == 1 ]]; then', source)
        self.assertIn(".t07_protocol_incident_acceptance.sh", source)
        self.assertIn("consumer_runtime_driver.py", protocol)
        self.assertIn("LIVE PROTOCOL-01 / INCIDENT-01", protocol)
        self.assertIn("run_matrix_browser unknown unknown", protocol)
        self.assertIn("run_matrix_browser incompatible unknown", protocol)
        self.assertIn("run_matrix_browser incompatible compatible", protocol)
        self.assertIn('metrics-reporter revoke --principal "$matrix_principal"', protocol)
        self.assertIn("run_matrix_browser unknown unknown 1", protocol)

    def test_rust_focused_acceptance_skips_already_closed_suites(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")
        bootstrap_e2e = (_TOOLS.parent.parent / "dashboard-prototype/tests/e2e/live-bootstrap.e2e.test.mjs").read_text(encoding="utf-8")

        self.assertIn('focused_rust_acceptance="${SENTINEL_T07_FOCUSED_RUST_ACCEPTANCE:-0}"', source)
        self.assertIn('export SENTINEL_T07_SKIP_MOCK_E2E=1', source)
        self.assertIn('export SENTINEL_T07_RUNTIME_RECEIPTS=1', source)
        self.assertIn('runtime_languages=(RUST)', source)
        self.assertIn('if [[ "$focused_rust_acceptance" != 1 ]]; then', source)
        self.assertIn('"$focused_rust_acceptance" != 1 ]]; then', source)
        self.assertIn('starting Collector without replaying the completed baseline Rules E2E', source)
        self.assertIn(
            "Focused Rust T07.1 run: skipping already-closed Java/Go metrics and cross-runtime rule-observation suites.",
            source,
        )
        self.assertIn('"LIVE T07.1 prerequisite provisioning: fresh MySQL+Consul setup and first admin login"', bootstrap_e2e)
        self.assertIn("if (!focusedRustProvisioning)", bootstrap_e2e)

    def test_review_services_use_detached_process_groups(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")
        detached_runner = _DETACHED_RUNNER.read_text(encoding="utf-8")

        self.assertIn("start_detached", source)
        self.assertIn('"$uv_bin" "${uv_args[@]}" sentinel-console serve-metrics', source)
        self.assertIn("detached: true", detached_runner)
        self.assertIn("child.unref()", detached_runner)

    def test_failed_run_removes_only_its_owner_verified_rust_container(self) -> None:
        source = _RUNNER.read_text(encoding="utf-8")

        cleanup = source[source.index("cleanup() {"):source.index("trap cleanup EXIT")]
        removal = source[
            source.index("remove_owned_rust_container() {"):
            source.index("assert_port_free \"$ui_port\"")
        ]

        self.assertIn("remove_owned_rust_container", cleanup)
        self.assertIn('"$rust_container"', removal)
        self.assertIn('"$owner_run_id" == "${SENTINEL_E2E_DOCKER_RUN_ID:-}"', removal)
        self.assertIn('"$docker_bin" rm --force --volumes "$container_id"', removal)
        self.assertNotIn('rm --force --volumes "$rust_container"', removal)
