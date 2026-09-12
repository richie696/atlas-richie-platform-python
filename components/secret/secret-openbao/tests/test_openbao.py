"""`OpenBaoSecretProviderFactory` integration tests.

中文
----
覆盖:
- 工厂元数据(name / backend / version)
- 实际 session 5-SPI composite 行为(KV v2 读 + Transit wrap)
- 跟 `VaultSecretClient` 行为一致(API 100% 兼容)

English
--------
End-to-end integration tests for the OpenBao thin wrapper.
The HTTP traffic goes to a Vault dev server (since OpenBao
is API-compatible); the test's *branding* checks assert
`descriptor.backend == SecretBackend.OPENBAO`.
"""

from __future__ import annotations

import pytest

from atlas_richie.secret.crypto import CryptoContext, KeyPurpose, KeyReference
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret_openbao import (
    OpenBaoSecretProperties,
    OpenBaoSecretProviderFactory,
)

pytestmark = pytest.mark.integration


def test_factory_metadata_branding() -> None:
    properties = OpenBaoSecretProperties(
        url="http://127.0.0.1:8200", token="x",
    )
    factory = OpenBaoSecretProviderFactory(properties)
    assert factory.backend is SecretBackend.OPENBAO
    assert factory.name.startswith("openbao-")
    assert factory.version.endswith("-openbao")
    descriptor = factory.descriptor()
    assert descriptor.backend is SecretBackend.OPENBAO
    assert descriptor.name.startswith("openbao-")
    assert descriptor.version.endswith("-openbao")


def test_factory_explicit_name_overrides_prefix() -> None:
    properties = OpenBaoSecretProperties(
        url="http://127.0.0.1:8200", token="x",
    )
    factory = OpenBaoSecretProviderFactory(
        properties, name="my-custom-openbao",
    )
    assert factory.name == "my-custom-openbao"


def test_session_descriptor_branding(openbao_session) -> None:
    """The session's descriptor must carry SecretBackend.OPENBAO."""
    assert openbao_session.descriptor.backend is SecretBackend.OPENBAO
    assert openbao_session.descriptor.name.startswith("openbao-")


def test_session_kv_v2_read(openbao_session) -> None:
    """The composite `VaultSecretClient` is API-compatible with
    Vault's KV v2: a plain get round-trip works against the
    underlying server."""
    path = "openbao/smoke"
    openbao_session._hvac_client.secrets.kv.v2.create_or_update_secret(  # noqa: SLF001
        path=path, secret={"value": "openbao-plain"}, mount_point="secret",
    )
    ref = SecretReference(
        provider=openbao_session.descriptor.name, path=path,
    )
    value = openbao_session.get(ref)
    assert value.plaintext == b"openbao-plain"
    assert value.metadata.backend is SecretBackend.OPENBAO


def test_session_transit_wrap_unwrap(openbao_session) -> None:
    """Transit round-trip works through the OpenBao factory —
    same composite `VaultSecretClient` as the vault wheel."""
    kek = KeyReference(provider="openbao", key_id="test-key")
    dek = b"openbao-dek-32-bytes-padding-here"
    wrapped = openbao_session.wrap_key(dek, kek)
    assert wrapped.algorithm == "vault-transit"
    back = openbao_session.unwrap_key(
        wrapped, CryptoContext(primary_key=kek, purpose=KeyPurpose.WRAP),
    )
    assert back == dek


def test_session_is_vault_secret_client_instance(openbao_session) -> None:
    """The concrete return type of `OpenBaoSecretProviderFactory.create`
    is `VaultSecretClient` (re-used, not subclassed). The only
    difference vs. a Vault-only deployment is the
    `descriptor.backend` enum value."""
    from atlas_richie.secret_vault.client import VaultSecretClient
    assert isinstance(openbao_session, VaultSecretClient)
