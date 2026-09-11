"""Redis 连接池 + 业务配置（pydantic-settings 注入）。
----
对位 Java 端 `cn.richie696.component.cache.redis.config.base.AtlasRedisProperties`
+ `LettuceExtension` + `AtlasRedisProperties.RedisPerf`。**字段语义 1:1
对齐**（默认值、命名约束、嵌套结构都跟 Java 端保持一致），但**配置
来源**用 Python 生态标准（pydantic-settings 默认从 env var / `.env` /
`pyproject.toml` 加载）而不是 Spring `@ConfigurationProperties` 的 yml。

加载优先级（pydantic-settings v2 默认）：
  1. 显式传入的 kwargs（最高）
  2. 环境变量 `ATLAS_RICHIE_CACHE_REDIS_*`（嵌套字段用 `__` 分隔，如
     `ATLAS_RICHIE_CACHE_REDIS_PERF__ENABLED=true`）
  3. `.env` 文件（同上）
  4. `pyproject.toml` 的 `[tool.atlas_richie.cache_redis]` 段（需显式配
     `pyproject_toml_table` 路径）
  5. dataclass 默认值（最低）

所有字段在 dataclass 上都有显式类型和默认值，业务方从 env 注入即可，
不需要在代码里 new 一个。

English
--------
`pydantic-settings`-backed configuration for the Redis backend.
Mirrors Java's `AtlasRedisProperties` 1:1 in field semantics (default
values, nesting structure, names) but uses Python's pydantic-settings
env-var / `.env` / `pyproject.toml` loading instead of Spring's
yml-based `@ConfigurationProperties`.

`Lettuce`-specific fields (`memoryReleasePolicy`, `memoryReleaseRatio`,
`keepAlive` epoll) are NOT ported — they're Lettuce's internal buffer
management and have no redis-py equivalent. Their behavior is
controlled by `socket_keepalive` + `retry_on_timeout` +
`health_check_interval` in the Python side instead.
"""

from __future__ import annotations

from enum import StrEnum
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisType(StrEnum):
    """Redis 服务端类型。

    对位 Java 端 `cn.richie696.component.cache.redis.enums.RedisTypeEnum`。
    redis-py 8.x 自动处理 cluster / sentinel，所以 Python 端这个字段
    主要是诊断 / 文档用途；URL 里的 `redis://` / `rediss://` / `redis://?cluster=1`
    才是实际生效的。

    English
    --------
    Redis server type. Maps to Java `RedisTypeEnum`. Python's redis-py
    8.x auto-detects cluster / sentinel from the URL, so this field
    is mainly for diagnostics and config documentation.
    """

    STANDALONE = "standalone"
    SENTINEL = "sentinel"
    CLUSTER = "cluster"


class ProtocolVersion(StrEnum):
    """RESP 协议版本。

    对位 Java 端 `io.lettuce.core.protocol.ProtocolVersion`。
    RESP3 在 Redis 6+ 默认开启；Redis 5 或更早的版本需要显式 RESP2。

    English
    --------
    RESP protocol version. Maps to Java `ProtocolVersion`. RESP3 is
    the default for Redis 6+; RESP2 for Redis 5 and earlier.
    """

    RESP2 = "RESP2"
    RESP3 = "RESP3"


