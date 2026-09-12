"""Auth strategy tests — Token / Kubernetes / AppRole.

中文
----
`TokenAuthStrategy` 连真 Vault 验证 `is_authenticated()`;
Kubernetes / AppRole 走 unit path(不连真 Vault,因为本机没有
k8s / AppRole 角色),只校验构造期参数校验。

English
--------
Auth strategy tests. Token strategy talks to the real Vault;
Kubernetes and AppRole strategies only exercise the
config-validation path because the dev Vault has no k8s /
AppRole roles mounted.
"""

from __future__ import annotations

import pytest

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret_vault import AuthType, VaultSecretProperties
from atlas_richie.secret_vault.auth import (
    AppRoleAuthStrategy,
    KubernetesAuthStrategy,
    TokenAuthStrategy,
    auth_strategy_for,
)

pytestmark = pytest.mark.unit


def test_factory_selects_token() -> None:
    p = VaultSecretProperties(url="http://127.0.0.1:8200", token="x")
    assert isinstance(auth_strategy_for(p), TokenAuthStrategy)


def test_factory_selects_kubernetes() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        auth_type=AuthType.KUBERNETES,
        kubernetes_role="r",
    )
    assert isinstance(auth_strategy_for(p), KubernetesAuthStrategy)


def test_factory_selects_approle() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        auth_type=AuthType.APPROLE,
        approle_role_id="r",
        approle_secret_id="s",
    )
    assert isinstance(auth_strategy_for(p), AppRoleAuthStrategy)


def test_kubernetes_missing_file_raises() -> None:
    p = VaultSecretProperties(
        url="http://127.0.0.1:8200",
        auth_type=AuthType.KUBERNETES,
        kubernetes_role="r",
        kubernetes_service_account_token_path="/no/such/file",
    )
    strategy = auth_strategy_for(p)
    with pytest.raises(SecretConfigurationException) as exc:
        strategy.apply(client=None)  # type: ignore[arg-type]
    assert "service account JWT not found" in str(exc.value)


def test_approle_missing_creds_raises() -> None:
    # pydantic `model_validator` blocks this at construction time;
    # if it slipped through, the AppRoleAuthStrategy constructor
    # would also re-check.
    with pytest.raises(Exception):
        VaultSecretProperties(
            url="http://127.0.0.1:8200",
            auth_type=AuthType.APPROLE,
            approle_role_id="r",
            # approle_secret_id intentionally missing
        )


def test_kubernetes_constructor_validates_role() -> None:
    """pydantic blocks an empty role at construction time."""
    with pytest.raises(Exception):
        VaultSecretProperties(
            url="http://127.0.0.1:8200",
            auth_type=AuthType.KUBERNETES,
            kubernetes_role="",
        )


# --- Integration: Token strategy against real Vault ---------------------


@pytest.mark.integration
def test_token_strategy_authenticates(vault_client) -> None:
    p = VaultSecretProperties(
        url=vault_client.url,  # type: ignore[attr-defined]
        token="root-token-dev",
    )
    strategy = auth_strategy_for(p)
    strategy.apply(vault_client)
    assert vault_client.is_authenticated()
