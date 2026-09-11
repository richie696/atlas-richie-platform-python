"""`ProviderRegistrar` implementation for the Redis backend.

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
    ) -> None:
        self._backend = RedisDistributedCache(
            client, namespace=namespace, connection_string=connection_string
        )
        self._infra = RedisCacheInfrastructure(self._backend)
        # Eagerly construct the real managers (M1-M4).
        self._string_manager = RedisStringManager(self._backend, self._infra)
        self._field_manager = RedisFieldManager(self._backend, self._infra)
        self._collection_manager = RedisCollectionManager(
            self._backend, self._infra
        )
        self._key_manager = RedisKeyManager(self._backend, self._infra)
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
        self._struct_manager = RedisStructManager(self._backend, self._infra)
        self._bounded_queue_manager = RedisBoundedQueueManager(
            self._backend, self._infra
        )
        self._bounded_stack_manager = RedisBoundedStackManager(
            self._backend, self._infra
        )
        self._lock_manager = RedisLockManager(self._backend, self._infra)
        # `cache_function` returns the base `CacheFunction` Protocol.
        self._cache_function = self._string_manager

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

    # ── 16 low-level ops ───────────────────────────────────────────

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
