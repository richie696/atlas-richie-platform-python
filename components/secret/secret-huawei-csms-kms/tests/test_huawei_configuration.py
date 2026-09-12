"""Huawei configuration + properties tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_huawei_csms_kms.configuration import (
    HuaweiConfigurationResolver,
    ResolvedHuaweiConfiguration,
)
from atlas_richie.secret_huawei_csms_kms.properties import (
    AuthType,
    HuaweiSecretProperties,
)


@pytest.fixture
def base_kwargs() -> dict:
    return {
        "region": "cn-north-4",
        "project_id": "project-1",
        "access_key_id": "AKID-test",
        "access_key_secret": "secret-test",
    }


class TestHuaweiRequired:
    def test_region_required(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            HuaweiSecretProperties(
                project_id="p",
                access_key_id="AKID",
                access_key_secret="secret",
            )

    def test_project_id_required(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            HuaweiSecretProperties(
                region="cn-north-4",
                access_key_id="AKID",
                access_key_secret="secret",
            )

    def test_access_key_id_required(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException):
            HuaweiConfigurationResolver().resolve(
                HuaweiSecretProperties(
                    **{**base_kwargs, "access_key_id": ""},
                ),
            )

    def test_access_key_secret_required(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException):
            HuaweiConfigurationResolver().resolve(
                HuaweiSecretProperties(
                    **{**base_kwargs, "access_key_secret": ""},
                ),
            )

    def test_minimal_config_ok(self, base_kwargs) -> None:
        properties = HuaweiSecretProperties(**base_kwargs)
        HuaweiConfigurationResolver().resolve(properties)


class TestHuaweiEndpoint:
    def test_https_secret_endpoint_ok(self, base_kwargs) -> None:
        properties = HuaweiSecretProperties(
            **base_kwargs,
            secret_endpoint="https://csms.cn-north-4.myhuaweicloud.com",
        )
        HuaweiConfigurationResolver().resolve(properties)

    def test_http_loopback_kms_endpoint_ok(self, base_kwargs) -> None:
        properties = HuaweiSecretProperties(
            **base_kwargs,
            kms_endpoint="http://127.0.0.1:8080",
        )
        HuaweiConfigurationResolver().resolve(properties)

    def test_http_non_loopback_kms_endpoint_rejected(self, base_kwargs) -> None:
        properties = HuaweiSecretProperties(
            **base_kwargs,
            kms_endpoint="http://kms.example.com",
        )
        with pytest.raises(SecretConfigurationException):
            HuaweiConfigurationResolver().resolve(properties)


class TestHuaweiSecretMappings:
    def test_blank_logical_rejected(self, base_kwargs) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            HuaweiSecretProperties(
                **base_kwargs,
                secrets={"": "prod/db"},
            )

    def test_blank_physical_rejected(self, base_kwargs) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            HuaweiSecretProperties(
                **base_kwargs,
                secrets={"db": "   "},
            )

    def test_blank_key_binding_physical_rejected(self, base_kwargs) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            HuaweiSecretProperties(
                **base_kwargs,
                kms_key_bindings={"default": "  "},
            )


class TestHuaweiConfigurationHash:
    def test_hash_is_64_hex_chars(self, base_kwargs) -> None:
        properties = HuaweiSecretProperties(**base_kwargs)
        resolved = HuaweiConfigurationResolver().resolve(properties)
        assert len(resolved.configuration_hash) == 64

    def test_hash_changes_with_region(self, base_kwargs) -> None:
        a = HuaweiConfigurationResolver().resolve(
            HuaweiSecretProperties(**{**base_kwargs, "region": "cn-north-4"}),
        )
        b = HuaweiConfigurationResolver().resolve(
            HuaweiSecretProperties(**{**base_kwargs, "region": "cn-east-2"}),
        )
        assert a.configuration_hash != b.configuration_hash

    def test_hash_changes_with_project_id(self, base_kwargs) -> None:
        a = HuaweiConfigurationResolver().resolve(
            HuaweiSecretProperties(**{**base_kwargs, "project_id": "p1"}),
        )
        b = HuaweiConfigurationResolver().resolve(
            HuaweiSecretProperties(**{**base_kwargs, "project_id": "p2"}),
        )
        assert a.configuration_hash != b.configuration_hash


class TestHuaweiCapability:
    def test_capability_matches_java(self, base_kwargs) -> None:
        properties = HuaweiSecretProperties(**base_kwargs)
        resolved = HuaweiConfigurationResolver().resolve(properties)
        cap = resolved.capability
        assert cap.can_read is True
        assert cap.can_write is False
        assert cap.can_rotate is True
        assert cap.can_list is False
        assert cap.encrypts_at_rest is True
        assert cap.signs_values is False
        assert cap.cacheable is True


__all__ = []
