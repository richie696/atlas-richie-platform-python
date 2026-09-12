"""OCI configuration + properties tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_oci_vault_kms.configuration import (
    OciConfigurationResolver,
    ResolvedOciConfiguration,
)
from atlas_richie.secret_oci_vault_kms.properties import (
    AuthType,
    OciSecretProperties,
)


@pytest.fixture
def base_kwargs() -> dict:
    return {
        "region": "us-ashburn-1",
        "auth_type": AuthType.NONE,
        "secrets": {"db": "ocid1.vaultsecret.oc1..abcd"},
        "kms_key_bindings": {"envelope": "ocid1.key.oc1..deadbeef"},
    }


class TestOciRequired:
    def test_region_required(self) -> None:
        with pytest.raises(ValidationError):
            OciSecretProperties(
                auth_type=AuthType.NONE,
                secrets={},
                kms_key_bindings={},
            )

    def test_region_blank_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OciSecretProperties(region="   ", auth_type=AuthType.NONE)

    def test_auth_type_default(self) -> None:
        props = OciSecretProperties(region="us-ashburn-1")
        assert props.auth_type is AuthType.NONE


class TestOciEndpoint:
    def test_https_endpoint_ok(self, base_kwargs) -> None:
        props = OciSecretProperties(**{**base_kwargs, "secret_endpoint": "https://secrets.us-ashburn-1.oraclecloud.com"})
        assert props.secret_endpoint.startswith("https://")

    def test_http_non_loopback_rejected(self, base_kwargs) -> None:
        with pytest.raises(SecretConfigurationException) as exc_info:
            OciConfigurationResolver().resolve(
                OciSecretProperties(**{**base_kwargs, "secret_endpoint": "http://example.com"}),
            )
        assert "https" in str(exc_info.value).lower() or "loopback" in str(exc_info.value).lower()

    def test_http_loopback_allowed(self, base_kwargs) -> None:
        # loopback http is allowed for dev
        props = OciSecretProperties(**{**base_kwargs, "secret_endpoint": "http://localhost:8080"})
        OciConfigurationResolver().resolve(props)
        # no exception

    def test_kms_endpoint_https_ok(self, base_kwargs) -> None:
        props = OciSecretProperties(**{**base_kwargs, "kms_endpoint": "https://kms.us-ashburn-1.oraclecloud.com"})
        OciConfigurationResolver().resolve(props)


class TestOciAuth:
    def test_instance_principal_ok(self, base_kwargs) -> None:
        props = OciSecretProperties(**{**base_kwargs, "auth_type": AuthType.NONE})
        OciConfigurationResolver().resolve(props)

    def test_resource_principal_ok(self, base_kwargs) -> None:
        props = OciSecretProperties(
            **{**base_kwargs, "auth_type": AuthType.WORKLOAD_IDENTITY_TOKEN_FILE, "workload_identity_token_file": "/var/run/token"},
        )
        OciConfigurationResolver().resolve(props)


class TestOciSecrets:
    def test_blank_logical_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "secrets": {"   ": "ocid1.secret"}}
        with pytest.raises(ValidationError):
            OciSecretProperties(**bad)

    def test_blank_physical_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "secrets": {"db": "  "}}
        with pytest.raises(ValidationError):
            OciSecretProperties(**bad)

    def test_blank_logical_in_bindings_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "kms_key_bindings": {"   ": "ocid1.key"}}
        with pytest.raises(ValidationError):
            OciSecretProperties(**bad)

    def test_blank_physical_in_bindings_rejected(self, base_kwargs) -> None:
        bad = {**base_kwargs, "kms_key_bindings": {"envelope": "  "}}
        with pytest.raises(ValidationError):
            OciSecretProperties(**bad)


class TestOciHash:
    def test_hash_is_64_hex(self, base_kwargs) -> None:
        props = OciSecretProperties(**base_kwargs)
        resolved = OciConfigurationResolver().resolve(props)
        assert len(resolved.configuration_hash) == 64
        assert all(c in "0123456789abcdef" for c in resolved.configuration_hash)

    def test_hash_changes_with_region(self, base_kwargs) -> None:
        p1 = OciConfigurationResolver().resolve(
            OciSecretProperties(**base_kwargs),
        )
        p2 = OciConfigurationResolver().resolve(
            OciSecretProperties(**{**base_kwargs, "region": "eu-frankfurt-1"}),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_changes_with_auth(self, base_kwargs) -> None:
        p1 = OciConfigurationResolver().resolve(
            OciSecretProperties(**base_kwargs),
        )
        p2 = OciConfigurationResolver().resolve(
            OciSecretProperties(
                **{**base_kwargs, "auth_type": AuthType.WORKLOAD_IDENTITY_TOKEN_FILE, "workload_identity_token_file": "/tmp/x"},
            ),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_changes_with_secrets(self, base_kwargs) -> None:
        p1 = OciConfigurationResolver().resolve(
            OciSecretProperties(**base_kwargs),
        )
        p2 = OciConfigurationResolver().resolve(
            OciSecretProperties(
                **{**base_kwargs, "secrets": {"other": "ocid1.vaultsecret.oc1..xyz"}},
            ),
        )
        assert p1.configuration_hash != p2.configuration_hash

    def test_hash_stable(self, base_kwargs) -> None:
        props = OciSecretProperties(**base_kwargs)
        p1 = OciConfigurationResolver().resolve(props)
        p2 = OciConfigurationResolver().resolve(props)
        assert p1.configuration_hash == p2.configuration_hash

    def test_hash_includes_capability_fingerprint(self, base_kwargs) -> None:
        # The OCI capability has can_read=True / can_rotate=True.
        # Verify the fingerprint string contains those flags.
        from atlas_richie.secret_oci_vault_kms.configuration import _oci_capability

        cap = _oci_capability()
        fp = capability_fingerprint(cap)
        assert "can_read=True" in fp
        assert "can_rotate=True" in fp
        assert "can_write=False" in fp


class TestOciCapability:
    def test_capability_secret_read(self, base_kwargs) -> None:
        props = OciSecretProperties(**base_kwargs)
        resolved = OciConfigurationResolver().resolve(props)
        assert resolved.capability.can_read is True
        assert resolved.capability.can_write is False
        assert resolved.capability.can_rotate is True
        assert resolved.capability.encrypts_at_rest is True
        assert resolved.capability.signs_values is False
        assert resolved.capability.cacheable is True

    def test_resolved_contains_provider_id(self, base_kwargs) -> None:
        props = OciSecretProperties(**base_kwargs)
        resolved = OciConfigurationResolver().resolve(props, provider_id="custom-id")
        assert resolved.provider_id == "custom-id"
