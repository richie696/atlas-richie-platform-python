"""Contract checks for authentication settings in the E2E middleware stack."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "deployment" / "kubernetes" / "e2e-middleware.yaml"
BOOTSTRAP_JOB_PATH = (
    PROJECT_ROOT / "deployment" / "kubernetes" / "nacos-bootstrap-job.yaml"
)
APPLY_SCRIPT_PATH = (
    PROJECT_ROOT / "deployment" / "kubernetes" / "apply-e2e-middleware.sh"
)


class E2EMiddlewareNacosAuthContractTests(unittest.TestCase):
    """Keep the Nacos 3 server auth switch aligned with its deployment contract."""

    def test_nacos_authentication_uses_the_supported_environment_variable(self) -> None:
        with MANIFEST_PATH.open(encoding="utf-8") as manifest:
            documents = tuple(yaml.safe_load_all(manifest))

        nacos = next(
            document
            for document in documents
            if isinstance(document, dict)
            and document.get("kind") == "Deployment"
            and document.get("metadata", {}).get("name") == "nacos"
        )
        container = _nacos_container(nacos)
        environment = {
            item["name"]: item.get("value")
            for item in container["env"]
            if "name" in item
        }

        self.assertEqual(environment.get("NACOS_AUTH_ENABLE"), "true")
        self.assertNotIn("NACOS_AUTH_ENABLED", environment)
        self.assertIn(
            "NACOS_AUTH_TOKEN",
            {item["name"] for item in container["env"]},
        )

    def test_bootstrap_job_reads_secret_and_hides_credentials(self) -> None:
        with BOOTSTRAP_JOB_PATH.open(encoding="utf-8") as manifest:
            job = yaml.safe_load(manifest)

        self.assertEqual(job["kind"], "Job")
        pod_spec = job["spec"]["template"]["spec"]
        self.assertFalse(pod_spec["automountServiceAccountToken"])
        container = pod_spec["containers"][0]
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        secret_refs = {
            item["name"]: item["valueFrom"]["secretKeyRef"]
            for item in container["env"]
        }
        self.assertEqual(
            secret_refs["NACOS_USERNAME"],
            {"name": "nacos-bootstrap-credentials", "key": "username"},
        )
        self.assertEqual(
            secret_refs["NACOS_PASSWORD"],
            {"name": "nacos-bootstrap-credentials", "key": "password"},
        )
        command = "\n".join(container["args"])
        self.assertIn("/nacos/v3/auth/user", command)
        self.assertIn('"${endpoint}/admin"', command)
        self.assertIn('"${endpoint}/login"', command)
        self.assertIn('"accessToken"', command)
        self.assertNotIn("echo $NACOS_PASSWORD", command)
        self.assertNotIn("echo $response", command)

    def test_apply_script_creates_credentials_and_waits_for_bootstrap(self) -> None:
        script = APPLY_SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("nacos-bootstrap-credentials", script)
        self.assertIn("nacos-bootstrap-job.yaml", script)
        self.assertIn("--for=condition=complete job/nacos-bootstrap", script)
        self.assertIn('existing_resources" == 0', script)
        self.assertIn('existing_resources" == "${#middleware_resources[@]}"', script)
        self.assertIn("refusing to reconcile resources automatically", script)


def _nacos_container(deployment: dict[str, Any]) -> dict[str, Any]:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    return next(
        container for container in containers if container.get("name") == "nacos"
    )
