"""Unit tests for `AzureSecretProperties` pydantic env injection.

中文
----
覆盖 `vault_url` 必填 + scheme 校验 + key_bindings default。
不需要 Azure 凭证。

English
--------
Unit tests for env injection. No Azure credentials required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_azure_keyvault import (
    AzureKeyWrapAlgorithm,
    AzureSecretProperties,
)

pytestmark = pytest.mark.unit


def test_vault_url_required() -> None:
    with pytest.raises(ValidationError):
        AzureSecretProperties()


def test_vault_url_must_have_scheme() -> None:
    with pytest.raises(ValidationError) as exc:
        AzureSecretProperties(vault_url="my-vault.vault.azure.net/")
    assert "https://" in str(exc.value) or "http://" in str(exc.value)


def test_vault_url_accepts_trailing_slash() -> None:
    # The Azure SDK handles trailing slashes itself; the
    # pydantic layer preserves the caller's input verbatim.
    p = AzureSecretProperties(vault_url="https://my-vault.vault.azure.net/")
    assert p.vault_url == "https://my-vault.vault.azure.net/"


def test_default_key_wrap_algorithm() -> None:
    p = AzureSecretProperties(vault_url="https://x.vault.azure.net/")
    assert p.default_key_wrap_algorithm is AzureKeyWrapAlgorithm.RSA_OAEP_256


def test_key_bindings_default_empty() -> None:
    p = AzureSecretProperties(vault_url="https://x.vault.azure.net/")
    assert p.key_bindings == {}


def test_key_bindings_explicit() -> None:
    p = AzureSecretProperties(
        vault_url="https://x.vault.azure.net/",
        key_bindings={"tenant-master": "prod-rsa-2048"},
    )
    assert p.key_bindings == {"tenant-master": "prod-rsa-2048"}


def test_env_prefix_drives_field_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_AZURE_VAULT_URL", "https://env-vault.vault.azure.net/")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_AZURE_DEFAULT_KEY_WRAP_ALGORITHM", "rsa1_5")
    p = AzureSecretProperties()
    assert p.vault_url == "https://env-vault.vault.azure.net/"
    assert p.default_key_wrap_algorithm is AzureKeyWrapAlgorithm.RSA1_5
