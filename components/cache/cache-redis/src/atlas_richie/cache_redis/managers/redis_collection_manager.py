"""Set 类型缓存管理器。
----
``CollectionOps`` + ``SetFunction`` 的 Redis 后端实现（M2）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisSetManager`` 的结构。
同时实现 cache-core 中的底层 ``CollectionOps`` Protocol（Set 数据结构访问）
与高层 ``SetFunction`` Protocol（pop 辅助 + 批量差集）。``ProviderRegistrar``
的 ``collection_ops()`` 与 ``set_function()`` 返回同一个实例。

``CollectionOps`` 与 ``SetFunction`` 之间方法名冲突：**无**。Java 端故意为
高层与底层 Set 操作使用不同方法名（例如 ``CollectionOps.pop`` 对应
``SetFunction.pop_data_from_set``，``CollectionOps.size`` 对应
``SetFunction.get_set_size``，``CollectionOps.add`` 对应
``SetFunction.add_set_item``）。这意味着 Python 翻译可以逐字实现每个
Protocol 的方法而无需合并签名 —— Java 的设计选择与 Python 缺少方法重载
恰好契合的少数情形之一。

防雪崩策略（对齐 Java）：仅在高层 ``add_set`` / ``add_set_item`` 辅助
方法的调用方显式传入 TTL 时生效（在 ``SetFunction`` 中很少见；Set 通常
没有 TTL）。``CollectionOps.set(key, values, timeout_millis)`` 辅助方法会
对传入的 TTL 应用防雪崩。

English
--------
Redis-backed `CollectionOps` + `SetFunction` (M2).

Mirrors `cn.richie696.component.cache.redis.manage.RedisSetManager`
1:1 in Python. Implements **both** the low-level `CollectionOps`
Protocol (Set data structure access) and the high-level `SetFunction`
Protocol (pop helpers + bulk difference) from `cache-core`. The
`ProviderRegistrar.collection_ops()` and `.set_function()` return
the same instance.

Method-name collisions between `CollectionOps` and `SetFunction`:
**none**. The Java side deliberately uses different method names for
the high-level and low-level Set operations (e.g.
`CollectionOps.pop` vs `SetFunction.pop_data_from_set`,
`CollectionOps.size` vs `SetFunction.get_set_size`,
`CollectionOps.add` vs `SetFunction.add_set_item`). This means the
Python translation can implement each Protocol's methods verbatim
without merging signatures — a rare case where the Java design
choice and Python's lack of overloading line up perfectly.

Anti-avalanche policy (matches Java): applied on the high-level
`add_set` / `add_set_item` helpers when the calling context
explicitly passes a TTL (rare; Set is usually TTL-less in
`SetFunction`). The `CollectionOps.set(key, values, timeout_millis)`
helper applies anti-avalanche to the supplied TTL.
"""

from __future__ import annotations

import secrets as _secrets
from typing import Any, Callable, Collection, Set as _PySet, TypeVar

from atlas_richie.cache_core.function.set_function import SetFunction
from atlas_richie.cache_core.ops.collection_ops import CollectionOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value

T = TypeVar("T")

# Anti-avalanche TTL offset range (matches Java's
# `CacheFunction.getRandomExtraMillis()`).
_MIN_ANTI_AVALANCHE_MS = 60_000
_MAX_ANTI_AVALANCHE_MS = 600_000


def _anti_avalanche_ms() -> int:
    return (
        _secrets.randbelow(_MAX_ANTI_AVALANCHE_MS - _MIN_ANTI_AVALANCHE_MS)
        + _MIN_ANTI_AVALANCHE_MS
    )


