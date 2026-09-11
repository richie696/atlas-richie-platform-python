"""`atlas-richie-cache-core` 的 Redis 后端实现。
----
提供 16 ops + 11 functions 的具体实现（封装 `redis-py`），以及
ProviderRegistrar、L2 缓存、Pub/Sub、Bloom Filter、Snowflake ID 等
扩展能力。

公开 API：

    RedisProviderRegistrar      # 具体 ProviderRegistrar
    RedisProviderRegistrar.from_url(...)
    RedisDistributedCache       # 传输层包装
    RedisCacheInfrastructure    # CacheInfrastructure 实现
    RedisStringManager          # M1: ValueOps + StringFunction
    RedisFieldManager           # M2: FieldOps + HashFunction
    RedisCollectionManager      # M2: CollectionOps + SetFunction
    RedisKeyManager             # M3.A: KeyOps
    RedisScriptManager          # M3.A: ScriptOps
    RedisLimiterManager         # M3.A: LimiterOps
    RedisNotificationManager    # M3.A + R-221: NotificationOps + NotificationFunction
    RedisNotificationListener   # R-221: subscribe() 句柄
    RedisSharedBloomFilter      # R-222: Redis BITSET + Lua 原子
    InMemoryBloomFilter         # R-222: 进程内 bytearray
    L2DistributedCache          # R-223: L1 (cachetools) + L2 (Redis) cache-aside
    L2CacheFactory              # R-223: per-config L2 cache 实例缓存
    RedisSnowflakeIdBuilder     # R-224: 64-bit Snowflake ID，workerId Redis 持久化
    RedisEventManager           # M3.A: EventOps + EventFunction
    RedisRankingManager         # M3.B: RankingOps + ZSetFunction
    RedisBitmapManager          # M3.B: BitmapOps + BitmapFunction
    RedisHyperLogManager        # M3.B: HyperLogOps + HyperLogFunction
    RedisGeoManager             # M3.B: GeoOps + GeoFunction
    RedisStructManager          # M3.C: StructOps
    RedisBoundedQueueManager    # M3.C: BoundedQueueOps
    RedisBoundedStackManager    # M3.C: BoundedStackOps
    RedisLockManager            # M4: LockOps + LockFunction
    RedisDistributedLock        # M4: try_acquire() 返回的句柄
    RedisDistributedBatchLock   # M4: batch() 返回的句柄

English
--------
Redis backend for `atlas-richie-cache-core`.

Public API:

    RedisProviderRegistrar      # the concrete ProviderRegistrar
    RedisProviderRegistrar.from_url(...)
    RedisDistributedCache       # transport wrapper
    RedisCacheInfrastructure    # CacheInfrastructure impl
    RedisStringManager          # M1: ValueOps + StringFunction
    RedisFieldManager           # M2: FieldOps + HashFunction
    RedisCollectionManager      # M2: CollectionOps + SetFunction
    RedisKeyManager             # M3.A: KeyOps
    RedisScriptManager          # M3.A: ScriptOps
    RedisLimiterManager         # M3.A: LimiterOps
    RedisNotificationManager    # M3.A + R-221: NotificationOps + NotificationFunction
    RedisNotificationListener   # R-221: subscribe() handle
    RedisSharedBloomFilter      # R-222: Redis BITSET + Lua atomic
    InMemoryBloomFilter         # R-222: in-process bytearray
    L2DistributedCache          # R-223: L1 (cachetools) + L2 (Redis) cache-aside
    L2CacheFactory              # R-223: per-config L2 cache instance cache
    RedisSnowflakeIdBuilder     # R-224: 64-bit Snowflake ID with Redis-persisted workerId
    RedisEventManager           # M3.A: EventOps + EventFunction
    RedisRankingManager         # M3.B: RankingOps + ZSetFunction
    RedisBitmapManager          # M3.B: BitmapOps + BitmapFunction
    RedisHyperLogManager        # M3.B: HyperLogOps + HyperLogFunction
    RedisGeoManager             # M3.B: GeoOps + GeoFunction
    RedisStructManager          # M3.C: StructOps
    RedisBoundedQueueManager    # M3.C: BoundedQueueOps
    RedisBoundedStackManager    # M3.C: BoundedStackOps
    RedisLockManager            # M4: LockOps + LockFunction
    RedisDistributedLock        # M4: handle returned by try_acquire()
    RedisDistributedBatchLock   # M4: handle returned by batch()
"""

