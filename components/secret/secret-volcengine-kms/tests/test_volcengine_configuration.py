"""Volcengine configuration + properties tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_volcengine_kms.configuration import (
    ResolvedVolcengineConfiguration,
    VolcengineConfigurationResolver,
)
from atlas_richie.secret_volcengine_kms.properties import (
    AuthType,
    VolcengineSecretProperties,
)


@pytest.fixture
def base_kwargs() -> dict:
    return {
        "region": "cn-beijing",
        "namespace": "atlas-orders",
        "access_key_id": "AKID-test",
        "access_key_secret": "secret-test",
    }


class TestVolcengineRequired:
    def test_region_required(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            VolcengineSecretProperties(
                namespace="n",
                access_key_id="AKID",
                access_key_secret="secret",
            )

    def test_namespace_required(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            VolcengineSecretProperties(
                region="cn-beijing",
                access_key_id="AKID",
                access_key_secret="secret",
            )

    def test_access_key_id_required(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException):
            VolcengineConfigurationResolver().resolve(
                VolcengineSecretProperties(
                    **{**base_kwargs, "access_key_id": ""},
                ),
            )

    def test_access_key_secret_required(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException):
            VolcengineConfigurationResolver().resolve(
                VolcengineSecretProperties(
                    **{**base_kwargs, "access_key_secret": ""},
                ),
            )

    def test_minimal_config_ok(self, base_kwargs) -> None:
        properties = VolcengineSecretProperties(**base_kwargs)
        VolcengineConfigurationResolver().resolve(properties)


class TestVolcengineEndpoint:
    def test_https_endpoint_ok(self, base_kwargs) -> None:
        properties = VolcengineSecretProperties(
            **base_kwargs,
            kms_endpoint="https://kms.cn-beijing.volcengineapi.com",
        )
        VolcengineConfigurationResolver().resolve(properties)

    def test_http_loopback_ok(self, base_kwargs) -> None:
        properties = VolcengineSecretProperties(
            **base_kwargs,
            kms_endpoint="http://127.0.0.1:8080",
        )
        VolcengineConfigurationResolver().resolve(properties)

    def test_http_non_loopback_rejected(self, base_kwargs) -> None:
        properties = VolcengineSecretProperties(
            **base_kwargs,
            kms_endpoint="http://kms.example.com",
        )
        with pytest.raises(SecretConfigurationException):
            VolcengineConfigurationResolver().resolve(properties)


class TestVolcengineKeyBindings:
    def test_blank_logical_rejected(self, base_kwargs) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            VolcengineSecretProperties(
                **base_kwargs,
                kms_key_bindings={"": "key-1"},
            )

    def test_blank_physical_rejected(self, base_kwargs) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            VolcengineSecretProperties(
                **base_kwargs,
                kms_key_bindings={"default": "  "},
            )


class TestVolcengineConfigurationHash:
    def test_hash_is_64_hex_chars(self, base_kwargs) -> None:
        properties = VolcengineSecretProperties(**base_kwargs)
        resolved = VolcengineConfigurationResolver().resolve(properties)
        assert len(resolved.configuration_hash) == 64

    def test_hash_changes_with_namespace(self, base_kwargs) -> None:
        a = VolcengineConfigurationResolver().resolve(
            VolcengineSecretProperties(**{**base_kwargs, "namespace": "n1"}),
        )
        b = VolcengineConfigurationResolver().resolve(
            VolcengineSecretProperties(**{**base_kwargs, "namespace": "n2"}),
        )
        assert a.configuration_hash != b.configuration_hash

    def test_hash_changes_with_region(self, base_kwargs) -> None:
        a = VolcengineConfigurationResolver().resolve(
            VolcengineSecretProperties(**{**base_kwargs, "region": "cn-beijing"}),
        )
        b = VolcengineConfigurationResolver().resolve(
            VolcengineSecretProperties(**{**base_kwargs, "region": "cn-shanghai"}),
        )
        assert a.configuration_hash != b.configuration_hash


class TestVolcengineCapability:
    def test_capability_matches_java(self, base_kwargs) -> None:
        properties = VolcengineSecretProperties(**base_kwargs)
        resolved = VolcengineConfigurationResolver().resolve(properties)
        cap = resolved.capability
        assert cap.can_read is False
        assert cap.can_write is False
        assert cap.can_rotate is False
        assert cap.can_list is False
        assert cap.encrypts_at_rest is True
        assert cap.signs_values is False
        assert cap.cacheable is False


__all__ = []