class RedisCollectionManager(CollectionOps, SetFunction):
    """Set 类型缓存管理器。
    ----
    Redis 后端的 Set 缓存管理器。

    同时实现 ``CollectionOps``（底层 Set 访问）与 ``SetFunction``
    （高层业务辅助）。

    English
    --------
    Redis-backed Set cache manager.

    Implements both `CollectionOps` (low-level Set access) and
    `SetFunction` (high-level business helpers).

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (currently unused; reserved
            for the M4 typed-read plumbing).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    # ── Internal helpers ───────────────────────────────────────────

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    @staticmethod
    def _encode_set(values: _PySet[Any]) -> list[str]:
        return [encode_value(v) for v in values]

    @staticmethod
    def _decode_set(raws: list[Any], clazz: type) -> _PySet[Any]:
        return {v for v in (decode_value(r, clazz) for r in raws) if v is not None}

    # ══════════════════════════════════════════════════════════════
    # CollectionOps (low-level)
    # ══════════════════════════════════════════════════════════════

    def get(self, key: str, clazz: type) -> _PySet[T]:
        raws = self._backend.raw_client().smembers(self._k(key))
        return self._decode_set(raws, clazz)

    def set(
        self, key: str, values: _PySet[Any], timeout_millis: int
    ) -> None:
        """Replace the entire Set with `values`; apply TTL with
        anti-avalanche offset if `timeout_millis > 0`.

        Uses DEL + SADD in a pipeline so the operation is one
        round-trip; the pipeline is NOT transactional.
        """
        client = self._backend.raw_client()
        encoded = self._encode_set(values)
        pipe = client.pipeline(transaction=False)
        pipe.delete(self._k(key))
        if encoded:
            pipe.sadd(self._k(key), *encoded)
        if timeout_millis and timeout_millis > 0:
            pipe.pexpire(
                self._k(key),
                int(timeout_millis) + _anti_avalanche_ms(),
            )
        pipe.execute()

    def add(self, key: str, value: Any) -> None:
        self._backend.raw_client().sadd(self._k(key), encode_value(value))

    def size(self, key: str) -> int:
        return int(self._backend.raw_client().scard(self._k(key)))

    def exists(self, key: str, value: Any) -> bool:
        return bool(
            self._backend.raw_client().sismember(
                self._k(key), encode_value(value)
            )
        )

    def remove(self, key: str, *values: Any) -> None:
        if not values:
            return
        self._backend.raw_client().srem(
            self._k(key), *[encode_value(v) for v in values]
        )

    def batch_set(self, mapping: dict[str, _PySet]) -> None:
        """Bulk replace Sets across many keys.

        NOT atomic (per the Java doc). Uses a pipeline so the batch
        is one round-trip.
        """
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for key, values in mapping.items():
            pipe.delete(self._k(key))
            encoded = self._encode_set(values)
            if encoded:
                pipe.sadd(self._k(key), *encoded)
        pipe.execute()

    def pop(self, key: str, clazz: type) -> Any:
        raw = self._backend.raw_client().spop(self._k(key))
        if raw is None:
            return None
        if isinstance(raw, (list, _PySet)):
            raw = raw[0] if raw else None
        if raw is None:
            return None
        return decode_value(raw, clazz)

    def pop_many(self, key: str, count: int, clazz: type) -> _PySet[T]:
        if count <= 0:
            return set()
        raws = self._backend.raw_client().spop(self._k(key), count)
        if raws is None:
            return set()
        if isinstance(raws, (bytes, str)):
            raws = [raws]
        return self._decode_set(list(raws), clazz)

    def get_with_lock(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], _PySet[T] | None],
    ) -> _PySet[T]:
        raise NotImplementedError(
            "RedisCollectionManager.get_with_lock is implemented in R-220 M4."
        )

    # ══════════════════════════════════════════════════════════════
    # SetFunction (high-level) — pop / difference / batch
    # ══════════════════════════════════════════════════════════════

    def get_from_set_with_lock(
        self,
        key: str,
        reference: type,
        db_loader: Callable[[], _PySet[T] | None],
        timeout_millis: int,
    ) -> _PySet[T]:
        raise NotImplementedError(
            "get_from_set_with_lock is implemented in R-220 M4 "
            "(Bloom + L2 + Redis lock)."
        )

    def get_from_set(self, key: str, reference: type) -> _PySet[T]:
        return self.get(key, reference)

    def pop_data_from_set(self, key: str, reference: type) -> Any:
        return self.pop(key, reference)

    def pop_members_from_set(
        self, key: str, count: int, reference: type
    ) -> _PySet[T]:
        return self.pop_many(key, count, reference)

    def difference_from_set(
        self, keys: Collection[str], reference: type
    ) -> _PySet[T]:
        """SDIFF across multiple keys (left-to-right precedence)."""
        if not keys:
            return set()
        namespaced = [self._k(k) for k in keys]
        raws = self._backend.raw_client().sdiff(*namespaced)
        if not raws:
            return set()
        return self._decode_set(list(raws), reference)

    def difference_from_set_with_key(
        self, key: str, other_keys: Collection[str], reference: type
    ) -> _PySet[T]:
        """SDIFF `key` minus the union of `other_keys`."""
        if not other_keys:
            return self.get_from_set(key, reference)
        namespaced = [self._k(k) for k in other_keys]
        raws = self._backend.raw_client().sdiff(self._k(key), *namespaced)
        if not raws:
            return set()
        return self._decode_set(list(raws), reference)

    def difference_and_store_from_set(
        self, compare_keys: Collection[str], dest_key: str
    ) -> int:
        """SDIFFSTORE; returns the cardinality of the stored set."""
        if not compare_keys:
            return 0
        namespaced = [self._k(k) for k in compare_keys]
        return int(
            self._backend.raw_client().sdiffstore(
                self._k(dest_key), *namespaced
            )
        )

    def exists_in_set(self, key: str, value: Any) -> bool:
        return self.exists(key, value)

    def batch_add_to_set(self, mapping: dict[str, _PySet]) -> None:
        """Bulk SADD across many Sets; NOT atomic (per the Java doc)."""
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for key, values in mapping.items():
            encoded = self._encode_set(values)
            if encoded:
                pipe.sadd(self._k(key), *encoded)
        pipe.execute()

    def add_set(self, key: str, values: _PySet) -> None:
        if not values:
            return
        self._backend.raw_client().sadd(
            self._k(key), *self._encode_set(values)
        )

    def add_set_item(self, key: str, *value: Any) -> None:
        if not value:
            return
        self._backend.raw_client().sadd(
            self._k(key), *[encode_value(v) for v in value]
        )

    def remove_set_item(self, key: str, *values: Any) -> None:
        self.remove(key, *values)

    def get_set_size(self, key: str) -> int:
        return self.size(key)


__all__ = ["RedisCollectionManager"]
