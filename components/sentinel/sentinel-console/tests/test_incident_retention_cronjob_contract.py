"""Static contract checks for the deployment-owned incident retention job."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    PROJECT_ROOT / "deployment" / "kubernetes" / "incident-retention-cronjob.yaml"
)


class IncidentRetentionCronJobContractTests(unittest.TestCase):
    """Prove the checked-in template keeps its bounded, least-privilege contract."""

    document: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        with MANIFEST_PATH.open(encoding="utf-8") as manifest:
            document = yaml.safe_load(manifest)
        if not isinstance(document, dict):
            raise AssertionError("CronJob manifest must contain a YAML mapping")
        cls.document = document

    def setUp(self) -> None:
        self.assertEqual(self.document["apiVersion"], "batch/v1")
        self.assertEqual(self.document["kind"], "CronJob")
        self.assertEqual(
            self.document["metadata"]["name"],
            "sentinel-console-incident-retention",
        )
        self.spec = self.document["spec"]
        self.job_spec = self.spec["jobTemplate"]["spec"]
        self.pod_spec = self.job_spec["template"]["spec"]
        self.container = self.pod_spec["containers"][0]

    def test_schedule_is_daily_utc_and_overlapping_runs_are_forbidden(self) -> None:
        self.assertEqual(self.spec["schedule"], "17 3 * * *")
        self.assertEqual(self.spec["timeZone"], "Etc/UTC")
        self.assertEqual(self.spec["concurrencyPolicy"], "Forbid")
        self.assertFalse(self.spec["suspend"])

    def test_job_execution_is_bounded_and_does_not_restart_failed_pods(self) -> None:
        self.assertEqual(self.spec["startingDeadlineSeconds"], 1800)
        self.assertEqual(self.job_spec["backoffLimit"], 2)
        self.assertEqual(self.job_spec["activeDeadlineSeconds"], 300)
        self.assertEqual(self.job_spec["ttlSecondsAfterFinished"], 86400)
        self.assertEqual(self.pod_spec["restartPolicy"], "Never")

    def test_job_uses_the_cli_and_requires_an_immutable_image_to_be_supplied(
        self,
    ) -> None:
        self.assertEqual(self.container["command"], ["sentinel-console"])
        self.assertEqual(self.container["args"], ["incident-events", "expire"])
        self.assertEqual(
            self.container["image"], "replace-with-immutable-sentinel-console-image"
        )
        self.assertEqual(self.container["imagePullPolicy"], "IfNotPresent")

    def test_pod_and_container_security_are_least_privilege(self) -> None:
        self.assertFalse(self.pod_spec["automountServiceAccountToken"])
        pod_security = self.pod_spec["securityContext"]
        self.assertTrue(pod_security["runAsNonRoot"])
        self.assertEqual(pod_security["runAsUser"], 10001)
        self.assertEqual(pod_security["runAsGroup"], 10001)
        self.assertEqual(pod_security["seccompProfile"]["type"], "RuntimeDefault")

        container_security = self.container["securityContext"]
        self.assertFalse(container_security["allowPrivilegeEscalation"])
        self.assertTrue(container_security["readOnlyRootFilesystem"])
        self.assertEqual(container_security["capabilities"]["drop"], ["ALL"])

    def test_database_locator_and_ca_are_secret_mounted_not_embedded(self) -> None:
        environment = {item["name"]: item for item in self.container["env"]}
        self.assertEqual(
            environment["SENTINEL_CONSOLE_RUNTIME_LOCATOR_PATH"]["value"],
            "/var/lib/sentinel-console/runtime/runtime-database-locator.json",
        )
        for variable, key in (
            (
                "SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_ACTIVE_KEY_ID",
                "locator-active-key-id",
            ),
            ("SENTINEL_CONSOLE_RUNTIME_LOCATOR_SECRET_KEY_RING", "locator-key-ring"),
        ):
            reference = environment[variable]["valueFrom"]["secretKeyRef"]
            self.assertEqual(reference["name"], "sentinel-console-runtime-secrets")
            self.assertEqual(reference["key"], key)

        volumes = {item["name"]: item for item in self.pod_spec["volumes"]}
        self.assertEqual(
            volumes["runtime-state"]["persistentVolumeClaim"]["claimName"],
            "sentinel-console-runtime-state",
        )
        self.assertEqual(
            volumes["database-ca"]["secret"]["secretName"],
            "sentinel-console-database-ca",
        )
        mounts = {item["name"]: item for item in self.container["volumeMounts"]}
        self.assertEqual(
            mounts["runtime-state"]["mountPath"],
            "/var/lib/sentinel-console/runtime",
        )
        self.assertTrue(mounts["database-ca"]["readOnly"])
