"""KMIP secret properties — endpoint, TLS material, key bindings。

中文
----
对位 Java `cn.richie696.component.secret.provider.kmip.KmipSecretProperties`
(单行 700+ 字符的 Lombok-style setter)。Python 端用 pydantic-settings
做 env 注入,前缀 `ATLAS_RICHIE_SECRET_KMIP_`。

字段:

- `endpoint: AnyHttpUrl` — `kmips://host:port`(TLS 强制)
- `trust_store: str` — PEM 路径(可选;空 → 走 system trust)
- `trust_store_password: str`(可选)
- `key_store: str` — PEM 路径(可选;用于 client cert)
- `key_store_password: str`(可选)
- `protocol_major: int` — KMIP major version(1-2)
- `protocol_minor: int` — KMIP minor version(0-9)
- `key_bindings: dict[str, str]` — logical → 物理 key id / UniqueID
- `connect_timeout_seconds: float = 10`
- `read_timeout_seconds: float = 30`
- `max_attempts: int = 3`

**关于 auth / key management**:`key_bindings` 是 logical →
physical UniqueID 映射;framework 端 `KeyReference.key_id`
直接承载 physical id(对位 R-238 PKCS#11 / R-240 Aliyun 的
模式)。

English
--------
Pydantic-settings env-injected configuration for the
KMIP backend. Mirrors Java `KmipSecretProperties`
1:1. `endpoint` is required (uses `kmips://` /
`https://` / `http://localhost` for dev); TLS material
is read at factory time; `key_bindings` maps
logical names to KMIP UniqueIDs.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class KmipSecretProperties(BaseSettings):
    """Env-injected configuration for the KMIP backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_KMIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Connection — endpoint is required, scheme must be kmips / https / loopback http.
    endpoint: str = Field(...)

    # TLS material
    trust_store: str | None = Field(default=None)
    trust_store_password: str | None = Field(default=None)
    key_store: str | None = Field(default=None)
    key_store_password: str | None = Field(default=None)

    # Protocol version
    protocol_major: int = Field(default=2, ge=1, le=2)
    protocol_minor: int = Field(default=1, ge=0, le=9)

    # Logical → physical UniqueID
    key_bindings: dict[str, str] = Field(default_factory=dict)

    # Timeouts and retries
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=3, ge=1)

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("endpoint is required and must be non-blank")
        normalized = value.strip()
        # Accept kmips://, https://, http://localhost|127.0.0.1|[::1]
        if not (
            normalized.startswith("kmips://")
            or normalized.startswith("https://")
            or normalized.startswith("http://localhost")
            or normalized.startswith("http://127.0.0.1")
            or normalized.startswith("http://[::1]")
        ):
            raise ValueError(
                f"endpoint must use kmips:// or https:// scheme "
                f"(http:// allowed only for loopback development): {value!r}",
            )
        return normalized

    @field_validator("key_bindings")
    @classmethod
    def _validate_key_bindings(cls, value: dict[str, str]) -> dict[str, str]:
        for logical, physical in value.items():
            if not logical or not logical.strip():
                raise ValueError(
                    f"key_bindings: logical key must be non-blank: {logical!r}",
                )
            if not physical or not physical.strip():
                raise ValueError(
                    f"key_bindings: physical UniqueID must be non-blank "
                    f"for logical {logical!r}",
                )
        return {k: v.strip() for k, v in value.items()}


__all__ = ["KmipSecretProperties"]
