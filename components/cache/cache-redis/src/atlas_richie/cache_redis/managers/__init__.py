"""Per-data-structure Redis manager classes (one per cache-core Protocol).

Real (M1-M4, all 15 ops + 11 functions):

- `RedisStringManager` — ValueOps + StringFunction.
- `RedisFieldManager` — FieldOps + HashFunction.
- `RedisCollectionManager` — CollectionOps + SetFunction.
- `RedisKeyManager` — KeyOps.
- `RedisScriptManager` — ScriptOps.
- `RedisLimiterManager` — LimiterOps.
- `RedisNotificationManager` — NotificationOps + NotificationFunction.
- `RedisEventManager` — EventOps + EventFunction.
- `RedisRankingManager` — RankingOps + ZSetFunction.
- `RedisBitmapManager` — BitmapOps + BitmapFunction.
- `RedisHyperLogManager` — HyperLogOps + HyperLogFunction.
- `RedisGeoManager` — GeoOps + GeoFunction.
- `RedisStructManager` — StructOps (Python-only).
- `RedisBoundedQueueManager` — BoundedQueueOps.
- `RedisBoundedStackManager` — BoundedStackOps.
- `RedisLockManager` — LockOps + LockFunction (3-layer + renewal).
"""

from __future__ import annotations

from .redis_bitmap_manager import RedisBitmapManager
from .redis_bounded_queue import RedisBoundedQueue
from .redis_bounded_queue_manager import RedisBoundedQueueManager
from .redis_bounded_stack import RedisBoundedStack
from .redis_bounded_stack_manager import RedisBoundedStackManager
from .redis_collection_manager import RedisCollectionManager
from .redis_event_manager import RedisEventManager
from .redis_field_manager import RedisFieldManager
from .redis_geo_manager import RedisGeoManager
from .redis_hyper_log_manager import RedisHyperLogManager
from .redis_key_manager import RedisKeyManager
from .redis_limiter_manager import RedisLimiterManager
from .redis_lock_manager import RedisLockManager
from .redis_notification_manager import RedisNotificationManager
from .redis_ranking_manager import RedisRankingManager
from .redis_script_manager import RedisScriptManager
from .redis_string_manager import RedisStringManager
from .redis_struct_manager import RedisStructManager

__all__ = [
    "RedisBitmapManager",
    "RedisBoundedQueue",
    "RedisBoundedQueueManager",
    "RedisBoundedStack",
    "RedisBoundedStackManager",
    "RedisCollectionManager",
    "RedisEventManager",
    "RedisFieldManager",
    "RedisGeoManager",
    "RedisHyperLogManager",
    "RedisKeyManager",
    "RedisLimiterManager",
    "RedisLockManager",
    "RedisNotificationManager",
    "RedisRankingManager",
    "RedisScriptManager",
    "RedisStringManager",
    "RedisStructManager",
]
