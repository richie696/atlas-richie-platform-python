"""Redis 后端 `ProviderRegistrar` 的具体实现。
----
状态：**M1-M4 + R-221 + R-222 + R-223 + R-224 已完成** — 30 个
`ProviderRegistrar` 抽象方法全部真实实现，外加 R-221 的
`NotificationOps.subscribe()`、R-222 的 Bloom Filter 工厂
`bloom_shared()` / `bloom_in_memory()`、R-223 的 `l1()` 工厂、
R-224 的 `snowflake()` 工厂。

15 ops + 11 functions 实际由 16 个 manager 类实现：每个 manager 同时
实现一个 ops Protocol 和对应的 function Protocol（与 Java 端 17 个
manager 的布局对齐，但因 Python-only `StructOps` 和 lock 端 ops/function
拆分略有差异）。

构造期会一次性 eager 实例化所有 manager，因此 `install()` 之后
所有能力立即可用。`close()` 负责关闭 event manager 和底层 backend。

English
--------
`ProviderRegistrar` implementation for the Redis backend.

Status: **M1-M4 + R-221 + R-222 complete** — all 30 abstract methods
real, plus `NotificationOps.subscribe()` (R-221) and Bloom filter
factories `bloom_shared()` / `bloom_in_memory()` (R-222).

15 ops + 11 functions are implemented by 16 manager classes
(each manager implements one ops Protocol and the corresponding
function Protocol, mirroring Java's 17-manager layout modulo
Python-only `StructOps` and a slightly different ops-vs-function
split on the locking side).
"""

from __future__ import annotations

from typing import Any

from atlas_richie.cache_core.config.bloom_filter_config import (
    BloomFilterConfig,
)
from atlas_richie.cache_core.enums.cache_provider import CacheProvider
from atlas_richie.cache_core.ops.cache_infrastructure import (
    CacheInfrastructure,
)
from atlas_richie.cache_core.registry.provider_registrar import (
    ProviderRegistrar,
)

from .managers.in_memory_bloom_filter import InMemoryBloomFilter
from .managers.redis_bitmap_manager import RedisBitmapManager
from .managers.redis_bloom_filter import RedisSharedBloomFilter
from .managers.redis_bounded_queue_manager import RedisBoundedQueueManager
from .managers.redis_bounded_stack_manager import RedisBoundedStackManager
from .managers.redis_collection_manager import RedisCollectionManager
from .managers.redis_event_manager import RedisEventManager
from .managers.redis_field_manager import RedisFieldManager
from .managers.redis_geo_manager import RedisGeoManager
from .managers.redis_hyper_log_manager import RedisHyperLogManager
from .managers.redis_key_manager import RedisKeyManager
from .managers.redis_limiter_manager import RedisLimiterManager
from .managers.redis_lock_manager import RedisLockManager
from .managers.redis_notification_manager import RedisNotificationManager
from .managers.redis_ranking_manager import RedisRankingManager
from .managers.redis_script_manager import RedisScriptManager
from .managers.redis_string_manager import RedisStringManager
from .managers.redis_struct_manager import RedisStructManager
from ._perf_guard import RedisPerfGuard
from .redis_cache_infrastructure import RedisCacheInfrastructure
from .redis_distributed_cache import RedisDistributedCache


