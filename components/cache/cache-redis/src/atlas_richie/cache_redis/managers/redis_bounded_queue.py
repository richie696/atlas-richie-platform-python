"""Redis-backed `BoundedQueue` implementation.

Mirrors `cn.richie696.component.cache.redis.manage.RedisBoundedQueueManager`
1:1. Extends the framework-layer `BoundedQueue` ABC from
`cache-core` and implements the abstract methods using Lua scripts
+ redis-py.

The atomicity-critical operations (`offer`, `grow`) run via Lua
scripts so the meta key and the data list stay consistent under
concurrent producers.
"""

from __future__ import annotations

from typing import List, Optional, TypeVar

from atlas_richie.cache_core.operations.bounded_list_capacity_limits import (
    BoundedListCapacityLimits,
)
from atlas_richie.cache_core.operations.bounded_queue import BoundedQueue

from ..serialization import decode_value, encode_value
from .bounded_list_element_converter import RedisBoundedListElementConverter
from .redis_bounded_list_support import (
    BOUNDED_QUEUE_OFFER_SCRIPT,
    BoundedListRedisSupport,
)

T = TypeVar("T")


class RedisBoundedQueue(BoundedQueue):
    """Redis-backed bounded FIFO queue.

    Active-pull model: business code calls `poll()` / `drain(int)`
    to consume. There is no push consumer group, no ACK. Positioned
    as peak-shaving buffer / lightweight async, NOT a Redis Stream
    message queue.

    Args:
        support: The `BoundedListRedisSupport` helper.
        key: User-supplied queue name.
        max_len: Capacity (validated against
            `BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING`).
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
        # Resolve the namespaced data + meta keys once at construction.
        # `key` is the user-supplied name; `_key` resolves to
        # `namespace:key`, and `_meta_key` adds the `:meta` suffix.
        self._ns_key: Optional[str] = None  # set by manager
        self._ns_meta: Optional[str] = None

    def _resolve_keys(self) -> tuple[str, str]:
        """Lazily resolve namespaced data + meta keys (set by the
        manager right after construction)."""
        if self._ns_key is None or self._ns_meta is None:
            raise RuntimeError(
                f"{self!r} has not been bound to a redis namespace; "
                f"the manager must call _bind() after construction"
            )
        return self._ns_key, self._ns_meta

    def _bind(self, ns_key: str, ns_meta: str) -> None:
        """Bind the namespaced keys (called by the manager)."""
        self._ns_key = ns_key
        self._ns_meta = ns_meta

    # ── State queries ──────────────────────────────────────────────

    def size(self) -> int:
        ns_key, _ = self._resolve_keys()
        return int(self._support._client.llen(ns_key))

    def is_empty(self) -> bool:
        return self.size() == 0

    # ── Write ──────────────────────────────────────────────────────

    def offer(self, item: T) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        encoded = encode_value(item)
        result = self._support.evalsha_cached(
            BOUNDED_QUEUE_OFFER_SCRIPT,
            2,
            ns_meta,
            ns_key,
            encoded,
        )
        # Lua returns -1 if the meta key is missing (i.e. the queue
        # was destroyed between get_or_create and offer); treat that
        # as a no-op.
        return int(result) >= 0

    # ── Read ───────────────────────────────────────────────────────

    def poll(self) -> Optional[T]:
        ns_key, _ = self._resolve_keys()
        raw = self._support._client.lpop(ns_key)
        return RedisBoundedListElementConverter.convert_one(
            raw, self.key, self._clazz, "poll"
        )

    def peek(self) -> Optional[T]:
        ns_key, _ = self._resolve_keys()
        raw = self._support._client.lindex(ns_key, 0)
        return RedisBoundedListElementConverter.convert_one(
            raw, self.key, self._clazz, "peek"
        )

    def peek_tail(self) -> Optional[T]:
        ns_key, _ = self._resolve_keys()
        raw = self._support._client.lindex(ns_key, -1)
        return RedisBoundedListElementConverter.convert_one(
            raw, self.key, self._clazz, "peek_tail"
        )

    def drain(self, count: int) -> List[T]:
        ns_key, _ = self._resolve_keys()
        if count <= 0:
            return []
        raws = self._support._client.lpop(ns_key, count)
        if raws is None:
            return []
        if isinstance(raws, (bytes, bytearray, str)):
            raws = [raws]
        return RedisBoundedListElementConverter.convert_all(
            list(raws), self.key, self._clazz, "drain"
        )

    # ── Capacity ───────────────────────────────────────────────────

    def grow(self) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        current = self._support.read_meta_max_len(ns_meta)
        if current is None:
            return False
        if not BoundedListCapacityLimits.can_grow(current):
            return False
        ceiling = BoundedListCapacityLimits.BOUNDED_MAX_LEN_CEILING
        # Step 1: double the meta (atomic via Lua).
        from .redis_bounded_list_support import BOUNDED_GROW_MAX_LEN_SCRIPT

        new_max = self._support.evalsha_cached(
            BOUNDED_GROW_MAX_LEN_SCRIPT,
            1,
            ns_meta,
            str(ceiling),
        )
        new_max = int(new_max)
        if new_max == current:
            return False  # already at cap
        # Step 2: trim the data list to the new max.
        from .redis_bounded_list_support import (
            BOUNDED_TRIM_LIST_TO_META_SCRIPT,
        )

        self._support.evalsha_cached(
            BOUNDED_TRIM_LIST_TO_META_SCRIPT, 2, ns_key, ns_meta
        )
        # Update the in-memory `max_len` for callers.
        self._max_len = new_max
        return True

    # ── Lifecycle ──────────────────────────────────────────────────

    def expire(self, timeout: int) -> bool:
        ns_key, ns_meta = self._resolve_keys()
        ok1 = bool(self._support._client.expire(ns_key, int(timeout)))
        ok2 = bool(self._support._client.expire(ns_meta, int(timeout)))
        return ok1 or ok2

    def destroy(self) -> bool:
        from .redis_bounded_list_support import BOUNDED_DESTROY_SCRIPT

        ns_key, ns_meta = self._resolve_keys()
        n = int(
            self._support.evalsha_cached(
                BOUNDED_DESTROY_SCRIPT, 2, ns_meta, ns_key
            )
        )
        if n > 0:
            self._destroyed = True
        return n > 0


__all__ = ["RedisBoundedQueue"]
