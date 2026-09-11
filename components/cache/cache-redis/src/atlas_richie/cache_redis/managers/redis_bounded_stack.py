"""Redis-backed `BoundedStack` implementation.

Mirrors `cn.richie696.component.cache.redis.manage.RedisBoundedStackManager`
1:1. Extends the framework-layer `BoundedStack` ABC. Uses Lua scripts
+ redis-py for atomicity.

Differences vs `RedisBoundedQueue`:

- No LTRIM (FIFO trim on overflow); stack push rejects when full.
- `latest(count)` returns the `count` most-recently-pushed elements
  (newest first), via `LRANGE key -count -1` + reverse.
"""

from __future__ import annotations

from typing import List, Optional, TypeVar

from atlas_richie.cache_core.operations.bounded_list_capacity_limits import (
    BoundedListCapacityLimits,
)
from atlas_richie.cache_core.operations.bounded_stack import BoundedStack

from .bounded_list_element_converter import RedisBoundedListElementConverter
from .redis_bounded_list_support import (
    BOUNDED_DESTROY_SCRIPT,
    BOUNDED_GROW_MAX_LEN_SCRIPT,
    BOUNDED_STACK_PUSH_SCRIPT,
    BoundedListRedisSupport,
)
from ..serialization import encode_value

T = TypeVar("T")


class RedisBoundedStack(BoundedStack):
    """Redis-backed bounded LIFO stack.

    Args:
        support: The `BoundedListRedisSupport` helper.
        key: User-supplied stack name.
        max_len: Capacity.
        clazz: Element deserialisation target.
    """

    def __init__(
        self,
        support: BoundedListRedisSupport,
        key: str,
        max_len: int,
        clazz: type,
    ) -> None:
        BoundedListCapacityLimits.validate_max_len(max_len)
        super().__init__(key, max_len)
        self._support = support
        self._clazz = clazz
        self._ns_key: Optional[str] = None
        self._ns_meta: Optional[str] = None

    def _resolve_keys(self) -> tuple[str, str]:
        if self._ns_key is None or self._ns_meta is None:
            raise RuntimeError(
                f"{self!r} has not been bound to a redis namespace; "
                f"the manager must call _bind() after construction"
            )
        return self._ns_key, self._ns_meta

    def _bind(self, ns_key: str, ns_meta: str) -> None:
        self._ns_key = ns_key
        self._ns_meta = ns_meta

    def size(self) -> int:
        ns_key, _ = self._resolve_keys()
        return int(self._support._client.llen(ns_key))

    def is_empty(self) -> bool:
        return self.size() == 0

    def push(self, item: T) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        result = self._support.evalsha_cached(
            BOUNDED_STACK_PUSH_SCRIPT,
            2,
            ns_meta,
            ns_key,
            encode_value(item),
        )
        # Lua returns 1 on push, 0 on full, -1 on missing meta.
        return int(result) == 1

    def pop(self) -> Optional[T]:
        ns_key, _ = self._resolve_keys()
        raw = self._support._client.rpop(ns_key)
        return RedisBoundedListElementConverter.convert_one(
            raw, self.key, self._clazz, "pop"
        )

    def peek(self) -> Optional[T]:
        ns_key, _ = self._resolve_keys()
        raw = self._support._client.lindex(ns_key, -1)
        return RedisBoundedListElementConverter.convert_one(
            raw, self.key, self._clazz, "peek"
        )

    def latest(self, count: int) -> List[T]:
        ns_key, _ = self._resolve_keys()
        if count <= 0:
            return []
        raws = self._support._client.lrange(ns_key, -count, -1)
        # `LRANGE -count -1` returns oldest-first; reverse to newest-first.
        raws = list(raws or [])[::-1]
        return RedisBoundedListElementConverter.convert_all(
            raws, self.key, self._clazz, "latest"
        )

    def grow(self) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        current = self._support.read_meta_max_len(ns_meta)
        if current is None or not BoundedListCapacityLimits.can_grow(current):
            return False
        ceiling = BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
        new_max = int(
            self._support.evalsha_cached(
                BOUNDED_GROW_MAX_LEN_SCRIPT,
                1,
                ns_meta,
                str(ceiling),
            )
        )
        if new_max == current:
            return False
        # Stack: no trim needed (pushing refused when at cap).
        self._max_len = new_max
        return True

    def expire(self, timeout: int) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        ok1 = bool(self._support._client.expire(ns_key, int(timeout)))
        ok2 = bool(self._support._client.expire(ns_meta, int(timeout)))
        return ok1 or ok2

    def destroy(self) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        n = int(
            self._support.evalsha_cached(
                BOUNDED_DESTROY_SCRIPT, 2, ns_meta, ns_key
            )
        )
        if n > 0:
            self._destroyed = True
        return n > 0


__all__ = ["RedisBoundedStack"]