class RedisProviderRegistrar(ProviderRegistrar):
    """Redis backend implementation of `ProviderRegistrar`."""

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "atlas-richie",
        connection_string: str | None = None,
        connection_pool: Any | None = None,
        perf: RedisPerfGuard | None = None,
    ) -> None:
        self._backend = RedisDistributedCache(
            client,
            namespace=namespace,
            connection_string=connection_string,
            connection_pool=connection_pool,
        )
        self._infra = RedisCacheInfrastructure(self._backend)
        # Eagerly construct the real managers (M1-M4).
        # R-M5.4: thread the optional `perf` guard into every manager
        # that has a `_perf` slot. The 5 small managers that don't
        # currently enforce perf (script / limiter / notification /
        # event / ranking / bitmap / hyper_log / geo / lock /
        # bounded_queue / bounded_stack) get `None` — adding the
        # `perf` arg to their constructors is deferred to a later
        # milestone (only the 5 most-frequent public surfaces are
        # instrumented right now).
        self._string_manager = RedisStringManager(self._backend, self._infra, perf)
        self._field_manager = RedisFieldManager(self._backend, self._infra, perf)
        self._collection_manager = RedisCollectionManager(
            self._backend, self._infra, perf
        )
        self._key_manager = RedisKeyManager(self._backend, self._infra, perf)
        self._script_manager = RedisScriptManager(self._backend, self._infra)
        self._limiter_manager = RedisLimiterManager(self._backend, self._infra)
        self._notification_manager = RedisNotificationManager(
            self._backend, self._infra
        )
        self._event_manager = RedisEventManager(self._backend, self._infra)
        self._ranking_manager = RedisRankingManager(self._backend, self._infra)
        self._bitmap_manager = RedisBitmapManager(self._backend, self._infra)
        self._hyper_log_manager = RedisHyperLogManager(
            self._backend, self._infra
        )
        self._geo_manager = RedisGeoManager(self._backend, self._infra)
        self._struct_manager = RedisStructManager(self._backend, self._infra, perf)
        self._bounded_queue_manager = RedisBoundedQueueManager(
            self._backend, self._infra
        )
        self._bounded_stack_manager = RedisBoundedStackManager(
            self._backend, self._infra
        )
        self._lock_manager = RedisLockManager(self._backend, self._infra)
        # `cache_function` returns the base `CacheFunction` Protocol.
        self._cache_function = self._string_manager
        # Expose the guard for tests / observability. `None` when
        # no guard is wired (the common case for ad-hoc `from_url`
        # callers; only `from_properties()` builds a guard).
        self._perf = perf

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        namespace: str = "atlas-richie",
        decode_responses: bool = True,
        **redis_kwargs: Any,
    ) -> "RedisProviderRegistrar":
        import redis as redis_lib

        client = redis_lib.Redis.from_url(
            redis_url, decode_responses=decode_responses, **redis_kwargs
        )
        masked = _mask_redis_url(redis_url)
        return cls(
            client, namespace=namespace, connection_string=masked
        )

    @classmethod
    def from_properties(
        cls,
        properties: "RedisCacheProperties",
    ) -> "RedisProviderRegistrar":
        """从 `RedisCacheProperties` (pydantic-settings) 构造 registrar。

        把 properties 里的 18 个池/连接/业务字段映射到 redis-py 8.x
        客户端 + 显式构造 `ConnectionPool`（业务方调 `max_connections`、
        `socket_timeout`、`retry_on_timeout` 等都从这里生效）。

        **与 Java 端对齐**：`AtlasRedisProperties` 的字段 1:1 映射
        到 `RedisCacheProperties`，但结构是 pydantic-settings 而不是
        yml。对应 Java 端 `@ConfigurationProperties(prefix = "platform.component.cache.redis")` +
        `LettuceExtension` + `RedisPerf` 三个层级合并成一个 dataclass。

        English
        --------
        Construct a `RedisProviderRegistrar` from a pydantic-settings
        `RedisCacheProperties`. Maps 18 pool/connection/business
        fields to redis-py 8.x client + explicit `ConnectionPool`,
        so business code can tune `max_connections`,
        `socket_timeout`, `retry_on_timeout`, etc. via env vars /
        .env / pyproject.toml.

        Mirrors Java's `AtlasRedisProperties` 1:1 in semantics, with
        the three-level Spring config (AtlasRedisProperties +
        LettuceExtension + RedisPerf) collapsed into one pydantic
        dataclass.
        """
        # Local import to avoid circular import at module load.
        from .redis_cache_properties import RedisCacheProperties
        from redis.connection import BlockingConnectionPool

        if not isinstance(properties, RedisCacheProperties):
            raise TypeError(
                f"properties must be a RedisCacheProperties instance, "
                f"got {type(properties).__name__}"
            )

        # Build a `BlockingConnectionPool` explicitly so that
        # `max_connections`, `socket_keepalive`, `pool_max_wait_seconds`
        # etc. from properties actually take effect.
        #
        # We choose `BlockingConnectionPool` over the default
        # `ConnectionPool` because `pool_max_wait_seconds` is a
        # blocking-pool concept (how long to block waiting for a free
        # connection); the default `ConnectionPool` rejects
        # immediately when the pool is full, which is rarely what
        # business code wants.
        pool_kwargs: dict[str, Any] = {
            "max_connections": properties.max_connections,
            "socket_timeout": properties.socket_timeout,
            "socket_connect_timeout": properties.socket_connect_timeout,
            "socket_keepalive": properties.socket_keepalive,
            "retry_on_timeout": properties.retry_on_timeout,
            "decode_responses": properties.decode_responses,
        }
        if properties.health_check_interval > 0:
            pool_kwargs["health_check_interval"] = properties.health_check_interval
        # `BlockingConnectionPool.timeout` is the max time to wait for a
        # free connection. None means use redis-py default (20s).
        # redis-py stores this on `pool.timeout` as a public attribute.
        pool_timeout = (
            properties.pool_max_wait_seconds
            if properties.pool_max_wait_seconds is not None
            else 20  # BlockingConnectionPool default
        )

        # `redis.connection.BlockingConnectionPool.from_url` builds a
        # pool with the given settings; the resulting `Redis` client
        # shares the pool.
        import redis as redis_lib

        pool = BlockingConnectionPool.from_url(
            properties.url, timeout=pool_timeout, **pool_kwargs
        )
        client = redis_lib.Redis(connection_pool=pool)

        masked = _mask_redis_url(properties.url)
        # R-M5.4: build the perf guard from `properties.perf` so all
        # 23 fields in `RedisPerfSettings` flow into the manager
        # `__init__`s. The guard is a no-op when `perf.enabled` is
        # False (the default), so callers who don't tune the 23
        # fields pay zero overhead.
        from ._perf_guard import RedisPerfGuard as _RedisPerfGuard

        perf_guard = _RedisPerfGuard(properties.perf)
        return cls(
            client,
            namespace=properties.namespace,
            connection_string=masked,
            connection_pool=pool,
            perf=perf_guard,
        )

    # ── 16 low-level ops ───────────────────────────────────────────

    @property
    def namespace(self) -> str:
        """The key namespace passed at construction (delegated to backend)."""
        return self._backend.namespace

    @property
    def connection_pool(self) -> Any | None:
        """The underlying `redis.ConnectionPool` (or `None` if `from_url`).

        Exposed for observability and for tests that need to assert
        pool settings (`max_connections`, `timeout`, etc.).
        """
        return self._backend._connection_pool

    @property
    def perf(self) -> RedisPerfGuard | None:
        """The `RedisPerfGuard` instance wired into all managers (R-M5.4).

        `None` when the registrar was constructed via `__init__` or
        `from_url` without an explicit `perf` arg. Always non-`None`
        when the registrar was built via `from_properties` (the
        default `RedisPerfSettings(enabled=False)` is wired through
        but is a no-op until the caller flips `enabled=True`).
        """
        return self._perf

    def value_ops(self):
        return self._string_manager

    def struct_ops(self):
        return self._struct_manager

    def field_ops(self):
        return self._field_manager

    def collection_ops(self):
        return self._collection_manager

    def ranking_ops(self):
        return self._ranking_manager

    def key_ops(self):
        return self._key_manager

    def bitmap_ops(self):
        return self._bitmap_manager

    def hyper_log_ops(self):
        return self._hyper_log_manager

    def geo_ops(self):
        return self._geo_manager

    def script_ops(self):
        return self._script_manager

    def limiter_ops(self):
        return self._limiter_manager

    def bounded_queue_ops(self):
        return self._bounded_queue_manager

    def bounded_stack_ops(self):
        return self._bounded_stack_manager

    def lock_ops(self):
        return self._lock_manager

    def notification_ops(self):
        return self._notification_manager

    def event_ops(self):
        return self._event_manager

    # ── 1 framework-internal interface ─────────────────────────────

    def cache_infrastructure(self) -> CacheInfrastructure:
        return self._infra

    # ── 11 high-level functions ────────────────────────────────────

    def string_function(self):
        return self._string_manager

    def hash_function(self):
        return self._field_manager

    def set_function(self):
        return self._collection_manager

    def z_set_function(self):
        return self._ranking_manager

    def geo_function(self):
        return self._geo_manager

    def hyper_log_function(self):
        return self._hyper_log_manager

    def bitmap_function(self):
        return self._bitmap_manager

    def lock_function(self):
        return self._lock_manager

    def notification_function(self):
        return self._notification_manager

    def event_function(self):
        return self._event_manager

    def cache_function(self):
        return self._cache_function

    # ── 2 meta accessors ───────────────────────────────────────────

    def provider(self) -> CacheProvider:
        return CacheProvider.REDIS

    def connection_string(self) -> str:
        return self._backend.connection_string

    # ── R-222: Bloom filter factories ────────────────────────────

    def bloom_shared(
        self, config: BloomFilterConfig | None = None
    ) -> RedisSharedBloomFilter:
        """Build a Redis-backed shared `BloomFilter` (Lua atomic).

        The `config` controls expected_insertions / false_probability /
        key. If a filter with the same key already exists in Redis,
        the existing dimensions are reused (so the bits survive
        process restarts and the same filter can be opened from
        multiple processes).
        """
        return RedisSharedBloomFilter(
            self._backend, config or BloomFilterConfig()
        )

    def bloom_in_memory(
        self,
        expected_insertions: int = 1_000_000,
        false_probability: float = 0.001,
    ) -> InMemoryBloomFilter:
        """Build a process-local `BloomFilter` (no I/O).

        Suitable for single-process use cases; cheap to construct and
        free of network round-trips.
        """
        return InMemoryBloomFilter(
            expected_insertions=expected_insertions,
            false_probability=false_probability,
        )

    # ── R-223: L2 DistributedCache (L1 + L2 fan-out) ─────────────

    def l1(
        self,
        max_size: int = 10_000,
        ttl_seconds: int = 300,
    ) -> "L2DistributedCache":
        """Return a cached `L2DistributedCache` for the given config.

        Same config → same instance (so `stats()` accumulates across
        calls). Different config → different instance.
        """
        from .local.l2_cache_factory import L2CacheFactory
        if not hasattr(self, "_l2_factory"):
            self._l2_factory = L2CacheFactory(
                default_region=self._backend.namespace
            )
        return self._l2_factory.get_or_create(
            value_ops=self._string_manager,
            max_size=max_size,
            ttl_seconds=ttl_seconds,
        )

    # ── R-224: SnowflakeIdBuilder ───────────────────────────────

    def snowflake(
        self, registry_key: str = "snowflake:workId"
    ) -> "RedisSnowflakeIdBuilder":
        """Build a `SnowflakeIdBuilder` that allocates its `workerId`
        atomically from a Redis-backed round-robin registry.

        Each registrar's `snowflake()` call returns a **fresh**
        builder with a fresh workerId (so two `snowflake()` calls in
        the same process get different workerIds). The same builder
        shares its `workerId` across all `next_id()` calls.
        """
        from .managers.redis_snowflake_id_builder import (
            RedisSnowflakeIdBuilder,
        )
        return RedisSnowflakeIdBuilder(self._backend, key=registry_key)

    # ── Lifecycle ──────────────────────────────────────────────────

    def close(self) -> None:
        self._event_manager.close()
        self._backend.close()


def _mask_redis_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1) if "://" in url else ("", url)
    if "@" not in rest:
        return url
    creds, host = rest.split("@", 1)
    if ":" not in creds:
        return url
    user, _ = creds.split(":", 1)
    return f"{scheme}://{user}:***@{host}"


__all__ = ["RedisProviderRegistrar"]
