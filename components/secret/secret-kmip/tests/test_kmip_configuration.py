"""KMIP configuration resolver + properties tests.

中文
----
验证:
- `endpoint` scheme / loopback 校验
- `protocol_major` / `protocol_minor` 范围
- `key_bindings` 的 logical / physical 校验
- `configuration_hash` 是 64 hex 字符

English
--------
Tests for `KmipConfigurationResolver` + `KmipSecretProperties`.
1:1 with Java `KmipSecretConfiguration.validate`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_kmip.configuration import (
    KmipConfigurationResolver,
    ResolvedKmipConfiguration,
)
from atlas_richie.secret_kmip.properties import KmipSecretProperties


class TestKmipEndpointValidation:
    def test_kmips_endpoint_ok(self) -> None:
        properties = KmipSecretProperties(endpoint="kmips://kmip.example:5696")
        KmipConfigurationResolver().resolve(properties)

    def test_https_endpoint_ok(self) -> None:
        properties = KmipSecretProperties(endpoint="https://kmip.example:5696")
        KmipConfigurationResolver().resolve(properties)

    def test_http_loopback_ok(self) -> None:
        properties = KmipSecretProperties(endpoint="http://localhost:5696")
        KmipConfigurationResolver().resolve(properties)

    def test_http_non_loopback_rejected(self) -> None:
        # pydantic catches the http://kmip.example case at the
        # properties level (its validator runs first). Both
        # signals are semantically equivalent "rejected".
        with pytest.raises((SecretConfigurationException, ValidationError)):
            KmipSecretProperties(endpoint="http://kmip.example:5696")

    def test_endpoint_with_userinfo_rejected(self) -> None:
        properties = KmipSecretProperties(
            endpoint="kmips://user:pass@kmip.example:5696",
        )
        with pytest.raises(SecretConfigurationException):
            KmipConfigurationResolver().resolve(properties)

    def test_endpoint_with_query_rejected(self) -> None:
        properties = KmipSecretProperties(
            endpoint="kmips://kmip.example:5696?foo=bar",
        )
        with pytest.raises(SecretConfigurationException):
            KmipConfigurationResolver().resolve(properties)


class TestKmipProtocolVersion:
    def test_protocol_major_out_of_range_rejected(self) -> None:
        # pydantic-level `Field(ge=1, le=2)` catches 3.
        with pytest.raises((SecretConfigurationException, ValidationError)):
            KmipSecretProperties(
                endpoint="kmips://kmip.example:5696",
                protocol_major=3,
            )

    def test_protocol_minor_out_of_range_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            KmipSecretProperties(
                endpoint="kmips://kmip.example:5696",
                protocol_minor=10,
            )


class TestKmipKeyBindings:
    def test_blank_logical_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            KmipSecretProperties(
                endpoint="kmips://kmip.example:5696",
                key_bindings={"": "key-1"},
            )

    def test_blank_physical_rejected(self) -> None:
        with pytest.raises((SecretConfigurationException, ValidationError)):
            KmipSecretProperties(
                endpoint="kmips://kmip.example:5696",
                key_bindings={"default": "  "},
            )

    def test_logical_with_double_dot_rejected(self) -> None:
        properties = KmipSecretProperties(
            endpoint="kmips://kmip.example:5696",
            key_bindings={"db..orders": "key-1"},
        )
        with pytest.raises(SecretConfigurationException):
            KmipConfigurationResolver().resolve(properties)

    def test_valid_binding_ok(self) -> None:
        properties = KmipSecretProperties(
            endpoint="kmips://kmip.example:5696",
            key_bindings={"default": "key-abc-123"},
        )
        resolved = KmipConfigurationResolver().resolve(properties)
        assert resolved.properties.key_bindings == {"default": "key-abc-123"}


class TestKmipConfigurationHash:
    def test_hash_is_64_hex_chars(self) -> None:
        properties = KmipSecretProperties(endpoint="kmips://kmip.example:5696")
        resolved = KmipConfigurationResolver().resolve(properties)
        assert len(resolved.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in resolved.configuration_hash)

    def test_hash_changes_with_endpoint(self) -> None:
        a = KmipConfigurationResolver().resolve(
            KmipSecretProperties(endpoint="kmips://a.example:5696"),
        )
        b = KmipConfigurationResolver().resolve(
            KmipSecretProperties(endpoint="kmips://b.example:5696"),
        )
        assert a.configuration_hash != b.configuration_hash

    def test_hash_stable_for_identical_config(self) -> None:
        properties = KmipSecretProperties(endpoint="kmips://kmip.example:5696")
        a = KmipConfigurationResolver().resolve(properties)
        b = KmipConfigurationResolver().resolve(properties)
        assert a.configuration_hash == b.configuration_hash


class TestKmipCapability:
    def test_capability_matches_java(self) -> None:
        properties = KmipSecretProperties(endpoint="kmips://kmip.example:5696")
        resolved = KmipConfigurationResolver().resolve(properties)
        cap = resolved.capability
        assert cap.can_read is False
        assert cap.can_write is False
        assert cap.can_rotate is False
        assert cap.can_list is False
        assert cap.encrypts_at_rest is True
        assert cap.signs_values is False
        assert cap.cacheable is False


__all__ = []
