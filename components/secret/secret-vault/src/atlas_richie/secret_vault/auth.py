"""Vault authentication strategies — Strategy + Factory 模式。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultClientFactory` 中
`authentication(...)` 私有方法。Java 端用 switch + 三类 Spring-Vault 的
`ClientAuthentication` 适配;Python 端用 **Strategy 模式** 把三种
auth 路径抽象成同一 Protocol,`auth_strategy_for(properties)` 工厂按
`properties.auth_type` 选择具体策略。

策略列表(对位 Java `VaultSecretProperties.AuthenticationType`,
本 wheel 收敛为 3 个 — Java 端的 TOKEN_FILE / JWT / AGENT 留给后续
secret-openbao 阶段或运行时 env 路由):

- `TokenAuthStrategy` — 静态 token 注入;`hvac.Client(token=...)` 已完成,
  `apply()` 校验 token 一致性
- `KubernetesAuthStrategy` — K8s service-account JWT 走
  `client.auth.kubernetes.login(role=..., jwt=...)`
- `AppRoleAuthStrategy` — AppRole 走
  `client.auth.approle.login(role_id=..., secret_id=...)`

`apply(client: hvac.Client) -> None` **就地** 给 client 注入 token,
不返回新对象。HVAC 客户端是可变对象,`apply` 后 `client.token` 即可用。
失败抛 `SecretException` / `SecretConfigurationException`,framework 层
能看到清晰的 secret-side 异常,而不是 hvac SDK 的私有类型。

English
--------
Vault authentication strategies. Mirrors the private
`authentication(...)` method in Java `VaultClientFactory`; the
Python side uses the Strategy pattern (one Protocol, three impls)
plus a small `auth_strategy_for(properties)` factory. Strategies
cover Token / Kubernetes / AppRole (Java-side TOKEN_FILE / JWT /
AGENT are deferred to secret-openbao or env-based runtime routing).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import hvac

from atlas_richie.secret.errors import SecretConfigurationException, SecretException
from atlas_richie.secret_vault.properties import AuthType, VaultSecretProperties

_logger = logging.getLogger("atlas_richie.secret_vault.auth")


@runtime_checkable
class VaultAuthStrategy(Protocol):
    """Authenticate an `hvac.Client` in place.

    Implementations must mutate `client` so that subsequent calls
    (e.g. `client.secrets.kv.v2.read_secret(...)`) succeed. They
    must raise `SecretException` on auth failure; config errors
    (missing role, missing file) raise `SecretConfigurationException`
    so the framework can distinguish "deployment misconfigured" from
    "Vault rejected the call".
    """

    def apply(self, client: hvac.Client) -> None:
        """Log in via this strategy. Idempotent on a re-call: a
        successful prior `apply()` should not raise; a token
        rotation may call `apply()` again to refresh.
        """
        ...


class TokenAuthStrategy:
    """Static-token auth.

    `hvac.Client(...)` was constructed with `token=...` from
    `VaultSecretProperties.to_hvac_client_kwargs()`. `apply()`
    therefore only checks that the running client still carries the
    configured token; if a rotation swaps the property and the
    client was created from it, a re-call updates the client.
    """

    __slots__ = ("_token",)

    def __init__(self, properties: VaultSecretProperties) -> None:
        if not properties.token:
            raise SecretConfigurationException(
                "vault: TokenAuthStrategy requires a non-empty token",
            )
        self._token = properties.token

    def apply(self, client: hvac.Client) -> None:
        if client.token != self._token:
            client.token = self._token
        # hvac 不会因构造期已注入 token 而自动认证成功;再 ping 一次
        # 触发 token lookup,失败抛 `hvac.exceptions.Forbidden` /
        # `hvac.exceptions.InvalidPath` / `requests.exceptions.HTTPError`。
        # 我们捕获后转译为 `SecretException`,framework 层看到的是
        # 干净的 secret-side 异常,而不是 hvac SDK 私有类型。
        if not client.is_authenticated():
            try:
                client.auth.token.lookup_self()
            except Exception as error:  # noqa: BLE001
                raise SecretException(
                    f"vault: token authentication failed: {error}",
                ) from error


class KubernetesAuthStrategy:
    """Kubernetes service-account JWT auth.

    Reads the projected service account JWT from
    `properties.kubernetes_service_account_token_path` (default
    `/var/run/secrets/kubernetes.io/serviceaccount/token`) and
    calls `client.auth.kubernetes.login(...)`. This auth is
    refreshable: `hvac` 1.x+ supports token-renew on the same
    client; a re-call of `apply()` after rotation re-reads the
    file (kubelet rotates the projected token every ~hour).
    """

    __slots__ = ("_mount_point", "_role", "_token_path")

    def __init__(self, properties: VaultSecretProperties) -> None:
        if not properties.kubernetes_role:
            raise SecretConfigurationException(
                "vault: KubernetesAuthStrategy requires "
                "ATLAS_RICHIE_SECRET_VAULT_KUBERNETES_ROLE",
            )
        self._role = properties.kubernetes_role
        self._mount_point = properties.kubernetes_mount_point
        self._token_path = Path(properties.kubernetes_service_account_token_path)

    def apply(self, client: hvac.Client) -> None:
        if not self._token_path.exists():
            raise SecretConfigurationException(
                f"vault: Kubernetes service account JWT not found "
                f"at {self._token_path}",
            )
        try:
            jwt = self._token_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise SecretConfigurationException(
                f"vault: failed to read Kubernetes service account "
                f"JWT at {self._token_path}: {error}",
            ) from error
        if not jwt:
            raise SecretConfigurationException(
                "vault: Kubernetes service account JWT is empty",
            )
        try:
            client.auth.kubernetes.login(
                role=self._role,
                jwt=jwt,
                mount_point=self._mount_point,
            )
        except Exception as error:  # noqa: BLE001
            raise SecretException(
                f"vault: Kubernetes auth login failed "
                f"(role={self._role!r}, mount={self._mount_point!r}): {error}",
            ) from error


class AppRoleAuthStrategy:
    """AppRole auth.

    Calls `client.auth.approle.login(role_id=..., secret_id=...)`
    with the role / secret IDs sourced from properties. AppRole is
    most often used in CI / non-K8s contexts; the secret-id is
    treated as a low-privilege, short-lived credential. A re-call
    re-authenticates with the same IDs.
    """

    __slots__ = ("_mount_point", "_role_id", "_secret_id")

    def __init__(self, properties: VaultSecretProperties) -> None:
        if not properties.approle_role_id or not properties.approle_secret_id:
            raise SecretConfigurationException(
                "vault: AppRoleAuthStrategy requires both role_id and secret_id",
            )
        self._role_id = properties.approle_role_id
        self._secret_id = properties.approle_secret_id
        self._mount_point = properties.approle_mount_point

    def apply(self, client: hvac.Client) -> None:
        try:
            client.auth.approle.login(
                role_id=self._role_id,
                secret_id=self._secret_id,
                mount_point=self._mount_point,
            )
        except Exception as error:  # noqa: BLE001
            raise SecretException(
                f"vault: AppRole auth login failed "
                f"(mount={self._mount_point!r}): {error}",
            ) from error


def auth_strategy_for(properties: VaultSecretProperties) -> VaultAuthStrategy:
    """Factory: select the right `VaultAuthStrategy` by
    `properties.auth_type`. Mirrors the Java switch in
    `VaultClientFactory.authentication(...)`.
    """
    if properties.auth_type is AuthType.TOKEN:
        return TokenAuthStrategy(properties)
    if properties.auth_type is AuthType.KUBERNETES:
        return KubernetesAuthStrategy(properties)
    if properties.auth_type is AuthType.APPROLE:
        return AppRoleAuthStrategy(properties)
    raise SecretConfigurationException(
        f"vault: unsupported auth_type {properties.auth_type!r}",
    )


__all__ = [
    "VaultAuthStrategy",
    "TokenAuthStrategy",
    "KubernetesAuthStrategy",
    "AppRoleAuthStrategy",
    "auth_strategy_for",
]


_ = (logging.getLogger,)
