"""Unit tests for `AwsConfigurationResolver`."""

from __future__ import annotations

import pytest

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_aws_kms import AwsSecretProperties
from atlas_richie.secret_aws_kms.configuration import AwsConfigurationResolver


def test_resolve_happy_path() -> None:
    p = AwsSecretProperties(region="us-east-1")
    resolved = AwsConfigurationResolver().resolve(p, provider_id="aws-main")
    assert resolved.provider_id == "aws-main"
    assert resolved.properties is p
    assert len(resolved.configuration_hash) == 64
    assert resolved.capability.can_read is True
    assert resolved.capability.can_write is False
    assert resolved.capability.can_list is True
    assert resolved.capability.encrypts_at_rest is True


def test_resolve_rejects_path_traversal() -> None:
    p = AwsSecretProperties(
        region="us-east-1",
        secrets_manager_path_prefix="../escape",
    )
    with pytest.raises(SecretConfigurationException) as exc:
        AwsConfigurationResolver().resolve(p)
    assert "secrets_manager_path_prefix" in str(exc.value)


def test_resolve_rejects_leading_slash() -> None:
    p = AwsSecretProperties(
        region="us-east-1",
        secrets_manager_path_prefix="/abs",
    )
    with pytest.raises(SecretConfigurationException):
        AwsConfigurationResolver().resolve(p)


def test_configuration_hash_changes_with_region() -> None:
    p1 = AwsSecretProperties(region="us-east-1")
    p2 = AwsSecretProperties(region="us-west-2")
    h1 = AwsConfigurationResolver().resolve(p1).configuration_hash
    h2 = AwsConfigurationResolver().resolve(p2).configuration_hash
    assert h1 != h2


def test_configuration_hash_changes_with_key_bindings() -> None:
    p1 = AwsSecretProperties(region="us-east-1")
    p2 = AwsSecretProperties(
        region="us-east-1",
        kms_key_bindings={"logical": "arn:aws:kms:us-east-1:111:key/abc"},
    )
    h1 = AwsConfigurationResolver().resolve(p1).configuration_hash
    h2 = AwsConfigurationResolver().resolve(p2).configuration_hash
    assert h1 != h2


def test_capability_backend_is_aws() -> None:
    assert SecretBackend.AWS.value == "aws"
