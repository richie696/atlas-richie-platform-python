"""IBM Key Protect configuration + properties tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_ibm_key_protect.configuration import (
    IbmKeyProtectConfigurationResolver,
)
from atlas_richie.secret_ibm_key_protect.properties import (
    AuthType,
    IbmKeyProtectProperties,
)


@pytest.fixture
def base_kwargs() -> dict:
    return {
        "region": "us-south",
        "instance_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "auth_type": AuthType.BEARER_TOKEN,
        "bearer_token": "iam-token-abc",
        "kms_endpoint": "https://us-south.kms.cloud.ibm.com",
        "kms_key_bindings": {"envelope": "crn:v1:bluemix:public:kms:us-south:a/...:key:abcd-1234"},
    }


class TestIbmRequired:
    def test_region_required(self) -> None:
        with pytest.raises(ValidationError):
            IbmKeyProtectProperties(
                instance_id="a1b2c3d4",
                auth_type=AuthType.BEARER_TOKEN,
                bearer_token="t",
            )

    def test_instance_id_required(self) -> None:
        with pytest.raises(ValidationError):
            IbmKeyProtectProperties(
                region="us-south",
                auth_type=AuthType.BEARER_TOKEN,
                bearer_token="t",
            )

    def test_region_blank_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IbmKeyProtectProperties(
                region="   ",
                instance_id="a1b2c3d4",
                auth_type=AuthType.BEARER_TOKEN,
                bearer_token="t",
            )

    def test_instance_id_blank_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IbmKeyProtectProperties(
                region="us-south",
                instance_id="  ",
                auth_type=AuthType.BEARER_TOKEN,
                bearer_token="t",
            )

    def test_key_ring_default(self, base_kwargs) -> None:
        props = IbmKeyProtectProperties(**{**base_kwargs, "key_ring": "default"})
        assert props.key_ring == "default"


class TestIbmEndpoint:
    def test_https_endpoint_ok(self, base_kwargs) -> None:
        props = IbmKeyProtectProperties(**{**base_kwargs, "kms_endpoint": "https://us-south.kms.cloud.ibm.com"})
        IbmKeyProtectConfigurationResolver().resolve(props)

    def test_http_non_loopback_rejected(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException):
            IbmKeyProtectConfigurationResolver().resolve(
                IbmKeyProtectProperties(**{**base_kwargs, "kms_endpoint": "http://example.com"}),
            )

    def test_http_loopback_allowed(self, base_kwargs) -> None:
        # loopback http is allowed for dev
        props = IbmKeyProtectProperties(**{**base_kwargs, "kms_endpoint": "http://localhost:8080"})
        IbmKeyProtectConfigurationResolver().resolve(props)


class TestIbmAuth:
    def test_bearer_token_required(self, base_kwargs) -> None:
        # Remove bearer_token
        kwargs = {k: v for k, v in base_kwargs.items() if k != "bearer_token"}
        kwargs["bearer_token"] = None
        with pytest.raises(SecretConfigurationException) as exc_info:
            IbmKeyProtectConfigurationResolver().resolve(
                IbmKeyProtectProperties(**kwargs),
            )
        assert "SEC-BOOT-003" in str(exc_info.value)

    def test_bearer_token_blank_rejected(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException) as exc_info:
            IbmKeyProtectConfigurationResolver().resolve(
                IbmKeyProtectProperties(**{**base_kwargs, "bearer_token": "   "}),
            )
        assert "SEC-BOOT-003" in str(exc_info.value)


class TestIbmKeys:
    def test_blank_logical_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "kms_key_bindings": {"   ": "crn:..."}}
        with pytest.raises(ValidationError):
            IbmKeyProtectProperties(**bad)

    def test_blank_physical_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "kms_key_bindings": {"envelope": "  "}}
        with pytest.raises(ValidationError):
            IbmKeyProtectProperties(**bad)


class TestIbmHash:
    def test_hash_is_64_hex(self, base_kwargs) -> None:
        props = IbmKeyProtectProperties(**base_kwargs)
        resolved = IbmKeyProtectConfigurationResolver().resolve(props)
        assert len(resolved.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in resolved.configuration_hash)

    def test_hash_changes_with_region(self, base_kwargs) -> None:
        p1 = IbmKeyProtectConfigurationResolver().resolve(
            IbmKeyProtectProperties(**base_kwargs),
        )
        p2 = IbmKeyProtectConfigurationResolver().resolve(
            IbmKeyProtectProperties(**{**base_kwargs, "region": "eu-de"}),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_changes_with_instance_id(self, base_kwargs) -> None:
        p1 = IbmKeyProtectConfigurationResolver().resolve(
            IbmKeyProtectProperties(**base_kwargs),
        )
        p2 = IbmKeyProtectConfigurationResolver().resolve(
            IbmKeyProtectProperties(
                **{**base_kwargs, "instance_id": "ffffffff-1111-2222-3333-444444444444"},
            ),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_changes_with_keys(self, base_kwargs) -> None:
        p1 = IbmKeyProtectConfigurationResolver().resolve(
            IbmKeyProtectProperties(**base_kwargs),
        )
        p2 = IbmKeyProtectConfigurationResolver().resolve(
            IbmKeyProtectProperties(
                **{**base_kwargs, "kms_key_bindings": {"other": "crn:v1:..."}},
            ),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_stable(self, base_kwargs) -> None:
        props = IbmKeyProtectProperties(**base_kwargs)
        p1 = IbmKeyProtectConfigurationResolver().resolve(props)
        p2 = IbmKeyProtectConfigurationResolver().resolve(props)
        assert p1.configuration_hash == p2.configuration_hash

    def test_hash_includes_capability_fingerprint(self, base_kwargs) -> None:
        from atlas_richie.secret_ibm_key_protect.configuration import _ibm_kms_capability

        cap = _ibm_kms_capability()
        fp = capability_fingerprint(cap)
        assert "can_read=False" in fp
        assert "can_write=False" in fp
        assert "can_rotate=False" in fp
        assert "encrypts_at_rest=True" in fp


class TestIbmCapability:
    def test_capability_kms_only(self, base_kwargs) -> None:
        props = IbmKeyProtectProperties(**base_kwargs)
        resolved = IbmKeyProtectConfigurationResolver().resolve(props)
        assert resolved.capability.can_read is False
        assert resolved.capability.can_write is False
        assert resolved.capability.can_rotate is False
        assert resolved.capability.encrypts_at_rest is True
        assert resolved.capability.signs_values is False
        assert resolved.capability.cacheable is False

    def test_resolved_contains_provider_id(self, base_kwargs) -> None:
        props = IbmKeyProtectProperties(**base_kwargs)
        resolved = IbmKeyProtectConfigurationResolver().resolve(
            props,
            provider_id="custom-id",
        )
        assert resolved.provider_id == "custom-id"
