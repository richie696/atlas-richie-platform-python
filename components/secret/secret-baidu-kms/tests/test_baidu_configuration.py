"""Baidu Cloud KMS configuration + properties tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_baidu_kms.configuration import (
    BaiduConfigurationResolver,
)
from atlas_richie.secret_baidu_kms.properties import (
    AuthType,
    BaiduSecretProperties,
)


@pytest.fixture
def base_kwargs() -> dict:
    return {
        "region": "bj",
        "kms_endpoint": "http://bkm.bj.baidubce.com",
        "auth_type": AuthType.ACCESS_KEY,
        "access_key_id": "ak-test-123",
        "access_key_secret": "sk-test-456",
        "kms_key_bindings": {"envelope": "kms-key-id-abc"},
    }


class TestBaiduRequired:
    def test_access_key_id_required(self) -> None:
        with pytest.raises(ValidationError):
            BaiduSecretProperties(
                access_key_secret="sk",
            )

    def test_access_key_secret_required(self) -> None:
        with pytest.raises(ValidationError):
            BaiduSecretProperties(
                access_key_id="ak",
            )

    def test_region_default(self) -> None:
        props = BaiduSecretProperties(
            access_key_id="ak",
            access_key_secret="sk",
        )
        assert props.region == "bj"
        assert props.kms_endpoint == "http://bkm.bj.baidubce.com"


class TestBaiduEndpoint:
    def test_endpoint_with_host_ok(self, base_kwargs) -> None:
        props = BaiduSecretProperties(**{**base_kwargs, "kms_endpoint": "https://bkm.bj.baidubce.com"})
        BaiduConfigurationResolver().resolve(props)

    def test_endpoint_no_host_rejected(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException):
            BaiduConfigurationResolver().resolve(
                BaiduSecretProperties(**{**base_kwargs, "kms_endpoint": "http://"}),
            )

    def test_endpoint_with_port(self, base_kwargs) -> None:
        props = BaiduSecretProperties(**{**base_kwargs, "kms_endpoint": "https://bkm.bj.baidubce.com:8443"})
        BaiduConfigurationResolver().resolve(props)


class TestBaiduAuth:
    def test_access_key_required(self, base_kwargs) -> None:
        kwargs = {k: v for k, v in base_kwargs.items() if k != "access_key_id"}
        with pytest.raises(SecretConfigurationException) as exc_info:
            BaiduConfigurationResolver().resolve(
                BaiduSecretProperties(**{**kwargs, "access_key_id": "   "}),
            )
        assert "SEC-BOOT-003" in str(exc_info.value)

    def test_access_key_secret_required(self, base_kwargs) -> None:
        kwargs = {k: v for k, v in base_kwargs.items() if k != "access_key_secret"}
        with pytest.raises(SecretConfigurationException) as exc_info:
            BaiduConfigurationResolver().resolve(
                BaiduSecretProperties(**{**kwargs, "access_key_secret": "   "}),
            )
        assert "SEC-BOOT-003" in str(exc_info.value)


class TestBaiduKeys:
    def test_blank_logical_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "kms_key_bindings": {"   ": "kms-key-id"}}
        with pytest.raises(ValidationError):
            BaiduSecretProperties(**bad)

    def test_blank_physical_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "kms_key_bindings": {"envelope": "  "}}
        with pytest.raises(ValidationError):
            BaiduSecretProperties(**bad)


class TestBaiduHash:
    def test_hash_is_64_hex(self, base_kwargs) -> None:
        props = BaiduSecretProperties(**base_kwargs)
        resolved = BaiduConfigurationResolver().resolve(props)
        assert len(resolved.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in resolved.configuration_hash)

    def test_hash_changes_with_region(self, base_kwargs) -> None:
        p1 = BaiduConfigurationResolver().resolve(
            BaiduSecretProperties(**base_kwargs),
        )
        p2 = BaiduConfigurationResolver().resolve(
            BaiduSecretProperties(**{**base_kwargs, "region": "gz"}),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_changes_with_endpoint(self, base_kwargs) -> None:
        p1 = BaiduConfigurationResolver().resolve(
            BaiduSecretProperties(**base_kwargs),
        )
        p2 = BaiduConfigurationResolver().resolve(
            BaiduSecretProperties(
                **{**base_kwargs, "kms_endpoint": "http://bkm.gz.baidubce.com"},
            ),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_changes_with_keys(self, base_kwargs) -> None:
        p1 = BaiduConfigurationResolver().resolve(
            BaiduSecretProperties(**base_kwargs),
        )
        p2 = BaiduConfigurationResolver().resolve(
            BaiduSecretProperties(
                **{**base_kwargs, "kms_key_bindings": {"other": "kms-key-id-xyz"}},
            ),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_stable(self, base_kwargs) -> None:
        props = BaiduSecretProperties(**base_kwargs)
        p1 = BaiduConfigurationResolver().resolve(props)
        p2 = BaiduConfigurationResolver().resolve(props)
        assert p1.configuration_hash == p2.configuration_hash

    def test_hash_includes_capability_fingerprint(self, base_kwargs) -> None:
        from atlas_richie.secret_baidu_kms.configuration import _baidu_kms_capability

        cap = _baidu_kms_capability()
        fp = capability_fingerprint(cap)
        assert "can_read=False" in fp
        assert "can_write=False" in fp
        assert "encrypts_at_rest=True" in fp


class TestBaiduCapability:
    def test_capability_kms_only(self, base_kwargs) -> None:
        props = BaiduSecretProperties(**base_kwargs)
        resolved = BaiduConfigurationResolver().resolve(props)
        assert resolved.capability.can_read is False
        assert resolved.capability.can_write is False
        assert resolved.capability.can_rotate is False
        assert resolved.capability.encrypts_at_rest is True
        assert resolved.capability.signs_values is False
        assert resolved.capability.cacheable is False

    def test_resolved_contains_provider_id(self, base_kwargs) -> None:
        props = BaiduSecretProperties(**base_kwargs)
        resolved = BaiduConfigurationResolver().resolve(
            props,
            provider_id="custom-id",
        )
        assert resolved.provider_id == "custom-id"
