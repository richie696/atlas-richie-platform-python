"""Safety tests for disposable Nacos database-acceptance cleanup."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import call, patch

from rule_publication_nacos_database_acceptance import (
    _CONTAINER_OWNER_LABEL,
    _NACOS_GRPC_PORT_OFFSET,
    _free_loopback_port_pair,
    _remove_owned_container,
)

_CONTAINER_ID = "a" * 64
_RUN_ID = "synthetic-run-id"


class NacosDatabaseAcceptanceCleanupTests(unittest.TestCase):
    """Cleanup must be fenced to the container owned by this test run."""

    def test_nacos_grpc_port_uses_the_provider_http_offset(self) -> None:
        http_port, grpc_port = _free_loopback_port_pair()

        self.assertGreater(http_port, 0)
        self.assertGreater(grpc_port, 0)
        self.assertEqual(grpc_port, http_port + _NACOS_GRPC_PORT_OFFSET)

    def test_removes_exact_container_id_after_owner_label_matches(self) -> None:
        inspection_format = (
            f'{{{{.Id}}}} {{{{ index .Config.Labels "{_CONTAINER_OWNER_LABEL}"' + " }}"
        )
        with patch(
            "rule_publication_nacos_database_acceptance.subprocess.run",
            side_effect=(
                subprocess.CompletedProcess([], 0, f"{_CONTAINER_ID} {_RUN_ID}\n", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 1, "", "No such object"),
                subprocess.CompletedProcess([], 0, "Docker is available", ""),
            ),
        ) as run:
            _remove_owned_container(_CONTAINER_ID, _RUN_ID)

        self.assertIn(
            call(
                ["docker", "container", "rm", "--force", _CONTAINER_ID],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ),
            run.call_args_list,
        )
        self.assertEqual(run.call_args_list[0].args[0][-1], _CONTAINER_ID)
        self.assertEqual(run.call_args_list[0].args[0][4], inspection_format)

    def test_refuses_container_with_different_owner_label(self) -> None:
        with (
            patch(
                "rule_publication_nacos_database_acceptance.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 0, f"{_CONTAINER_ID} another-run\n", ""
                ),
            ) as run,
            self.assertRaisesRegex(RuntimeError, "refusing to remove"),
        ):
            _remove_owned_container(_CONTAINER_ID, _RUN_ID)

        self.assertEqual(run.call_count, 1)
        self.assertNotIn("rm", run.call_args.args[0])

    def test_missing_container_is_clean_when_docker_is_available(self) -> None:
        with patch(
            "rule_publication_nacos_database_acceptance.subprocess.run",
            side_effect=(
                subprocess.CompletedProcess([], 1, "", "No such object"),
                subprocess.CompletedProcess([], 0, "Docker is available", ""),
            ),
        ) as run:
            _remove_owned_container(_CONTAINER_ID, _RUN_ID)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0], ["docker", "info"])


if __name__ == "__main__":
    unittest.main()
