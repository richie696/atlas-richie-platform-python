"""Unit tests for `VaultConfigurationResolver`.

中文
----
覆盖 path safety 校验 + `configuration_hash` 一致性 + capability
声明。不需要 Vault。

English
--------
Unit tests for path-safety validation, SHA-256 configuration
hashing, and the static `SecretCapability` declaration. No
Vault required.
"""

from __future__ import annotations

import pytest

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_vault import VaultSecretProperties
from atlas_richie.secret_vault.configuration import VaultConfigurationResolver


def _resolve(kv_mount: str = "secret", transit_mount: str = "transit") -> VaultConfigurationResolver:
    return VaultConfigurationResolver()


def test_resolve_happy_path() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        token="x",
        kv_mount="kv",
        transit_mount="trans",
    )
    resolved = _resolve().resolve(p, provider_id="vault-main")
    assert resolved.provider_id == "vault-main"
    assert resolved.properties is p
    assert len(resolved.configuration_hash) == 64  # SHA-256 hex
    assert resolved.capability.can_read is True
    assert resolved.capability.encrypts_at_rest is True
    assert resolved.capability.can_list is False


def test_resolve_rejects_path_traversal() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x", kv_mount="../escape")
    with pytest.raises(SecretConfigurationException) as exc:
        _resolve().resolve(p)
    assert "kv_mount" in str(exc.value)


def test_resolve_rejects_leading_slash() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x", transit_mount="/abs")
    with pytest.raises(SecretConfigurationException) as exc:
        _resolve().resolve(p)
    assert "transit_mount" in str(exc.value)


def test_resolve_rejects_trailing_slash() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x", transit_mount="evil/")
    with pytest.raises(SecretConfigurationException) as exc:
        _resolve().resolve(p)
    assert "transit_mount" in str(exc.value)


def test_resolve_rejects_scheme_injection() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        token="x",
        kv_mount="http://other",
    )
    with pytest.raises(SecretConfigurationException) as exc:
        _resolve().resolve(p)
    assert "kv_mount" in str(exc.value)


def test_configuration_hash_changes_with_mount() -> None:
    p1 = VaultSecretProperties(url="http://127.0.0.1:8200", token="x", kv_mount="a")
    p2 = VaultSecretProperties(url="http://127.0.0.1:8200", token="x", kv_mount="b")
    h1 = _resolve().resolve(p1).configuration_hash
    h2 = _resolve().resolve(p2).configuration_hash
    assert h1 != h2


def test_capability_backend_is_vault() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x")
    resolved = _resolve().resolve(p)
    # Vault backend is declared in `metadata.SecretBackend.VAULT`
    # (used by descriptor).
    assert SecretBackend.VAULT.value == "vault"
    assert resolved.capability.encrypts_at_rest is True