class RedisPerfSettings(BaseSettings):
    """Redis 性能守卫配置（嵌套子 dataclass）。

    对位 Java 端 `AtlasRedisProperties.RedisPerf` 内部类 — **23 个
    字段全部 1:1 映射**，包括 `enabled` / `warnNonO1` / `tocSoftMs` /
    `tocHardMs` / `blockForbiddenTiers` / `logBigKeyProbeHints` /
    `tocAllowedComplexities` / `warnStringPayloadAntiPatterns` /
    `jsonLikeMinCharsForWarn` / `warnJsonLikeStringBlob` /
    `stringPayloadMaxChars{Warn,Error}` /
    `stringPayloadMaxBytes{Warn,Error}` /
    `blockStringPayloadViolations` / `maxBatchReadItems` /
    `blockBatchReadViolations` / `warnHashPayloadViolations` /
    `hashFieldPayloadMaxBytes{Warn,Error}` /
    `hashPayloadMaxBytes{Warn,Error}` / `blockHashPayloadViolations`。

    注意：性能守卫在 M5.3+ 才真正接入 manager；目前字段已就位但
    enforcement 代码未实现（属于 dev 剩余）。`enabled=false` 默认值
    与 Java 端一致，避免对存量项目产生日志噪声。

    English
    --------
    Redis performance-guard settings. Mirrors Java's `RedisPerf`
    1:1. NOTE: enforcement is not yet wired into the managers
    (deferred to M5.3+); the fields are defined so the config
    surface is complete. `enabled=False` matches Java's default
    to avoid log noise on existing deployments.
    """

    model_config = SettingsConfigDict(
        # `RedisPerfSettings` sets its OWN `env_prefix` rather than
        # relying on the parent's `env_nested_delimiter` (pydantic-
        # settings v2's `env_nested_delimiter` tries to JSON-decode the
        # suffix and fails for simple `KEY=VALUE` forms). With
        # `env_prefix="ATLAS_RICHIE_CACHE_REDIS_PERF_"`, each
        # performance-guard field maps to its own env var:
        #   ATLAS_RICHIE_CACHE_REDIS_PERF_ENABLED=true
        #   ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_SOFT_MS=20
        env_prefix="ATLAS_RICHIE_CACHE_REDIS_PERF_",
        extra="ignore",
    )

    enabled: bool = False
    warn_non_o1: bool = True
    toc_soft_ms: int = 8
    toc_hard_ms: int = 50
    block_forbidden_tiers: bool = False
    log_big_key_probe_hints: bool = True
    toc_allowed_complexities: List[str] = Field(default_factory=list)
    warn_string_payload_anti_patterns: bool = True
    json_like_min_chars_for_warn: int = 128
    warn_json_like_string_blob: bool = True
    string_payload_max_chars_warn: int = 100_000
    string_payload_max_chars_error: int = 1_000_000
    string_payload_max_bytes_warn: int = 262_144
    string_payload_max_bytes_error: int = 1_048_576
    block_string_payload_violations: bool = False
    max_batch_read_items: int = 1_000
    block_batch_read_violations: bool = True
    warn_hash_payload_violations: bool = True
    hash_field_payload_max_bytes_warn: int = 262_144
    hash_field_payload_max_bytes_error: int = 1_048_576
    hash_payload_max_bytes_warn: int = 1_048_576
    hash_payload_max_bytes_error: int = 4_194_304
    block_hash_payload_violations: bool = True


