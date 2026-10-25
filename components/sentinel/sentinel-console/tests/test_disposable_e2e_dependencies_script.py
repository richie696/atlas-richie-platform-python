"""Safety checks for the disposable E2E dependency wrapper."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "with_disposable_e2e_dependencies.sh"
)
_OS_METADATA_FILENAMES = frozenset({".DS_Store"})


class DisposableE2EDependenciesScriptTests(unittest.TestCase):
    """Verify exact-resource cleanup without invoking a real Docker daemon."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.directory = Path(self._temporary_directory.name)
        self.docker_log = self.directory / "docker.log"
        self.docker_created_log = self.directory / "docker-created.log"
        self.docker_state = self.directory / "docker-state"
        self.docker_state.mkdir()
        self.fake_docker = self.directory / "docker"
        self.fake_docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            'printf \'%s\\n\' "$*" >> "$FAKE_DOCKER_LOG"\n'
            'case "$1" in\n'
            '  info) [[ "${DOCKER_UNAVAILABLE:-0}" != 1 ]] ;;\n'
            "  container)\n"
            '    if [[ "$2" == inspect && "$3" == --format ]]; then\n'
            '      state="$FAKE_DOCKER_STATE/${@: -1}"\n'
            '      [[ -f "$state" ]] || exit 1\n'
            '      cat "$state"\n'
            "      exit 0\n"
            "    fi\n"
            '    if [[ "${CONTAINER_NAME_COLLISION:-0}" == 1 ]]; then exit 0; fi\n'
            "    exit 1 ;;\n"
            "  run)\n"
            '    if [[ "${FAIL_CONSUL_RUN:-0}" == 1 && "$*" == *hashicorp/consul* ]]; then exit 55; fi\n'
            "    name= label=\n"
            "    while (($#)); do\n"
            '      case "$1" in\n'
            '        --name) name="$2"; shift 2 ;;\n'
            '        --label) label="$2"; shift 2 ;;\n'
            "        *) shift ;;\n"
            "      esac\n"
            "    done\n"
            '    if [[ "${RACE_NAME_COLLISION:-0}" == 1 && "$name" == *-mysql-* ]]; then\n'
            "      printf '%064d external-owner\\n' 1 > \"$FAKE_DOCKER_STATE/$name\"\n"
            "      exit 125\n"
            "    fi\n"
            "    container_id=\"$(printf '%s' \"$name\" | openssl dgst -sha256 | awk '{print $NF}')\"\n"
            '    printf \'%s %s\\n\' "$container_id" "${label#*=}" >> "$FAKE_DOCKER_CREATED_LOG"\n'
            '    printf \'%s %s\\n\' "$container_id" "${label#*=}" > "$FAKE_DOCKER_STATE/$name"\n'
            "    exit 0 ;;\n"
            "  port)\n"
            "    if [[ \"$3\" == '3306/tcp' ]]; then "
            "printf '127.0.0.1:33061\\n'; "
            "else printf '127.0.0.1:38501\\n'; fi ;;\n"
            "  exec) exit 0 ;;\n"
            '  rm)\n'
            '    [[ "${FAIL_REMOVE:-0}" != 1 ]] || exit 56\n'
            '    container_id="${@: -1}"\n'
            '    for state in "$FAKE_DOCKER_STATE"/*; do\n'
            '      [[ -f "$state" ]] || continue\n'
            '      read -r state_id _ < "$state"\n'
            '      [[ "$state_id" != "$container_id" ]] || rm -f -- "$state"\n'
            '    done\n'
            '    exit 0 ;;\n'
            "  *) exit 90 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        self.fake_docker.chmod(0o755)

    def _run_owned_state_files(self) -> list[Path]:
        """Return only the state files this run created.

        macOS drops a `.DS_Store` metadata file into directories below the
        per-user temporary items folder. It is not a run-owned dependency, so
        cleanup assertions must not count it as a leftover container state.
        """
        return sorted(
            path
            for path in self.docker_state.iterdir()
            if path.name not in _OS_METADATA_FILENAMES
        )

    def _run(
        self,
        command: list[str],
        *,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["DOCKER_BIN"] = str(self.fake_docker)
        environment["FAKE_DOCKER_LOG"] = str(self.docker_log)
        environment["FAKE_DOCKER_CREATED_LOG"] = str(self.docker_created_log)
        environment["FAKE_DOCKER_STATE"] = str(self.docker_state)
        environment.update(extra_environment or {})
        return subprocess.run(
            ["bash", str(_SCRIPT), *command],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
        )

    def test_removes_only_the_two_uniquely_named_containers_on_success(self) -> None:
        capture_path = self.directory / "ca-path.txt"
        result = self._run(
            [
                "bash",
                "-c",
                " && ".join(  # noqa: FLY002 - keep the shell assertions individually auditable
                    [
                        'test -n "$SENTINEL_E2E_CONSUL_URL"',
                        'test -n "$SENTINEL_E2E_DOCKER_RUN_ID"',
                        'test -n "$SENTINEL_E2E_MYSQL_CONTAINER"',
                        '[[ "$SENTINEL_E2E_MYSQL_CONTAINER" == "sentinel-e2e-mysql-$SENTINEL_E2E_DOCKER_RUN_ID" ]]',
                        '[[ "$SENTINEL_CONSOLE_RUN_CONSUL_ACCEPTANCE" == 1 ]]',
                        'test -s "$SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE"',
                        'grep -q "log_bin_trust_function_creators=ON" "$SENTINEL_E2E_MYSQL_CONFIG"',
                        'openssl verify -CAfile "$SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE" "$SENTINEL_E2E_MYSQL_CERTIFICATE_DIRECTORY/server-cert.pem"',
                        'openssl x509 -in "$SENTINEL_E2E_MYSQL_CERTIFICATE_DIRECTORY/server-cert.pem" -checkhost localhost -noout',
                        'openssl x509 -in "$SENTINEL_E2E_MYSQL_CERTIFICATE_DIRECTORY/server-cert.pem" -checkip 127.0.0.1 -noout',
                        '[[ "$SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS" == *"mysql|127.0.0.1/32|33061"* ]]',
                        '[[ "$SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS" == *"postgresql|10.20.0.0/16|5432"* ]]',
                        '[[ "$SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS" == *"consul|127.0.0.1|127.0.0.1/32|38501"* ]]',
                        '[[ "$SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS" == *"nacos|nacos.internal|10.30.0.0/16|8848"* ]]',
                        'printf "%s" "$SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE" > "$SENTINEL_E2E_CAPTURE_PATH"',
                    ]
                ),
            ],
            extra_environment={
                "SENTINEL_E2E_CAPTURE_PATH": str(capture_path),
                "SENTINEL_CONSOLE_BOOTSTRAP_DATABASE_TARGETS": (
                    "postgresql|10.20.0.0/16|5432"
                ),
                "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                    "nacos|nacos.internal|10.30.0.0/16|8848"
                ),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        certificate_authority = Path(capture_path.read_text(encoding="utf-8"))
        self.assertFalse(certificate_authority.exists())
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        run_commands = [line for line in commands if line.startswith("run ")]
        removal_commands = [line for line in commands if line.startswith("rm ")]
        removed_ids = {line.split()[-1] for line in removal_commands}
        created_ids = {
            line.split()[0]
            for line in self.docker_created_log.read_text(encoding="utf-8").splitlines()
        }
        self.assertEqual(len(run_commands), 2)
        self.assertEqual(len(removed_ids), 2)
        self.assertEqual(removed_ids, created_ids)
        self.assertTrue(all("--volumes" in line for line in removal_commands))
        self.assertTrue(
            all("com.atlas-richie.sentinel-e2e.run=" in line for line in run_commands)
        )
        self.assertTrue(all(len(container_id) == 64 for container_id in removed_ids))

        self.assertTrue(all("127.0.0.1::" in line for line in run_commands))
        mysql_run = next(line for line in run_commands if "mysql:8.4.11" in line)
        consul_run = next(
            line for line in run_commands if "hashicorp/consul:1.21.1" in line
        )
        self.assertIn("--env MYSQL_PASSWORD", mysql_run)
        self.assertIn("--env MYSQL_ROOT_PASSWORD", mysql_run)
        self.assertNotIn("MYSQL_PASSWORD=", mysql_run)
        self.assertNotIn("MYSQL_ROOT_PASSWORD=", mysql_run)
        self.assertFalse(any("MYSQL_PWD=" in line for line in commands))
        self.assertEqual(mysql_run.count("--mount"), 2)
        self.assertIn("target=/etc/mysql/certs,readonly", mysql_run)
        self.assertIn(
            "target=/etc/mysql/conf.d/zz-sentinel-e2e-ssl.cnf,readonly", mysql_run
        )
        self.assertNotIn("--mount", consul_run)

    def test_retains_only_this_runs_dependencies_when_review_retention_is_requested(self) -> None:
        result = self._run(
            ["bash", "-c", "exit 0"],
            extra_environment={"SENTINEL_E2E_KEEP_DEPENDENCIES": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Retaining run-owned acceptance dependencies for review", result.stdout)
        created = self.docker_created_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(created), 2)
        retained_ids = {line.split()[0] for line in created}
        retained_state_ids = {
            state.read_text(encoding="utf-8").split()[0]
            for state in self._run_owned_state_files()
        }
        self.assertEqual(retained_state_ids, retained_ids)
        self.assertNotIn("rm --force --volumes", self.docker_log.read_text(encoding="utf-8"))

    def test_removes_created_containers_when_acceptance_command_fails(self) -> None:
        result = self._run(["bash", "-c", "exit 7"])

        self.assertEqual(result.returncode, 7)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(line.startswith("run ") for line in commands), 2)
        self.assertEqual(sum(line.startswith("rm ") for line in commands), 2)

    def test_review_retention_does_not_keep_dependencies_after_failed_acceptance(self) -> None:
        result = self._run(
            ["bash", "-c", "exit 7"],
            extra_environment={"SENTINEL_E2E_KEEP_DEPENDENCIES": "1"},
        )

        self.assertEqual(result.returncode, 7)
        self.assertNotIn("Retaining run-owned acceptance dependencies", result.stdout)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(line.startswith("rm ") for line in commands), 2)
        self.assertEqual(self._run_owned_state_files(), [])

    def test_explicit_failure_retention_keeps_only_this_runs_dependencies(self) -> None:
        result = self._run(
            ["bash", "-c", "exit 7"],
            extra_environment={"SENTINEL_E2E_KEEP_DEPENDENCIES_ON_FAILURE": "1"},
        )

        self.assertEqual(result.returncode, 7)
        self.assertIn("Retaining run-owned acceptance dependencies for review", result.stdout)
        created = self.docker_created_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(created), 2)
        retained_ids = {line.split()[0] for line in created}
        retained_state_ids = {
            state.read_text(encoding="utf-8").split()[0]
            for state in self._run_owned_state_files()
        }
        self.assertEqual(retained_state_ids, retained_ids)
        self.assertNotIn("rm --force --volumes", self.docker_log.read_text(encoding="utf-8"))

    def test_fails_successful_command_when_owned_container_cleanup_cannot_be_confirmed(
        self,
    ) -> None:
        result = self._run(["true"], extra_environment={"FAIL_REMOVE": "1"})

        self.assertEqual(result.returncode, 70)
        self.assertIn("could not be confirmed removed", result.stderr)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(line.startswith("rm ") for line in commands), 2)
        self.assertEqual(len(self._run_owned_state_files()), 2)

    def test_cleans_partial_start_when_second_container_creation_fails(self) -> None:
        result = self._run(["true"], extra_environment={"FAIL_CONSUL_RUN": "1"})

        self.assertEqual(result.returncode, 55)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(line.startswith("run ") for line in commands), 2)
        removal_commands = [line for line in commands if line.startswith("rm ")]
        removed_ids = {line.split()[-1] for line in removal_commands}
        self.assertEqual(len(removed_ids), 1)
        self.assertTrue(all("--volumes" in line for line in removal_commands))
        mysql_id = (
            self.docker_created_log.read_text(encoding="utf-8")
            .splitlines()[0]
            .split()[0]
        )
        self.assertEqual(removed_ids, {mysql_id})

    def test_forwards_termination_and_cleans_created_containers(self) -> None:
        environment = os.environ.copy()
        environment["DOCKER_BIN"] = str(self.fake_docker)
        environment["FAKE_DOCKER_LOG"] = str(self.docker_log)
        environment["FAKE_DOCKER_CREATED_LOG"] = str(self.docker_created_log)
        environment["FAKE_DOCKER_STATE"] = str(self.docker_state)
        process = subprocess.Popen(
            ["bash", str(_SCRIPT), "bash", "-c", "sleep 30"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.docker_log.exists():
                commands = self.docker_log.read_text(encoding="utf-8").splitlines()
                if sum(line.startswith("exec ") for line in commands) >= 2:
                    break
            time.sleep(0.05)
        else:
            self.fail(
                "disposable services did not reach readiness in the fake Docker run"
            )

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)

        self.assertEqual(process.returncode, 143, f"stdout={stdout}\nstderr={stderr}")
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(line.startswith("rm ") for line in commands), 2)

    def test_requires_a_command_before_checking_or_starting_docker(self) -> None:
        result = self._run([])

        self.assertEqual(result.returncode, 64)
        self.assertIn("Usage:", result.stderr)
        self.assertFalse(self.docker_log.exists())

    def test_does_not_start_containers_when_docker_daemon_is_unavailable(self) -> None:
        result = self._run(["true"], extra_environment={"DOCKER_UNAVAILABLE": "1"})

        self.assertEqual(result.returncode, 69)
        self.assertIn("No containers were started", result.stderr)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertFalse(any(line.startswith("run ") for line in commands))

    def test_refuses_a_generated_name_collision_without_removing_existing_data(
        self,
    ) -> None:
        result = self._run(
            ["true"], extra_environment={"CONTAINER_NAME_COLLISION": "1"}
        )

        self.assertEqual(result.returncode, 73)
        self.assertIn("Refusing to reuse existing container name", result.stderr)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertFalse(any(line.startswith("run ") for line in commands))
        self.assertFalse(any(line.startswith("rm ") for line in commands))

    def test_does_not_remove_a_foreign_container_created_after_preflight(self) -> None:
        result = self._run(["true"], extra_environment={"RACE_NAME_COLLISION": "1"})

        self.assertEqual(result.returncode, 125)
        commands = self.docker_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(line.startswith("run ") for line in commands), 1)
        self.assertFalse(any(line.startswith("rm ") for line in commands))
        foreign_containers = list(self.docker_state.glob("sentinel-e2e-mysql-*"))
        self.assertEqual(len(foreign_containers), 1)
        self.assertEqual(
            foreign_containers[0].read_text(encoding="utf-8").split()[1],
            "external-owner",
        )


if __name__ == "__main__":
    unittest.main()
