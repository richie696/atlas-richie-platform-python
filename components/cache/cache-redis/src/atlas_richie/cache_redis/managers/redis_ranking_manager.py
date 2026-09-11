"""ZSet 类型缓存管理器。
----
``RankingOps`` + ``ZSetFunction`` 的 Redis 后端实现（M3.B）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisZSetManager`` 的结构。
同时实现 cache-core 中的底层 ``RankingOps`` Protocol 与高层 ``ZSetFunction``
Protocol。``ProviderRegistrar.ranking_ops()`` 与 ``.z_set_function()``
返回同一个实例。

``RankingOps`` 与 ``ZSetFunction`` 之间的方法名冲突：仅 ``increment_score``
在两者上签名一致 —— 这是共享方法而非冲突。其余方法在两个 Protocol 上
名称互不相同（例如 ``RankingOps.set`` 对应 ``ZSetFunction.add_zset_item``；
``RankingOps.pop_min`` 对应 ``ZSetFunction.pop_min_from_zset``）。Java
端故意为底层 ops 管理器与高层 function 辅助使用不同名称，因此 Python
翻译可以逐字实现每个 Protocol 的方法而无需合并签名。

``RankingOps.ordered_set`` 在 Protocol 中类型为 ``set``；Java 中的规范
类型是 ``TreeSet<?>``（已排序容器）。Python 中对应 ``sortedcontainers.SortedSet``
（任何支持 ``(value, score)`` 迭代的有序容器均可）。ZSet 序列化时将
每个元素视作 ``(value, score)`` 二元组。

``ZINTER`` / ``ZUNION`` / ``ZDIFF``（返回计算结果集）需要 Redis 6.2+；
我们直接使用，因为目标 Redis 是 8.8.0。存储型变体（``ZINTERSTORE`` 等）
适用于所有 Redis 版本。

English
--------
Redis-backed `RankingOps` + `ZSetFunction` (M3.B).

Mirrors `cn.richie696.component.cache.redis.manage.RedisZSetManager`
1:1. Implements **both** the low-level `RankingOps` Protocol and the
high-level `ZSetFunction` Protocol from `cache-core`. The
`ProviderRegistrar.ranking_ops()` and `.z_set_function()` return the
same instance.

Method-name collisions between `RankingOps` and `ZSetFunction`:
**only `increment_score` has the same signature on both** — that's a
shared method, not a collision. Every other method has a distinct
name on the two Protocols (e.g. `RankingOps.set` vs
`ZSetFunction.add_zset_item`; `RankingOps.pop_min` vs
`ZSetFunction.pop_min_from_zset`). The Java side deliberately uses
different names for the low-level ops manager and the high-level
function helper, so the Python translation can implement each
Protocol's methods verbatim without merging signatures.

`RankingOps.ordered_set` is typed as `set` in the Protocol; the
canonical Java type is `TreeSet<?>` (a sorted container). The Python
equivalent is `sortedcontainers.SortedSet` (any ordered container
that supports `(value, score)` iteration works). For ZSet
serialisation we treat each element as a `(value, score)` 2-tuple.

ZINTER / ZUNION / ZDIFF (returning the computed result set) require
Redis 6.2+; we use them directly since the target Redis is 8.8.0.
The store variants (ZINTERSTORE etc.) work on all Redis versions.
"""

from __future__ import annotations

from typing import Any, Collection, Dict, List, Set, TypeVar

from atlas_richie.cache_core.function.z_set_function import ZSetFunction
from atlas_richie.cache_core.ops.ranking_ops import RankingOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value

T = TypeVar("T")