class RedisCacheProperties(BaseSettings):
    """Redis 缓存完整配置（顶层 dataclass）。

    对位 Java 端 `AtlasRedisProperties` + `LettuceExtension`（已平铺到
    根；Python 端没有 Lettuce 嵌套）。Lettuce 专属字段（`keepAlive`
    epoll / `memoryReleasePolicy` / `memoryReleaseRatio`）**不移植** —
    Python 端 redis-py 8.x 不需要这些。

    **加载方式**：

        # 1. 从环境变量加载（推荐生产环境）
        properties = RedisCacheProperties()
        # env: ATLAS_RICHIE_CACHE_REDIS_URL=redis://...
        #      ATLAS_RICHIE_CACHE_REDIS_MAX_CONNECTIONS=200

        # 2. 从 kwargs 显式构造
        properties = RedisCacheProperties(
            url="redis://localhost:6379/0",
            max_connections=200,
            namespace="myapp",
        )

        # 3. 从 .env 文件加载（开发环境）
        # 写 .env: ATLAS_RICHIE_CACHE_REDIS_URL=redis://...
        properties = RedisCacheProperties(_env_file=".env")

    **env var 命名规范**（env_prefix 默认 `ATLAS_RICHIE_CACHE_REDIS_`）：
        ATLAS_RICHIE_CACHE_REDIS_URL                       # 必填
        ATLAS_RICHIE_CACHE_REDIS_NAMESPACE                 # "atlas-richie"
        ATLAS_RICHIE_CACHE_REDIS_SERVER_TYPE               # standalone/sentinel/cluster
        ATLAS_RICHIE_CACHE_REDIS_PROTOCOL_VERSION          # RESP2/RESP3
        ATLAS_RICHIE_CACHE_REDIS_ENABLE_L2_CACHING         # bool
        ATLAS_RICHIE_CACHE_REDIS_L2_CACHING_DATA           # 逗号分隔的 key type 列表
        ATLAS_RICHIE_CACHE_REDIS_ENABLE_LOCAL_LOCK         # bool
        ATLAS_RICHIE_CACHE_REDIS_PING_BEFORE_ACTIVATE      # bool
        ATLAS_RICHIE_CACHE_REDIS_MAX_CONNECTIONS           # 池大小
        ATLAS_RICHIE_CACHE_REDIS_SOCKET_TIMEOUT            # 秒
        ATLAS_RICHIE_CACHE_REDIS_SOCKET_CONNECT_TIMEOUT    # 秒
        ATLAS_RICHIE_CACHE_REDIS_SOCKET_KEEPALIVE          # bool
        ATLAS_RICHIE_CACHE_REDIS_RETRY_ON_TIMEOUT          # bool
        ATLAS_RICHIE_CACHE_REDIS_HEALTH_CHECK_INTERVAL     # 秒（0=不检查）
        ATLAS_RICHIE_CACHE_REDIS_DECODE_RESPONSES          # bool
        ATLAS_RICHIE_CACHE_REDIS_SHUTDOWN_TIMEOUT          # 秒
        ATLAS_RICHIE_CACHE_REDIS_POOL_MAX_WAIT_SECONDS     # 秒
        ATLAS_RICHIE_CACHE_REDIS_PERF__ENABLED             # 嵌套（用 `__` 分隔）
        ... 等 23 个 perf 字段

    **List 字段 env var 格式**：pydantic-settings v2 解析 list 字段时
    默认走 JSON 解析，所以 env var 写 `JSON 数组` 而不是逗号分隔：

        # ❌ 错误（pydantic-settings 会把 'a,b,c' 整体当一个 string）
        ATLAS_RICHIE_CACHE_REDIS_L2_CACHING_DATA=string,hash

        # ✓ 正确
        ATLAS_RICHIE_CACHE_REDIS_L2_CACHING_DATA='["string", "hash"]'
        ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_ALLOWED_COMPLEXITIES='["O1", "LOG_N"]'

    **kv env var 来源**：业务方生产环境用 `docker run -e` 或 K8s
    `envFrom` 注入；开发环境在项目根写 `.env` 文件（pydantic-settings
    自动读）。

    English
    --------
    Top-level Redis cache configuration. Mirrors Java's
    `AtlasRedisProperties` + flattened `LettuceExtension` fields.
    Lettuce-only fields (epoll keepalive, memory release policy)
    are NOT ported.

    All 23 `RedisPerf` sub-fields are also exposed, accessed via the
    `perf: RedisPerfSettings` attribute or `ATLAS_RICHIE_CACHE_REDIS_PERF_*`
    env vars (note: each perf field has its own env var, NOT
    `__` separator — see `RedisPerfSettings` docstring for why).

    **List fields in env vars**: pydantic-settings v2 parses list
    fields as JSON, so use JSON array syntax, not comma-separated:

        # ✓ correct
        ATLAS_RICHIE_CACHE_REDIS_L2_CACHING_DATA='["string", "hash"]'
        ATLAS_RICHIE_CACHE_REDIS_PERF_TOC_ALLOWED_COMPLEXITIES='["O1", "LOG_N"]'
    """

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_CACHE_REDIS_",
        # No `env_nested_delimiter` here — nested `RedisPerfSettings`
        # sets its own `env_prefix` instead (see its docstring).
        extra="ignore",
        case_sensitive=False,
    )

    # ── 必填 ──────────────────────────────────────────────────────

    url: str = Field(
        ...,
        description="Redis 连接 URL，格式 `redis://[user:password@]host:port/db` "
        "或 `rediss://...`（TLS）或 `unix://...`。",
    )

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("url must be a non-empty string")
        if not (
            v.startswith("redis://")
            or v.startswith("rediss://")
            or v.startswith("unix://")
        ):
            raise ValueError(
                f"url must start with redis://, rediss://, or unix://; got {v[:20]!r}"
            )
        return v

    # ── 业务配置（对位 Java 顶层字段）───────────────────────────────

    namespace: str = Field(
        default="atlas-richie",
        description="key 前缀；所有 Redis key 自动加 `{namespace}:` 前缀。",
    )
    server_type: RedisType = Field(
        default=RedisType.STANDALONE,
        description="Redis 服务类型（standalone / sentinel / cluster）。"
        "redis-py 8.x 自动从 URL 检测，此字段主要用于诊断。",
    )
    protocol_version: ProtocolVersion = Field(
        default=ProtocolVersion.RESP3,
        description="RESP 协议版本。RESP3 用于 Redis 6+；RESP2 用于 Redis 5 或更早。",
    )
    enable_l2_caching: bool = Field(
        default=False,
        description="是否启用 Redis 二级缓存（L1 process-local + L2 Redis）。"
        "对位 Java 端 `enableL2Caching`。",
    )
    l2_caching_data: List[str] = Field(
        default_factory=list,
        description="L2 缓存的数据类型（key type 列表），如 `['string', 'hash']`。"
        "对位 Java 端 `l2CachingData: List<KeyTypeEnum>`。",
    )
    enable_local_lock: bool = Field(
        default=True,
        description="是否启用本地 JVM 锁（先在本地竞争，本地未持有才请求 Redis 锁）。"
        "对位 Java 端 `enableLocalLock`。",
    )
    ping_before_activate: bool = Field(
        default=True,
        description="是否在连接激活之前执行 PING 命令。"
        "对位 Java 端 `pingBeforeActivateConnection`。",
    )

    # ── redis-py 池 / 连接参数（平铺 Java 端 `Lettuce` 父类）────────

    max_connections: int = Field(
        default=50,
        description="连接池最大连接数。对位 Java 端 `lettuce.pool.max-active`。",
    )
    socket_timeout: float = Field(
        default=5.0,
        description="读写 socket 超时（秒）。对位 Java 端 `lettuce.timeout`。",
    )
    socket_connect_timeout: float = Field(
        default=5.0,
        description="连接 socket 超时（秒）。redis-py 专属参数，Java Lettuce 走同一 timeout。",
    )
    socket_keepalive: bool = Field(
        default=True,
        description="是否启用 TCP keepalive。redis-py 专属参数。",
    )
    retry_on_timeout: bool = Field(
        default=False,
        description="是否在 socket 超时时自动重试。redis-py 专属参数。",
    )
    health_check_interval: int = Field(
        default=0,
        description="连接健康检查间隔（秒，0=不检查）。redis-py 专属参数。",
    )
    decode_responses: bool = Field(
        default=True,
        description="是否把 Redis bytes 自动 decode 成 str。",
    )
    shutdown_timeout: Optional[float] = Field(
        default=None,
        description="连接池关闭超时（秒，None=不超时）。对位 Java 端 `shutdown-timeout`。",
    )
    pool_max_wait_seconds: Optional[float] = Field(
        default=None,
        description="从池获取连接的最大等待时间（秒，None=阻塞）。"
        "对位 Java 端 `lettuce.pool.max-wait`。",
    )

    # ── 嵌套性能守卫（对位 Java 端 `RedisPerf` 内部类）───────────────

    perf: RedisPerfSettings = Field(
        default_factory=RedisPerfSettings,
        description="Redis 性能守卫（嵌套 23 字段）。对位 Java 端 `RedisPerf`。",
    )
