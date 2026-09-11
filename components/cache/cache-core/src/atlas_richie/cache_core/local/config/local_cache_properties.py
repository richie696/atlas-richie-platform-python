"""本地缓存配置。
----
本地缓存配置文件。提供本地缓存的提供者、过期策略、TTL、最大元素个数，
以及每区域（region）的覆盖配置。

环境变量前缀为 `ATLAS_CACHE_LOCAL_`，嵌套字段分隔符为 `__`（pydantic-
settings 默认行为）：

- ``ATLAS_CACHE_LOCAL_PROVIDER=cachetools``
- ``ATLAS_CACHE_LOCAL_DEFAULT_TTL_MILLIS=600000``
- ``ATLAS_CACHE_LOCAL_DEFAULT_MAX_SIZE=10000``
- ``ATLAS_CACHE_LOCAL_DEFAULT_EXPIRY_POLICY=accessed``
- 每区域覆盖通过
  ``ATLAS_CACHE_LOCAL_CACHE_DEFINITIONS__<region>__TTL_MILLIS=...``
  设置（pydantic-settings 标准嵌套字典机制）。

English
--------
Local-cache configuration (pydantic-settings).

Mirrors `cn.richie696.component.cache.local.config.LocalCacheProperties`
+ `CacheDefinition`. The Java side uses Spring
`@ConfigurationProperties(prefix = "platform.component.cache.local")`
which is awkward in Python; the pydantic-settings equivalent reads
`ATLAS_CACHE_LOCAL_*` environment variables with `__` as the nested
delimiter:

- ``ATLAS_CACHE_LOCAL_PROVIDER=cachetools``
- ``ATLAS_CACHE_LOCAL_DEFAULT_TTL_MILLIS=600000``
- ``ATLAS_CACHE_LOCAL_DEFAULT_MAX_SIZE=10000``
- ``ATLAS_CACHE_LOCAL_DEFAULT_EXPIRY_POLICY=accessed``
- Per-region overrides via
  ``ATLAS_CACHE_LOCAL_CACHE_DEFINITIONS__<region>__TTL_MILLIS=...``
  (standard pydantic-settings nested-dict mechanism).
"""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..enums.cache_provider import CacheProvider
from ..enums.expiry_policy import ExpiryPolicy


class CacheDefinition(BaseModel):
    """每区域（region）的本地缓存配置覆盖。

    Attributes:
        expiry_policy: 过期策略（覆盖全局默认）。
        ttl_millis: 默认过期时间（毫秒）。
        max_size: 最大元素个数。

    English
    --------
    Per-region cache override.
    """

    expiry_policy: ExpiryPolicy = ExpiryPolicy.ACCESSED
    ttl_millis: int = 300_000
    max_size: int = 10_000


class LocalCacheProperties(BaseSettings):
    """本地缓存配置文件。

    字段：
    - `provider`：缓存提供者（如 `CACHETOOLS`、`EHCACHE`、`CAFFEINE`、`CACHE2K`）
    - `cache_definitions`：多区域（region）自定义配置

    English
    --------
    Local cache configuration file.
    """

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_CACHE_LOCAL_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    #: 缓存提供者（默认 `CACHETOOLS`）。
    provider: CacheProvider = CacheProvider.CACHETOOLS

    #: 默认过期策略。
    default_expiry_policy: ExpiryPolicy = ExpiryPolicy.ACCESSED

    #: 默认过期时间（毫秒）。
    default_ttl_millis: int = 300_000

    #: 默认最大元素个数。
    default_max_size: int = 10_000

    #: 每区域覆盖配置。
    cache_definitions: Dict[str, CacheDefinition] = Field(default_factory=dict)


__all__ = ["CacheDefinition", "LocalCacheProperties"]
