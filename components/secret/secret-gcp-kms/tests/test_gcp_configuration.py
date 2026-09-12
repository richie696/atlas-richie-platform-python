"""Unit tests for `GcpConfigurationResolver`."""

from __future__ import annotations

import pytest

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_gcp_kms import GcpSecretProperties
from atlas_richie.secret_gcp_kms.configuration import GcpConfigurationResolver


def test_resolve_happy_path() -> None:
    p = GcpSecretProperties(project_id="my-project")
    resolved = GcpConfigurationResolver().resolve(p, provider_id="gcp-main")
    assert resolved.provider_id == "gcp-main"
    assert resolved.properties is p
    assert len(resolved.configuration_hash) == 64
    assert resolved.capability.can_read is True
    assert resolved.capability.can_list is False


def test_configuration_hash_changes_with_project() -> None:
    p1 = GcpSecretProperties(project_id="p1")
    p2 = GcpSecretProperties(project_id="p2")
    h1 = GcpConfigurationResolver().resolve(p1).configuration_hash
    h2 = GcpConfigurationResolver().resolve(p2).configuration_hash
    assert h1 != h2


def test_configuration_hash_changes_with_key_bindings() -> None:
    p1 = GcpSecretProperties(project_id="p")
    p2 = GcpSecretProperties(
        project_id="p",
        kms_key_bindings={"logical": "physical"},
    )
    h1 = GcpConfigurationResolver().resolve(p1).configuration_hash
    h2 = GcpConfigurationResolver().resolve(p2).configuration_hash
    assert h1 != h2


def test_capability_backend_is_gcp() -> None:
    assert SecretBackend.GCP.value == "gcp"