from __future__ import annotations

from .errors import (
    CacheError,
    CapacityError,
    ConfigurationError,
    ConflictError,
    ConnectionError,
    KeyError_,
    SerializationError,
    StateError,
)
from ._perf_guard import RedisPerfGuard
from .managers.redis_bitmap_manager import RedisBitmapManager
from .managers.redis_bounded_queue import RedisBoundedQueue
from .managers.redis_bounded_queue_manager import RedisBoundedQueueManager
from .managers.redis_bounded_stack import RedisBoundedStack
from .managers.redis_bounded_stack_manager import RedisBoundedStackManager
from .managers.redis_collection_manager import RedisCollectionManager
from .managers.redis_distributed_lock import (
    RedisDistributedBatchLock,
    RedisDistributedLock,
)
from .managers.redis_event_manager import RedisEventManager
from .managers.redis_field_manager import RedisFieldManager
from .managers.redis_geo_manager import RedisGeoManager
from .managers.redis_hyper_log_manager import RedisHyperLogManager
from .managers.redis_key_manager import RedisKeyManager
from .managers.redis_limiter_manager import RedisLimiterManager
from .managers.redis_lock_manager import RedisLockManager
from .local.l2_cache_factory import L2CacheFactory
from .local.l2_distributed_cache import L2DistributedCache
from .managers.in_memory_bloom_filter import InMemoryBloomFilter
from .managers.redis_bloom_filter import RedisSharedBloomFilter
from .managers.redis_notification_manager import RedisNotificationManager
from .managers.redis_notification_listener import RedisNotificationListener
from .managers.redis_snowflake_id_builder import RedisSnowflakeIdBuilder
from .managers.redis_ranking_manager import RedisRankingManager
from .managers.redis_script_manager import RedisScriptManager
from .managers.redis_string_manager import RedisStringManager
from .managers.redis_struct_manager import RedisStructManager
from .redis_cache_infrastructure import RedisCacheInfrastructure
from .redis_distributed_cache import RedisDistributedCache
from .redis_cache_properties import ProtocolVersion, RedisCacheProperties, RedisPerfSettings, RedisType
from .redis_provider_registrar import RedisProviderRegistrar

__version__ = "0.10.0"  # bumped for R-224 (SnowflakeIdBuilder)

__all__ = [
    "CacheError",
    "CapacityError",
    "ConfigurationError",
    "ConflictError",
    "ConnectionError",
    "KeyError_",
    "RedisBitmapManager",
    "RedisBoundedQueue",
    "RedisBoundedQueueManager",
    "RedisBoundedStack",
    "RedisBoundedStackManager",
    "RedisCacheInfrastructure",
    "RedisCacheProperties",
    "RedisCollectionManager",
    "RedisDistributedBatchLock",
    "RedisDistributedCache",
    "RedisDistributedLock",
    "RedisEventManager",
    "RedisFieldManager",
    "RedisGeoManager",
    "RedisHyperLogManager",
    "RedisKeyManager",
    "RedisLimiterManager",
    "RedisLockManager",
    "RedisNotificationManager",
    "RedisNotificationListener",
    "RedisPerfGuard",
    "RedisPerfSettings",
    "RedisSharedBloomFilter",
    "InMemoryBloomFilter",
    "L2DistributedCache",
    "L2CacheFactory",
    "RedisSnowflakeIdBuilder",
    "RedisProviderRegistrar",
    "RedisRankingManager",
    "RedisScriptManager",
    "RedisStringManager",
    "RedisStructManager",
    "RedisType",
    "ProtocolVersion",
    "SerializationError",
    "StateError",
    "__version__",
]
