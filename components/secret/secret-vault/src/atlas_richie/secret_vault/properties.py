"""Vault secret backend 属性 — pydantic-settings env 注入。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultSecretProperties`。
Python 端基于 pydantic-settings(R-M6 决定),env 前缀
`ATLAS_RICHIE_SECRET_VAULT_`。

字段分类:

- **连接**:`url` / `namespace` / `timeout_seconds`
- **认证**:`auth_type` 枚举 + 三类子字段(Token / Kubernetes / AppRole)
- **存储 mount**:`kv_mount`(KV v2,默认 `secret`)/ `transit_mount`(Transit,默认 `transit`)
- **重试**:`max_retries` / `retry_backoff_seconds`
- **TLS**:`verify_tls`(开发用 False,生产用 True)

`to_hvac_client_kwargs()` 构造 `hvac.Client(...)` 入参 dict;实际
`hvac.Client` 构造在 `VaultClientFactory` 里,这里只描述数据。

`AuthType` 枚举 3 个值,互斥。子字段用 `field_validator` 校验
"选了 auth_type=X 则对应子字段必填"。

English
--------
Vault secret backend properties. Pydantic-settings env injection
following the R-M6 convention. Fields cover connection, authentication
(Token / Kubernetes / AppRole), KV v2 / Transit mount points, retry
policy, and TLS. `to_hvac_client_kwargs()` returns the kwargs dict
that `hvac.Client(**kwargs)` accepts; actual client construction
lives in `VaultClientFactory`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


class AuthType(StrEnum):
    """Vault authentication strategy."""

    TOKEN = "token"
    KUBERNETES = "kubernetes"
    APPROLE = "approle"


class VaultSecretProperties(BaseSettings):
    """Env-injected configuration for the Vault secret backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_VAULT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(...)
    namespace: str = Field(default="atlas-richie-secret")
    timeout_seconds: float = Field(default=30.0, gt=0)

    # Authentication
    auth_type: AuthType = Field(default=AuthType.TOKEN)
    token: str | None = Field(default=None)
    kubernetes_role: str | None = Field(default=None)
    kubernetes_mount_point: str = Field(default="kubernetes")
    kubernetes_service_account_token_path: str = Field(
        default="/var/run/secrets/kubernetes.io/serviceaccount/token",
    )
    approle_role_id: str | None = Field(default=None)
    approle_secret_id: str | None = Field(default=None)
    approle_mount_point: str = Field(default="approle")

    # Mount points
    kv_mount: str = Field(default="secret")
    transit_mount: str = Field(default="transit")

    # Transit key bindings: logical name → physical Transit key name.
    # Mirrors Java `VaultSecretProperties.Transit.keyBindings`. When
    # a `KeyReference.key_id` is present in this map, the client
    # uses the mapped physical key; otherwise the key_id is used
    # as-is (backward-compatible with deployments that pass the
    # physical name directly).
    transit_key_bindings: dict[str, str] = Field(default_factory=dict)

    # Retry
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=0.5, gt=0)

    # TLS
    verify_tls: bool = Field(default=True)
    ca_cert_path: str | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError(
                f"url must start with http:// or https://; got {value!r}",
            )
        return value

    @model_validator(mode="after")
    def _validate_auth_fields(self) -> "VaultSecretProperties":
        if self.auth_type is AuthType.TOKEN:
            if not self.token:
                raise ValueError(
                    "auth_type=token requires ATLAS_RICHIE_SECRET_VAULT_TOKEN",
                )
        elif self.auth_type is AuthType.KUBERNETES:
            if not self.kubernetes_role:
                raise ValueError(
                    "auth_type=kubernetes requires "
                    "ATLAS_RICHIE_SECRET_VAULT_KUBERNETES_ROLE",
                )
        elif self.auth_type is AuthType.APPROLE:
            if not (self.approle_role_id and self.approle_secret_id):
                raise ValueError(
                    "auth_type=approle requires "
                    "ATLAS_RICHIE_SECRET_VAULT_APPROLE_ROLE_ID "
                    "and _SECRET_ID",
                )
        return self

    def to_hvac_client_kwargs(self) -> Mapping[str, object]:
        """Build the kwargs dict for `hvac.Client(**kwargs)`.

        The caller passes this to `hvac.Client(...)`; the actual
        auth strategy is applied lazily (e.g. `client.auth.kubernetes.login(...)`)
        inside `VaultClientFactory`.
        """
        kwargs: dict[str, object] = {
            "url": self.url,
            "timeout": self.timeout_seconds,
            "verify": (
                self.ca_cert_path if self.ca_cert_path else self.verify_tls
            ),
        }
        if self.auth_type is AuthType.TOKEN and self.token is not None:
            kwargs["token"] = self.token
        return kwargs


__all__ = [
    "AuthType",
    "VaultSecretProperties",
]


_ = (Mapping,)