class RedisRankingManager(RankingOps, ZSetFunction):
    """ZSet 类型缓存管理器。
    ----
    Redis 后端的 ZSet / 排行榜管理器。

    同时实现 ``RankingOps``（底层）与 ``ZSetFunction``（高层批量 +
    交集辅助）。

    English
    --------
    Redis-backed ZSet / leaderboard manager.

    Implements both `RankingOps` (low-level) and `ZSetFunction`
    (high-level bulk + intersection helpers).

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (currently unused; reserved
            for typed read plumbing if needed).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    @staticmethod
    def _normalise_member(value: Any) -> str:
        """Encode a member for ZSet storage (ZSet members are
        byte strings; non-str values get JSON-encoded)."""
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", errors="replace")
        if isinstance(value, str):
            return value
        return encode_value(value)

    @staticmethod
    def _decode_member(raw: Any, clazz: type) -> Any:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return decode_value(raw, clazz)

    # ══════════════════════════════════════════════════════════════
    # RankingOps (low-level)
    # ══════════════════════════════════════════════════════════════

    def set(self, key: str, value: Any, score: float) -> None:
        self._backend.raw_client().zadd(
            self._k(key), {self._normalise_member(value): float(score)}
        )

    def set_all(self, key: str, ordered_set: set) -> None:
        if not ordered_set:
            return
        mapping: Dict[str, float] = {}
        for element in ordered_set:
            if isinstance(element, tuple) and len(element) == 2:
                v, s = element
                mapping[self._normalise_member(v)] = float(s)
            else:
                # Fallback: caller passed a flat set; use 0 as score.
                mapping[self._normalise_member(element)] = 0.0
        if mapping:
            self._backend.raw_client().zadd(self._k(key), mapping)

    def batch_set(self, mapping: dict[str, set]) -> None:
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for key, ordered_set in mapping.items():
            flat: Dict[str, float] = {}
            for element in ordered_set or []:
                if isinstance(element, tuple) and len(element) == 2:
                    v, s = element
                    flat[self._normalise_member(v)] = float(s)
                else:
                    flat[self._normalise_member(element)] = 0.0
            if flat:
                pipe.zadd(self._k(key), flat)
        pipe.execute()

    def size(self, key: str) -> int:
        return int(self._backend.raw_client().zcard(self._k(key)))

    def remove(self, key: str, *values: Any) -> None:
        if not values:
            return
        self._backend.raw_client().zrem(
            self._k(key), *[self._normalise_member(v) for v in values]
        )

    def remove_by_rank(self, key: str, start: int, end: int) -> None:
        self._backend.raw_client().zremrangebyrank(self._k(key), int(start), int(end))

    def remove_by_score(
        self, key: str, min_score: float, max_score: float
    ) -> None:
        self._backend.raw_client().zremrangebyscore(
            self._k(key), float(min_score), float(max_score)
        )

    def increment_score(
        self, key: str, value: Any, delta: float
    ) -> float:
        return float(
            self._backend.raw_client().zincrby(
                self._k(key), float(delta), self._normalise_member(value)
            )
        )

    def pop_min(self, key: str, reference: type) -> Any:
        raws = self._backend.raw_client().zpopmin(self._k(key))
        if not raws:
            return None
        return self._decode_member(raws[0][0], reference)

    def pop_min_many(self, key: str, count: int, reference: type) -> Set[Any]:
        if count <= 0:
            return set()
        raws = self._backend.raw_client().zpopmin(self._k(key), int(count))
        return {self._decode_member(m, reference) for m, _ in (raws or [])}

    def range(
        self, key: str, start: int, end: int, reference: type
    ) -> Set[Any]:
        raws = self._backend.raw_client().zrange(self._k(key), int(start), int(end))
        return {self._decode_member(r, reference) for r in raws or []}

    def range_by_score(
        self, key: str, min_score: float, max_score: float, reference: type
    ) -> Set[Any]:
        raws = self._backend.raw_client().zrangebyscore(
            self._k(key), float(min_score), float(max_score)
        )
        return {self._decode_member(r, reference) for r in raws or []}

    def reverse_rank(self, key: str, value: Any) -> int:
        """0-based descending rank. -1 if the member is absent."""
        rank = self._backend.raw_client().zrevrank(
            self._k(key), self._normalise_member(value)
        )
        return int(rank) if rank is not None else -1

    # ══════════════════════════════════════════════════════════════
    # ZSetFunction (high-level)
    # ══════════════════════════════════════════════════════════════

    def add_zset(self, key: str, ordered_set: set) -> None:
        # `ZSetFunction.add_zset` ↔ `RankingOps.set_all` (different name).
        self.set_all(key, ordered_set)

    def add_zset_item(self, key: str, value: Any, score: float) -> None:
        # `ZSetFunction.add_zset_item` ↔ `RankingOps.set`.
        self.set(key, value, score)

    def batch_add_to_zset(self, mapping: dict[str, set]) -> None:
        self.batch_set(mapping)

    def get_zset_data(
        self, key: str, start: int, end: int, reference: type
    ) -> Dict[float, Any]:
        raws = self._backend.raw_client().zrange(
            self._k(key), int(start), int(end), withscores=True
        )
        out: Dict[float, Any] = {}
        for member, score in raws or []:
            v = self._decode_member(member, reference)
            if v is not None:
                out[float(score)] = v
        return out

    def get_zset_rank(self, key: str, value: Any) -> int:
        rank = self._backend.raw_client().zrank(
            self._k(key), self._normalise_member(value)
        )
        return int(rank) if rank is not None else -1

    def get_zset_reverse_rank(self, key: str, value: Any) -> int:
        return self.reverse_rank(key, value)

    def get_zset_size(self, key: str) -> int:
        return self.size(key)

    def reverse_range_with_scores(
        self, key: str, start: int, end: int, reference: type
    ) -> Set[Any]:
        raws = self._backend.raw_client().zrevrange(
            self._k(key), int(start), int(end), withscores=False
        )
        return {self._decode_member(r, reference) for r in raws or []}

    def reverse_range_by_score(
        self, key: str, min_score: float, max_score: float, reference: type
    ) -> Set[Any]:
        raws = self._backend.raw_client().zrevrangebyscore(
            self._k(key), float(max_score), float(min_score)
        )
        return {self._decode_member(r, reference) for r in raws or []}

    def pop_min_from_zset(self, key: str, reference: type) -> Any:
        return self.pop_min(key, reference)

    def pop_min_from_zset_many(
        self, key: str, count: int, reference: type
    ) -> Set[Any]:
        return self.pop_min_many(key, count, reference)

    def remove_zset_item(self, key: str, *values: Any) -> None:
        self.remove(key, *values)

    def remove_zset_item_by_rank(
        self, key: str, start: int, end: int
    ) -> None:
        self.remove_by_rank(key, start, end)

    def remove_zset_item_by_score(
        self, key: str, min_score: float, max_score: float
    ) -> None:
        self.remove_by_score(key, min_score, max_score)

    # ── Set algebra: ZINTER / ZUNION / ZDIFF (Redis 6.2+) ───────────

    def intersect_from_zset(
        self, key: str, other_keys: Collection[str], reference: type
    ) -> List[Any]:
        namespaced = [self._k(key)] + [self._k(k) for k in other_keys]
        raws = self._backend.raw_client().zinter(namespaced)
        return [self._decode_member(r, reference) for r in raws or []]

    def union_from_zset(
        self, key: str, other_keys: Collection[str], reference: type
    ) -> List[Any]:
        namespaced = [self._k(key)] + [self._k(k) for k in other_keys]
        raws = self._backend.raw_client().zunion(namespaced)
        return [self._decode_member(r, reference) for r in raws or []]

    def difference_from_zset(
        self, key: str, other_keys: Collection[str], reference: type
    ) -> List[Any]:
        namespaced = [self._k(key)] + [self._k(k) for k in other_keys]
        raws = self._backend.raw_client().zdiff(namespaced)
        return [self._decode_member(r, reference) for r in raws or []]

    def intersect_and_store_from_zset(
        self, key: str, other_keys: Collection[str], dest_key: str
    ) -> int:
        namespaced = [self._k(key)] + [self._k(k) for k in other_keys]
        return int(
            self._backend.raw_client().zinterstore(
                self._k(dest_key), namespaced
            )
        )

    def union_and_store_from_zset(
        self, key: str, other_keys: Collection[str], dest_key: str
    ) -> int:
        namespaced = [self._k(key)] + [self._k(k) for k in other_keys]
        return int(
            self._backend.raw_client().zunionstore(
                self._k(dest_key), namespaced
            )
        )

    def difference_and_store_from_zset(
        self, key: str, other_keys: Collection[str], dest_key: str
    ) -> int:
        namespaced = [self._k(key)] + [self._k(k) for k in other_keys]
        return int(
            self._backend.raw_client().zdiffstore(
                self._k(dest_key), namespaced
            )
        )


__all__ = ["RedisRankingManager"]
