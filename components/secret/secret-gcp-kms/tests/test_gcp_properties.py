"""Unit tests for `GcpSecretProperties`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_gcp_kms import GcpSecretProperties

pytestmark = pytest.mark.unit


def test_project_id_required() -> None:
    with pytest.raises(ValidationError):
        GcpSecretProperties()


def test_project_id_must_be_nonempty() -> None:
    with pytest.raises(ValidationError):
        GcpSecretProperties(project_id="   ")


def test_default_values() -> None:
    p = GcpSecretProperties(project_id="my-project")
    assert p.kms_location == "global"
    assert p.kms_key_ring == "atlas-richie"
    assert p.kms_key_bindings == {}


def test_kms_key_bindings_explicit() -> None:
    p = GcpSecretProperties(
        project_id="my-project",
        kms_key_bindings={
            "tenant-master": "projects/p/locations/global/keyRings/r/cryptoKeys/k",
        },
    )
    assert "tenant-master" in p.kms_key_bindings


def test_env_prefix_drives_field_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_GCP_PROJECT_ID", "env-project")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_GCP_KMS_LOCATION", "europe-west1")
    p = GcpSecretProperties()
    assert p.project_id == "env-project"
    assert p.kms_location == "europe-west1"
