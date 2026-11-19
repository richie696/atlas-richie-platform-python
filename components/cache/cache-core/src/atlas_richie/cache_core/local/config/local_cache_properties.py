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

能力开关（统计 / 按值存储 / read-through / write-through / refresh-ahead）
同样有 `DEFAULT_` 级默认值与每区域覆盖两级，命名规则一致。

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

The capability switches (statistics / store-by-value / read-through /
write-through / refresh-ahead) follow the same two-level scheme: a
`DEFAULT_` fallback plus a per-region override.
"""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..enums.cache_provider import CacheProvider
from ..enums.expiry_policy import ExpiryPolicy


class CacheDefinition(BaseModel):
    """每区域（region）的本地缓存配置覆盖。

    对位 Java ``CacheDefinition`` 的字段映射：

    | Java | Python |
    |---|---|
    | `statisticsEnabled` | `statistics_enabled` |
    | `storeByValue` | `store_by_value` |
    | `readThrough` | `read_through` |
    | `writeThrough` | `write_through` |
    | `cache2kRefreshAhead` | `refresh_ahead` |
    | `cache2kLoaderThreadCount` | `refresh_ahead_threads` |

    **三处与 Java 的刻意差异**：

    1. `store_by_value` 默认 **True**（Java 默认 False）。Python 侧的本地
       缓存自落地起就"每次读写都做防御性拷贝"，把默认值改回 False 等于
       悄悄取消这层保护；这里保留既有行为，并把"按引用存储"作为显式
       关闭开关留给有性能诉求的调用方。
    2. `refresh_ahead` 去掉了 `cache2k` 前缀。Java 的本地缓存由 cache2k
       提供，所以那个开关与 provider 绑定；Python 的本地缓存基于
       cachetools，refresh-ahead 与 provider 无关，用 provider 中立的
       命名才不会误导。
    3. `refresh_ahead_ratio` 是 Python 自定义的策略参数——cache2k 把
       "提前多久刷新"藏在内部，Python 需要显式暴露才能配置与测试。

    Java 的 `cacheLoaderClassName` / `cacheWriterClassName` 在这里没有
    对应字段：Java 靠"类名字符串 + 反射"装配 loader/writer，Python 没有
    这种惯用法，改为向管理器注册可调用对象
    （``LocalCacheManager.register_loader`` / ``register_writer``）。

    Attributes:
        expiry_policy: 过期策略（覆盖全局默认）。
        ttl_millis: 默认过期时间（毫秒）。
        max_size: 最大元素个数。
        statistics_enabled: 是否统计命中 / 未命中等计数。
        store_by_value: 是否按值存储（读写时做防御性拷贝）。
        read_through: 未命中时是否回源加载（需注册 loader）。
        write_through: 变更时是否回写数据源（需注册 writer）。
        refresh_ahead: 条目即将过期时是否后台异步刷新
            （需 read_through + loader）。
        refresh_ahead_ratio: 剩余寿命比例低于该值时触发刷新。
        refresh_ahead_threads: 后台刷新线程数。

    English
    --------
    Per-region cache override.

    **Three deliberate deviations from Java**: `store_by_value` defaults
    to True (Java defaults to False) because the Python local cache has
    always copied on every read and write — flipping the default would
    silently drop that protection; `refresh_ahead` drops the `cache2k`
    prefix because the Python local cache is cachetools-backed and the
    feature is not provider-specific there; and `refresh_ahead_ratio` is
    a Python-defined policy knob that cache2k keeps internal.
    """

    expiry_policy: ExpiryPolicy = ExpiryPolicy.ACCESSED
    ttl_millis: int = 300_000
    max_size: int = 10_000

    #: 是否统计命中 / 未命中等计数（对位 Java `statisticsEnabled`）。
    statistics_enabled: bool = False
    #: 是否按值存储（对位 Java `storeByValue`；Python 默认 True，见类文档）。
    store_by_value: bool = True
    #: 未命中时是否回源加载（对位 Java `readThrough`）。
    read_through: bool = False
    #: 变更时是否回写数据源（对位 Java `writeThrough`）。
    write_through: bool = False
    #: 条目即将过期时是否后台异步刷新（对位 Java `cache2kRefreshAhead`）。
    refresh_ahead: bool = False
    #: 剩余寿命比例低于该值时触发刷新。
    refresh_ahead_ratio: float = Field(0.1, gt=0.0, le=1.0)
    #: 后台刷新线程数（对位 Java `cache2kLoaderThreadCount`）。
    refresh_ahead_threads: int = Field(1, ge=1)


class LocalCacheProperties(BaseSettings):
    """本地缓存配置文件。

    字段：
    - `provider`：缓存提供者（如 `CACHETOOLS`、`EHCACHE`、`CAFFEINE`、`CACHE2K`）
    - `cache_definitions`：多区域（region）自定义配置
    - `default_*`：未显式配置的区域所使用的回退值

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

    #: 默认是否统计命中 / 未命中等计数。
    default_statistics_enabled: bool = False

    #: 默认是否按值存储。
    default_store_by_value: bool = True

    #: 默认未命中时是否回源加载。
    default_read_through: bool = False

    #: 默认变更时是否回写数据源。
    default_write_through: bool = False

    #: 默认是否在条目即将过期时后台异步刷新。
    default_refresh_ahead: bool = False

    #: 默认的刷新触发比例。
    default_refresh_ahead_ratio: float = Field(0.1, gt=0.0, le=1.0)

    #: 默认的后台刷新线程数。
    default_refresh_ahead_threads: int = Field(1, ge=1)

    #: 每区域覆盖配置。
    cache_definitions: Dict[str, CacheDefinition] = Field(default_factory=dict)


__all__ = ["CacheDefinition", "LocalCacheProperties"]
