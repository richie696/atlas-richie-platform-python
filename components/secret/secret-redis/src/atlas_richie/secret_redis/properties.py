"""Redis secret backend 属性 — pydantic-settings env 注入。

中文
----
对位 Java `cn.richie696.component.secret.provider.redis.RedisSecretProperties`。
Python 端基于 pydantic-settings(R-M6 决定),env 前缀 `ATLAS_RICHIE_SECRET_REDIS_`。

字段:

- `url: str` — Redis server URL(必填)
- `namespace: str = "atlas-richie-secret"` — Redis key 前缀
- `default_ttl_seconds: int = 0` — 写入默认 TTL;0 表示不设过期
- `local_encryption_key_b64: str` — 32 字节 AES-256 key,base64 编码
  (必填)。env 变量 `ATLAS_RICHIE_SECRET_REDIS_LOCAL_ENCRYPTION_KEY`。
  生产应替换为 KMS / HSM 包装的 DEK(后续 `secret-vault` /
  `secret-pkcs11` wheel 实现);当前 wheel 用本地 key 做 envelope
  encryption at-rest,确保 Redis dump 不暴露明文。
- `key_purpose: KeyPurpose = KeyPurpose.ENCRYPT` — AAD 用途字段
- `max_connections: int = 50` / `socket_timeout: float = 5.0` — 透传
  给底层 `RedisCacheProperties`,控制连接池与超时
- `enable_local_lock: bool = True` / `ping_before_activate: bool = True`
  — 透传给 `RedisCacheProperties`,做激活期 sanity check

`to_cache_properties()` 构造内部 `RedisCacheProperties`,不暴露给
调用方 — secret 端只关心 secret 语义,Redis 内部参数封装在
`RedisSecretProperties` 内。

English
--------
Redis secret backend properties. pydantic-settings env injection
following the R-M6 convention. The properties wrap a
`RedisCacheProperties` (built via `to_cache_properties()`) so the
underlying `RedisStringManager` / `RedisDistributedCache` can be
constructed without leaking cache-redis internals.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from atlas_richie.cache_redis import RedisCacheProperties
    from atlas_richie.secret.crypto.key import KeyPurpose


class RedisSecretProperties(BaseSettings):
    """Env-injected configuration for the Redis secret backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_REDIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(...)
    namespace: str = Field(default="atlas-richie-secret")
    default_ttl_seconds: int = Field(default=0, ge=0)
    local_encryption_key_b64: str = Field(...)
    key_purpose: str = Field(default="encrypt")
    max_connections: int = Field(default=50, ge=1)
    socket_timeout: float = Field(default=5.0, gt=0)
    enable_local_lock: bool = Field(default=True)
    ping_before_activate: bool = Field(default=True)

    @field_validator("local_encryption_key_b64")
    @classmethod
    def _validate_local_key(cls, value: str) -> str:
        """Verify the base64 key decodes to 32 bytes (AES-256)."""
        try:
            decoded = base64.b64decode(value, validate=True)
        except Exception as error:
            raise ValueError(
                "local_encryption_key_b64 must be valid base64",
            ) from error
        if len(decoded) != 32:
            raise ValueError(
                f"local_encryption_key must decode to 32 bytes (AES-256); got {len(decoded)}",
            )
        return value

    def decode_local_key(self) -> bytes:
        """Return the raw 32-byte AES-256 key."""
        return base64.b64decode(self.local_encryption_key_b64, validate=True)

    def to_cache_properties(self) -> "RedisCacheProperties":
        """Construct a `RedisCacheProperties` mirroring the fields
        that matter for connection / pool / sanity checks.

        Uses `protocol_version=RESP2` because Redis 7+'s RESP3 `HELLO`
        command requires AUTH to be pre-configured; for development
        Redis on `127.0.0.1:16379` we run without AUTH and need
        RESP2. Other cache-redis fields (perf / server_type) keep
        their defaults; secret-redis does not need them.
        """
        from atlas_richie.cache_redis import ProtocolVersion, RedisCacheProperties

        return RedisCacheProperties(
            url=self.url,
            namespace=self.namespace,
            protocol_version=ProtocolVersion.RESP2,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
            enable_local_lock=self.enable_local_lock,
            ping_before_activate=self.ping_before_activate,
        )

    def key_purpose_enum(self) -> "KeyPurpose":
        """Parse `key_purpose` into the `KeyPurpose` StrEnum."""
        from atlas_richie.secret.crypto.key import KeyPurpose

        return KeyPurpose(self.key_purpose)


__all__ = ["RedisSecretProperties"]


_ = (Mapping,)
