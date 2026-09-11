"""有界队列（Bounded FIFO Queue）Redis 实现。
----
``BoundedQueueOps`` 的 Redis 后端实现（M3.C）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisBoundedQueueManager``
的结构。实现 cache-core 中的 ``BoundedQueueOps`` Protocol。管理器创建并
绑定 ``RedisBoundedQueue`` 实例；队列本身就是实际的数据结构句柄。

English
--------
Redis-backed `BoundedQueueOps` (M3.C).

Mirrors `cn.richie696.component.cache.redis.manage.RedisBoundedQueueManager`
1:1. Implements the `BoundedQueueOps` Protocol from `cache-core`.
The manager creates and binds `RedisBoundedQueue` instances; the
queues are the actual data-structure handles.
"""

from __future__ import annotations

from typing import TypeVar

from atlas_richie.cache_core.operations.bounded_list_capacity_limits import (
    BoundedListCapacityLimits,
)
from atlas_richie.cache_core.operations.bounded_queue import BoundedQueue
from atlas_richie.cache_core.ops.bounded_queue_ops import BoundedQueueOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from .redis_bounded_list_support import BoundedListRedisSupport
from .redis_bounded_queue import RedisBoundedQueue

T = TypeVar("T")


class RedisBoundedQueueManager(BoundedQueueOps):
    """有界队列（Bounded FIFO Queue）Redis 实现。
    ----
    Redis 后端的有界队列管理器。

    1:1 实现 ``BoundedQueueOps``。该类是有状态的：它在所有
    ``RedisBoundedQueue`` 对象之间共享一个 ``BoundedListRedisSupport``
    实例，从而复用脚本 SHA 缓存。

    English
    --------
    Redis-backed bounded-queue manager.

    Implements `BoundedQueueOps` 1:1. The class is stateful: it
    shares one `BoundedListRedisSupport` instance across all
    `RedisBoundedQueue` objects so the script SHA cache is reused.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra
        self._support = BoundedListRedisSupport(backend.raw_client())

    def _make_queue(
        self, key: str, max_len: int, clazz: type
    ) -> RedisBoundedQueue:
        ns_key = self._backend.make_key(key)
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        q = RedisBoundedQueue(self._support, key, max_len, clazz)
        q._bind(ns_key, ns_meta)
        return q

    def _init_meta(self, key: str, max_len: int) -> bool:
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        return self._support.set_meta_if_absent(ns_meta, max_len)

    def create(self, key: str, max_len: int, clazz: type) -> BoundedQueue:
        ns_key = self._backend.make_key(key)
        self._support.assert_list_key_compatible(ns_key, "BoundedQueue")
        if not self._init_meta(key, max_len):
            existing = self._support.read_meta_max_len(
                self._backend.make_key(
                    BoundedListCapacityLimits.meta_key(key)
                )
            )
            BoundedListCapacityLimits.assert_max_len_matches(
                key, max_len, existing or max_len
            )
        return self._make_queue(key, max_len, clazz)

    def get(self, key: str, clazz: type) -> BoundedQueue:
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        max_len = self._support.read_meta_max_len(ns_meta)
        if max_len is None:
            raise KeyError(f"BoundedQueue '{key}' does not exist")
        return self._make_queue(key, max_len, clazz)

    def get_or_create(
        self, key: str, max_len: int, clazz: type
    ) -> BoundedQueue:
        if not self._init_meta(key, max_len):
            existing = self._support.read_meta_max_len(
                self._backend.make_key(
                    BoundedListCapacityLimits.meta_key(key)
                )
            )
            max_len = existing or max_len
        return self._make_queue(key, max_len, clazz)

    def exists(self, key: str) -> bool:
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        return self._support.read_meta_max_len(ns_meta) is not None

    def destroy(self, key: str) -> bool:
        ns_key = self._backend.make_key(key)
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        from .redis_bounded_list_support import BOUNDED_DESTROY_SCRIPT

        n = int(
            self._support.evalsha_cached(
                BOUNDED_DESTROY_SCRIPT, 2, ns_meta, ns_key
            )
        )
        return n > 0

    def expire(self, key: str, timeout: int) -> bool:
        ns_key = self._backend.make_key(key)
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        ok1 = bool(self._support._client.expire(ns_key, int(timeout)))
        ok2 = bool(self._support._client.expire(ns_meta, int(timeout)))
        return ok1 or ok2

    def grow(self, key: str) -> bool:
        try:
            q = self.get(key, type(None))
        except KeyError:
            return False
        return q.grow()


__all__ = ["RedisBoundedQueueManager"]
