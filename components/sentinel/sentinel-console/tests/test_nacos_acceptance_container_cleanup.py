"""Unit checks for recovering only Nacos containers owned by one acceptance run."""

from __future__ import annotations

import subprocess
from unittest import TestCase
from unittest.mock import patch

from rule_activation_plan_nacos_database_acceptance import (
    _find_owned_container_id,
)

_CONTAINER_ID = "a" * 64
_RUN_ID = "acceptance-run-123"


class NacosAcceptanceContainerCleanupTests(TestCase):
    @patch("rule_activation_plan_nacos_database_acceptance.subprocess.run")
    def test_recovers_container_id_when_owner_label_matches(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{_CONTAINER_ID} {_RUN_ID}\n",
            stderr="",
        )

        self.assertEqual(
            _find_owned_container_id("sentinel-nacos-acceptance", _RUN_ID),
            _CONTAINER_ID,
        )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(
            run.call_args.args[0][-1], "sentinel-nacos-acceptance"
        )

    @patch("rule_activation_plan_nacos_database_acceptance.subprocess.run")
    def test_refuses_container_owned_by_another_run(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{_CONTAINER_ID} another-run\n",
            stderr="",
        )

        with self.assertRaisesRegex(RuntimeError, "not owned by this run"):
            _find_owned_container_id("sentinel-nacos-acceptance", _RUN_ID)

    @patch("rule_activation_plan_nacos_database_acceptance.subprocess.run")
    def test_missing_container_is_not_an_error_when_docker_is_available(
        self, run
    ) -> None:
        run.side_effect = (
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),
        )

        self.assertIsNone(
            _find_owned_container_id("sentinel-nacos-acceptance", _RUN_ID)
        )
        self.assertEqual(run.call_count, 2)

    @patch("rule_activation_plan_nacos_database_acceptance.subprocess.run")
    def test_reports_unverifiable_cleanup_when_docker_is_unavailable(self, run) -> None:
        run.side_effect = (
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
        )

        with self.assertRaisesRegex(RuntimeError, "cannot verify"):
            _find_owned_container_id("sentinel-nacos-acceptance", _RUN_ID)
