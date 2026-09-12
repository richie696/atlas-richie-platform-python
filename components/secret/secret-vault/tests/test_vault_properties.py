"""Unit tests for `VaultSecretProperties` pydantic env injection.

中文
----
覆盖 `model_validator(mode="after")` 校验 + `to_hvac_client_kwargs()`
构造 + env 前缀 `ATLAS_RICHIE_SECRET_VAULT_` 解析。
不需要 Vault。

English
--------
Unit tests for `VaultSecretProperties`. No Vault required; the
test only exercises pydantic-settings env binding and the
auth-type → sub-field validator.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_richie.secret_vault import AuthType, VaultSecretProperties

pytestmark = pytest.mark.unit


def test_token_default_url_and_mounts() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x")
    assert p.auth_type is AuthType.TOKEN
    assert p.kv_mount == "secret"
    assert p.transit_mount == "transit"
    assert p.namespace == "atlas-richie-secret"
    assert p.timeout_seconds == 30.0
    assert p.max_retries == 3
    assert p.retry_backoff_seconds == 0.5
    assert p.verify_tls is True


def test_kubernetes_requires_role() -> None:
    with pytest.raises(ValidationError) as exc:
        VaultSecretProperties(
            url="http://127.0.0.1:8200",
            auth_type=AuthType.KUBERNETES,
        )
    assert "KUBERNETES_ROLE" in str(exc.value)


def test_approle_requires_role_and_secret() -> None:
    with pytest.raises(ValidationError) as exc:
        VaultSecretProperties(
            url="http://127.0.0.1:8200",
            auth_type=AuthType.APPROLE,
            approle_role_id="r",
        )
    assert "APPROLE_ROLE_ID" in str(exc.value) and "SECRET_ID" in str(exc.value)


def test_url_must_have_scheme() -> None:
    with pytest.raises(ValidationError) as exc:
        VaultSecretProperties(url="vault.local:8200", token="x")
    assert "http://" in str(exc.value)


def test_to_hvac_client_kwargs_token() -> None:
    p = VaultSecretProperties(url="https://v.example:8200", token="s.abc")
    kwargs = p.to_hvac_client_kwargs()
    assert kwargs["url"] == "https://v.example:8200"
    assert kwargs["token"] == "s.abc"
    assert kwargs["verify"] is True
    assert kwargs["timeout"] == 30.0


def test_to_hvac_client_kwargs_tls_off() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        token="x",
        verify_tls=False,
    )
    kwargs = p.to_hvac_client_kwargs()
    assert kwargs["verify"] is False


def test_to_hvac_client_kwargs_token_omitted_for_k8s() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        auth_type=AuthType.KUBERNETES,
        kubernetes_role="demo",
    )
    kwargs = p.to_hvac_client_kwargs()
    # Token must NOT be passed for K8s / AppRole (hvac would
    # otherwise short-circuit to the supplied token and ignore
    # the auth strategy).
    assert "token" not in kwargs


def test_env_prefix_drives_field_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_VAULT_URL", "http://from-env:8200")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_VAULT_TOKEN", "env-token")
    monkeypatch.setenv("ATLAS_RICHIE_SECRET_VAULT_KV_MOUNT", "kv-from-env")
    p = VaultSecretProperties()
    assert p.url == "http://from-env:8200"
    assert p.token == "env-token"
    assert p.kv_mount == "kv-from-env"


def test_transit_key_bindings_default_empty() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x")
    assert p.transit_key_bindings == {}


def test_transit_key_bindings_default_isolated_per_instance() -> None:
    """Two instances must not share a default-dict reference."""
    p1 = VaultSecretProperties(url="http://127.0.0.1:8200", token="x")
    p2 = VaultSecretProperties(url="http://127.0.0.1:8200", token="x")
    p1.transit_key_bindings["logical"] = "physical"
    assert p2.transit_key_bindings == {}


def test_transit_key_bindings_explicit() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        token="x",
        transit_key_bindings={"tenant-master": "prod/aes256-gcm96"},
    )
    assert p.transit_key_bindings == {"tenant-master": "prod/aes256-gcm96"}
