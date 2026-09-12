"""Unit tests for `AwsSecretProperties` pydantic env injection.

中文
----
覆盖 `region` 必填 + `auth_type=profile` 子字段必填 +
`to_boto3_client_kwargs()` / `to_kms_client_kwargs()` /
`to_sm_client_kwargs()` 输出。不需要 localstack。

English
--------
Unit tests for env injection. No localstack required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_aws_kms import AwsAuthType, AwsSecretProperties

pytestmark = pytest.mark.unit


def test_region_required() -> None:
    with pytest.raises(ValidationError):
        AwsSecretProperties()


def test_region_must_be_nonempty() -> None:
    with pytest.raises(ValidationError):
        AwsSecretProperties(region="")


def test_default_auth_is_default_chain() -> None:
    p = AwsSecretProperties(region="us-east-1")
    assert p.auth_type is AwsAuthType.DEFAULT_CHAIN
    assert p.kms_signing_algorithm == "RSASSA_PSS_SHA_256"
    assert p.secrets_manager_path_prefix == ""


def test_profile_requires_profile_name() -> None:
    with pytest.raises(ValidationError) as exc:
        AwsSecretProperties(region="us-east-1", auth_type=AwsAuthType.PROFILE)
    assert "PROFILE_NAME" in str(exc.value)


def test_profile_with_name() -> None:
    p = AwsSecretProperties(
        region="us-east-1",
        auth_type=AwsAuthType.PROFILE,
        profile_name="my-app",
    )
    assert p.profile_name == "my-app"


def test_to_boto3_client_kwargs_no_endpoints() -> None:
    p = AwsSecretProperties(region="us-east-1")
    kwargs = p.to_boto3_client_kwargs()
    assert kwargs["region_name"] == "us-east-1"
    assert "endpoint_url" not in kwargs


def test_to_kms_client_kwargs_includes_endpoint() -> None:
    p = AwsSecretProperties(
        region="us-east-1",
        endpoint_kms="http://localhost:4566",
    )
    kwargs = p.to_kms_client_kwargs()
    assert kwargs["endpoint_url"] == "http://localhost:4566"


def test_to_sm_client_kwargs_includes_endpoint() -> None:
    p = AwsSecretProperties(
        region="us-east-1",
        endpoint_sm="http://localhost:4566",
    )
    kwargs = p.to_sm_client_kwargs()
    assert kwargs["endpoint_url"] == "http://localhost:4566"


def test_kms_key_bindings_default_empty() -> None:
    p = AwsSecretProperties(region="us-east-1")
    assert p.kms_key_bindings == {}


def test_kms_key_bindings_explicit() -> None:
    p = AwsSecretProperties(
        region="us-east-1",
        kms_key_bindings={"tenant-master": "arn:aws:kms:us-east-1:111:key/abc"},
    )
    assert p.kms_key_bindings == {"tenant-master": "arn:aws:kms:us-east-1:111:key/abc"}


def test_env_prefix_drives_field_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_AWS_REGION", "ap-east-1")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_AWS_KMS_SIGNING_ALGORITHM", "ECDSA_SHA_256")
    p = AwsSecretProperties()
    assert p.region == "ap-east-1"
    assert p.kms_signing_algorithm == "ECDSA_SHA_256"
