"""Barbican configuration + properties tests.

中文
----
验证:
- endpoint scheme / loopback 校验
- TOKEN / TOKEN_FILE 两种 auth 模式
- secrets 映射的 id 非空
- configuration_hash 是 64 hex 字符
- capability 与 Java `Set<SecretCapability>` 一致

English
--------
Tests for `BarbicanConfigurationResolver` +
`BarbicanSecretProperties`. 1:1 with Java
`BarbicanConfiguration.validate`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_barbican.configuration import (
    BarbicanConfigurationResolver,
    ResolvedBarbicanConfiguration,
)
from atlas_richie.secret_barbican.properties import (
    AuthType,
    BarbicanSecretMapping,
    BarbicanSecretProperties,
)


class TestBarbicanEndpoint:
    def test_https_endpoint_ok(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_token="x",
        )
        BarbicanConfigurationResolver().resolve(properties)

    def test_http_loopback_ok(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="http://127.0.0.1:9311",
            auth_token="x",
        )
        BarbicanConfigurationResolver().resolve(properties)

    def test_http_non_loopback_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            BarbicanSecretProperties(endpoint="http://barbican.example")

    def test_empty_endpoint_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            BarbicanSecretProperties(endpoint="")

    def test_endpoint_trailing_slash_stripped(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example/",
            auth_token="x",
        )
        # pydantic-level validator strips
        assert properties.endpoint == "https://barbican.example"


class TestBarbicanAuth:
    def test_token_auth_requires_token(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_type=AuthType.TOKEN,
        )
        with pytest.raises(SecretConfigurationException):
            BarbicanConfigurationResolver().resolve(properties)

    def test_token_file_auth_requires_path(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_type=AuthType.TOKEN_FILE,
        )
        with pytest.raises(SecretConfigurationException):
            BarbicanConfigurationResolver().resolve(properties)

    def test_token_auth_with_token_ok(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_type=AuthType.TOKEN,
            auth_token="token-abc",
        )
        BarbicanConfigurationResolver().resolve(properties)

    def test_token_file_auth_with_path_ok(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_type=AuthType.TOKEN_FILE,
            auth_token_file="/etc/barbican/token",
        )
        BarbicanConfigurationResolver().resolve(properties)


class TestBarbicanSecretMappings:
    def test_blank_id_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            BarbicanSecretProperties(
                endpoint="https://barbican.example",
                secrets={"db": BarbicanSecretMapping(id="")},
            )

    def test_valid_mapping_ok(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_token="x",
            secrets={"db": BarbicanSecretMapping(id="sec-123")},
        )
        resolved = BarbicanConfigurationResolver().resolve(properties)
        assert resolved.properties.secrets["db"].id == "sec-123"


class TestBarbicanProjectId:
    def test_project_id_with_double_dot_rejected(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            project_id="..",
        )
        with pytest.raises(SecretConfigurationException):
            BarbicanConfigurationResolver().resolve(properties)

    def test_project_id_ok(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            project_id="project-1",
            auth_token="x",
        )
        BarbicanConfigurationResolver().resolve(properties)


class TestBarbicanConfigurationHash:
    def test_hash_is_64_hex_chars(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_token="x",
        )
        resolved = BarbicanConfigurationResolver().resolve(properties)
        assert len(resolved.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in resolved.configuration_hash)

    def test_hash_changes_with_endpoint(self) -> None:
        a = BarbicanConfigurationResolver().resolve(
            BarbicanSecretProperties(
                endpoint="https://a.example", auth_token="x",
            ),
        )
        b = BarbicanConfigurationResolver().resolve(
            BarbicanSecretProperties(
                endpoint="https://b.example", auth_token="x",
            ),
        )
        assert a.configuration_hash != b.configuration_hash


class TestBarbicanCapability:
    def test_capability_matches_java(self) -> None:
        properties = BarbicanSecretProperties(
            endpoint="https://barbican.example",
            auth_token="x",
        )
        resolved = BarbicanConfigurationResolver().resolve(properties)
        cap = resolved.capability
        assert cap.can_read is True
        assert cap.can_write is False
        assert cap.can_rotate is False
        assert cap.can_list is False
        assert cap.encrypts_at_rest is True
        assert cap.signs_values is False
        assert cap.cacheable is True


__all__ = []
