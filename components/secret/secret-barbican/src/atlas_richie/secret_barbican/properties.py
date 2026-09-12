"""Barbican secret properties — pydantic-settings env injection。

中文
----
对位 Java `cn.richie696.component.secret.provider.barbican.BarbicanSecretProperties`
(单行 1100+ 字符的 Lombok-style 字段,翻译为 Python dataclass +
pydantic-settings model)。

字段:

- `endpoint: AnyHttpUrl` — Barbican service base URL,例如
  `https://keystone.example:5000/v1`(框架拼上 `/v1/secrets/...`)
- `project_id: str` — OpenStack project id(写入 `X-Project-Id`
  header)
- `secrets: dict[str, BarbicanSecretMapping]` — logical →
  physical secret id(对位 Java `SecretMapping`)
- `connect_timeout_seconds: float = 10`
- `read_timeout_seconds: float = 30`
- `max_attempts: int = 3`

**认证**(`Authentication`):
- `AuthType.TOKEN` + `token: str` — 直接提供 token
- `AuthType.TOKEN_FILE` + `token_file: str` — 从文件读 token
  (对位 Java `loadToken`)

**注意**:与 Java 不同,Python 端用 `httpx.Client` 而非 JDK
`HttpClient`,所以 TLS 校验 / proxy 配置走 `httpx` 自己的
trust store / proxy 参数(对位 Java `RemoteHttpClientFactory`)。

English
--------
Pydantic-settings env-injected configuration for the
Barbican backend. Mirrors Java `BarbicanSecretProperties`
1:1. `endpoint` is the Barbican service URL; auth
supports `Token` (inline) or `TokenFile` (read from
disk). The client uses `httpx.Client` for HTTP (vs Java's
JDK `HttpClient`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger("atlas_richie.secret_barbican.properties")


class AuthType(str, Enum):
    """Barbican authentication mechanism (mirrors Java
    `BarbicanSecretProperties.AuthenticationType`).
    """

    TOKEN = "token"
    TOKEN_FILE = "token_file"


@dataclass(frozen=True, slots=True)
class BarbicanSecretMapping:
    """Logical → physical Barbican secret id mapping.

    Attributes:
        id: Physical Barbican secret UUID.
    """

    id: str


@dataclass(frozen=True, slots=True)
class BarbicanAuth:
    """Barbican authentication (mirrors Java
    `BarbicanSecretProperties.Authentication`).

    Attributes:
        type: `TOKEN` (inline) or `TOKEN_FILE` (read from disk).
        token: Inline token (when `type=TOKEN`).
        token_file: Path to token file (when `type=TOKEN_FILE`).
    """

    type: AuthType
    token: str = ""
    token_file: str = ""


class BarbicanSecretProperties(BaseSettings):
    """Env-injected configuration for the Barbican backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_BARBICAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    endpoint: str = Field(...)
    project_id: str | None = Field(default=None)
    secrets: dict[str, BarbicanSecretMapping] = Field(default_factory=dict)

    # Authentication — flat fields; we synthesize `BarbicanAuth` for the client.
    auth_type: AuthType = Field(default=AuthType.TOKEN)
    auth_token: str = Field(default="")
    auth_token_file: str | None = Field(default=None)

    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=3, ge=1)

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("endpoint is required and must be non-blank")
        normalized = value.strip()
        if not (
            normalized.startswith("https://")
            or normalized.startswith("http://localhost")
            or normalized.startswith("http://127.0.0.1")
            or normalized.startswith("http://[::1]")
        ):
            raise ValueError(
                f"endpoint must use https:// (or loopback http:// for dev): {value!r}",
            )
        return normalized.rstrip("/")

    @field_validator("secrets")
    @classmethod
    def _validate_secrets(cls, value: dict[str, BarbicanSecretMapping]) -> dict[str, BarbicanSecretMapping]:
        for logical, mapping in value.items():
            if not logical or not logical.strip():
                raise ValueError(
                    f"secrets: logical name must be non-blank: {logical!r}",
                )
            if mapping is None or not mapping.id or not mapping.id.strip():
                raise ValueError(
                    f"secrets[{logical!r}]: id must be non-blank",
                )
        return value

    def auth(self) -> BarbicanAuth:
        """Construct the `BarbicanAuth` aggregate (mirrors Java's
        `BarbicanSecretProperties.getAuthentication()`).
        """
        return BarbicanAuth(
            type=self.auth_type,
            token=self.auth_token,
            token_file=self.auth_token_file or "",
        )


__all__ = [
    "AuthType",
    "BarbicanAuth",
    "BarbicanSecretMapping",
    "BarbicanSecretProperties",
]
