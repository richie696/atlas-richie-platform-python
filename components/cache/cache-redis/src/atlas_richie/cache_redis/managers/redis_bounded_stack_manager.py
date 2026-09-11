"""有界栈（Bounded LIFO Stack）Redis 实现。
----
``BoundedStackOps`` 的 Redis 后端实现（M3.C）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisBoundedStackManager``
的结构。实现 cache-core 中的 ``BoundedStackOps`` Protocol。

English
--------
Redis-backed `BoundedStackOps` (M3.C).

Mirrors `cn.richie696.component.cache.redis.manage.RedisBoundedStackManager`
1:1. Implements the `BoundedStackOps` Protocol from `cache-core`.
"""

from __future__ import annotations

from typing import TypeVar

from atlas_richie.cache_core.operations.bounded_list_capacity_limits import (
    BoundedListCapacityLimits,
)
from atlas_richie.cache_core.operations.bounded_stack import BoundedStack
from atlas_richie.cache_core.ops.bounded_stack_ops import BoundedStackOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from .redis_bounded_list_support import (
    BOUNDED_DESTROY_SCRIPT,
    BoundedListRedisSupport,
)
from .redis_bounded_stack import RedisBoundedStack

T = TypeVar("T")


class RedisBoundedStackManager(BoundedStackOps):
    """有界栈（Bounded LIFO Stack）Redis 实现。
    ----
    Redis 后端的有界栈管理器。

    English
    --------
    Redis-backed bounded-stack manager.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra
        self._support = BoundedListRedisSupport(backend.raw_client())

    def _make_stack(
        self, key: str, max_len: int, clazz: type
    ) -> RedisBoundedStack:
        ns_key = self._backend.make_key(key)
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        s = RedisBoundedStack(self._support, key, max_len, clazz)
        s._bind(ns_key, ns_meta)
        return s

    def _init_meta(self, key: str, max_len: int) -> bool:
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        return self._support.set_meta_if_absent(ns_meta, max_len)

    def create(self, key: str, max_len: int, clazz: type) -> BoundedStack:
        ns_key = self._backend.make_key(key)
        self._support.assert_list_key_compatible(ns_key, "BoundedStack")
        if not self._init_meta(key, max_len):
            existing = self._support.read_meta_max_len(
                self._backend.make_key(
                    BoundedListCapacityLimits.meta_key(key)
                )
            )
            BoundedListCapacityLimits.assert_max_len_matches(
                key, max_len, existing or max_len
            )
        return self._make_stack(key, max_len, clazz)

    def get(self, key: str, clazz: type) -> BoundedStack:
        ns_meta = self._backend.make_key(
            BoundedListCapacityLimits.meta_key(key)
        )
        max_len = self._support.read_meta_max_len(ns_meta)
        if max_len is None:
            raise KeyError(f"BoundedStack '{key}' does not exist")
        return self._make_stack(key, max_len, clazz)

    def get_or_create(
        self, key: str, max_len: int, clazz: type
    ) -> BoundedStack:
        if not self._init_meta(key, max_len):
            existing = self._support.read_meta_max_len(
                self._backend.make_key(
                    BoundedListCapacityLimits.meta_key(key)
                )
            )
            max_len = existing or max_len
        return self._make_stack(key, max_len, clazz)

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
            s = self.get(key, type(None))
        except KeyError:
            return False
        return s.grow()


__all__ = ["RedisBoundedStackManager"]
