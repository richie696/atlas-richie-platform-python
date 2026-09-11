"""Hash 类型缓存管理器。
----
``FieldOps`` + ``HashFunction`` 的 Redis 后端实现（M2）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisHashManager`` 的结构。
同时实现 cache-core 中的底层 ``FieldOps`` Protocol（字段级 Hash 访问）
与高层 ``HashFunction`` Protocol（防击穿 + 批量辅助）。``ProviderRegistrar``
的 ``field_ops()`` 与 ``hash_function()`` 返回同一个实例（Python 允许一个
类结构性地满足多个 Protocol）。

``FieldOps`` 与 ``HashFunction`` 之间方法名冲突（``set``、``increment``、
``decrement``）通过使用单一方法签名、并将额外参数默认设为无操作值解决
（``timeout_millis=0``、``delta=1``）。合并后的方法同时满足两个 Protocol
的签名；语义仅在是否应用 TTL 或自定义 delta 上有所不同。

防雪崩策略（对齐 Java）：仅在高层 ``set(key, field, value, timeout_millis)``
且 ``timeout_millis > 0`` 时生效。底层 ``FieldOps.set``（无 TTL 参数）
**不**附加防雪崩。

M2 中已实现：

- 单字段：``set``、``get``、``get_typed``、``exists``。
- 原子计数器：``increment``、``increment_by``、``increment_double``、
  ``decrement``、``decrement_by``（``delta=1`` 默认值供 ``FieldOps`` 调用方使用）。
- 多字段：``set_all``、``get_all``、``get_many_typed``、``get_many``。
- 元信息：``get_fields``、``size``、``remove``。
- 批量：``batch_set``。
- 高层辅助：``get_object_from_hash_with_lock`` 占位。

后续 R-### 里程碑中处理：

- ``get_with_lock*`` 与 ``get_many_with_lock`` 防击穿
  （M4：需要 ``RedisLockManager`` + Lua 原子释放）。
- ``get_from_hash_with_lock[_typed]``（M4）。
- 写入时的布隆过滤器集成（M4）。
- 性能守卫包装（M4）。

English
--------
Redis-backed `FieldOps` + `HashFunction` (M2).

Mirrors `cn.richie696.component.cache.redis.manage.RedisHashManager`
1:1 in Python. Implements **both** the low-level `FieldOps` Protocol
(field-level Hash access) and the high-level `HashFunction` Protocol
(stampede prevention + bulk helpers) from `cache-core`. The
`ProviderRegistrar.field_ops()` and `.hash_function()` return the
same instance (Python allows a class to satisfy multiple Protocols
structurally).

Method-name collisions between `FieldOps` and `HashFunction`
(`set`, `increment`, `decrement`) are resolved by using a single
signature per method with the extra parameter defaulting to a no-op
value (`timeout_millis=0`, `delta=1`). The merged method satisfies
both Protocols' signatures; semantics differ only in whether TTL or
a custom delta is applied.

Anti-avalanche policy (matches Java): applied on the high-level
`set(key, field, value, timeout_millis)` helper when `timeout_millis
> 0`. Low-level `FieldOps.set` (no TTL argument) does NOT add
anti-avalanche.

What's implemented in M2:

- Single-field: `set`, `get`, `get_typed`, `exists`.
- Atomic counters: `increment`, `increment_by`, `increment_double`,
  `decrement`, `decrement_by` (with `delta=1` default for the
  `FieldOps` callers).
- Multi-field: `set_all`, `get_all`, `get_many_typed`, `get_many`.
- Meta: `get_fields`, `size`, `remove`.
- Batch: `batch_set`.
- High-level helpers: `get_object_from_hash_with_lock` placeholder.

What's deferred to later R-### milestones:

- `get_with_lock*` and `get_many_with_lock` stampede prevention
  (M4: needs `RedisLockManager` + Lua atomic release).
- `get_from_hash_with_lock[_typed]` (M4).
- Bloom filter integration on writes (M4).
- Perf guard wrapping (M4).
"""

from __future__ import annotations

import secrets as _secrets
from typing import Any, Callable, Collection, Dict, List, Set, TypeVar

from atlas_richie.cache_core.function.hash_function import HashFunction
from atlas_richie.cache_core.ops.field_ops import FieldOps

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


class RedisFieldManager(FieldOps, HashFunction):
    """Hash 类型缓存管理器。
    ----
    Redis 后端的 Hash 缓存管理器。

    同时实现 ``FieldOps``（底层字段访问）与 ``HashFunction``（高层业务辅助）。

    English
    --------
    Redis-backed Hash cache manager.

    Implements both `FieldOps` (low-level field access) and
    `HashFunction` (high-level business helpers).

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (for typed reads via
            `get_value_type`).
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

    # ══════════════════════════════════════════════════════════════
    # FieldOps (low-level)
    # ══════════════════════════════════════════════════════════════

    # ── Single field ───────────────────────────────────────────────

    def set(self, key: str, field: str, value: Any, timeout_millis: int = 0) -> None:
        """设置一个 Hash 字段；可选附带 TTL。
        ----
        合并 ``FieldOps.set(key, field, value)``（无 TTL）与
        ``HashFunction.set(key, field, value, timeout_millis)``（带 TTL）。
        当 ``timeout_millis > 0`` 时附加防雪崩偏移（高层策略）。

        English
        --------
        Set one field; optionally with TTL (HashFunction shape).

        Merges `FieldOps.set(key, field, value)` (no TTL) and
        `HashFunction.set(key, field, value, timeout_millis)` (with
        TTL). When `timeout_millis > 0`, applies the anti-avalanche
        offset (high-level policy).

        Args:
            key: 缓存 key。
            field: Hash 字段名。
            value: 字段值。
            timeout_millis: 可选过期时间（毫秒），``0`` 表示不设置。
        """
        client = self._backend.raw_client()
        client.hset(self._k(key), field, encode_value(value))
        if timeout_millis and timeout_millis > 0:
            client.hpexpire(
                self._k(key), int(timeout_millis) + _anti_avalanche_ms(), field
            )

    def get(self, key: str, field: str, clazz: type) -> Any:
        raw = self._backend.raw_client().hget(self._k(key), field)
        return decode_value(raw, clazz)

    def get_typed(self, key: str, field: str, reference: type) -> Any:
        registered = self._infra.get_value_type(key)
        target = registered if registered is not None else reference
        return self.get(key, field, target if target is not None else str)

    def exists(self, key: str, field: str) -> bool:
        return bool(self._backend.raw_client().hexists(self._k(key), field))

    # ── Atomic counters ─────────────────────────────────────────────
    #
    # `FieldOps.increment(key, field)` and
    # `HashFunction.increment(key, field, delta)` are merged with
    # `delta=1` default. Same for `decrement`.

    def increment(self, key: str, field: str, delta: int = 1) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, int(delta))
        )

    def increment_by(self, key: str, field: str, delta: int) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, int(delta))
        )

    def increment_double(self, key: str, field: str, delta: float) -> float:
        return float(
            self._backend.raw_client().hincrbyfloat(
                self._k(key), field, float(delta)
            )
        )

    def decrement(self, key: str, field: str, delta: int = 1) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, -int(delta))
        )

    def decrement_by(self, key: str, field: str, delta: int) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, -int(delta))
        )

    # ── Multi field ────────────────────────────────────────────────

    def set_all(
        self, key: str, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        if not mapping:
            return
        client = self._backend.raw_client()
        encoded = {f: encode_value(v) for f, v in mapping.items()}
        client.hset(self._k(key), mapping=encoded)
        if timeout_millis and timeout_millis > 0:
            ttl = int(timeout_millis) + _anti_avalanche_ms()
            for field in encoded:
                client.hpexpire(self._k(key), ttl, field)

    def get_all(self, key: str, clazz: type) -> Dict[str, Any]:
        raw_map = self._backend.raw_client().hgetall(self._k(key))
        if not raw_map:
            return {}
        out: Dict[str, Any] = {}
        for field, raw in raw_map.items():
            v = decode_value(raw, clazz)
            if v is not None:
                out[field] = v
        return out

    def get_many_typed(
        self, key: str, fields: Collection[str], reference: type
    ) -> List[Any]:
        if not fields:
            return []
        raws = self._backend.raw_client().hmget(self._k(key), list(fields))
        return [
            v
            for v in (decode_value(raw, reference) for raw in raws)
            if v is not None
        ]

    def get_many(
        self, key: str, fields: Collection[str], clazz: type
    ) -> Dict[str, Any]:
        if not fields:
            return {}
        raws = self._backend.raw_client().hmget(self._k(key), list(fields))
        out: Dict[str, Any] = {}
        for field, raw in zip(fields, raws):
            v = decode_value(raw, clazz)
            if v is not None:
                out[field] = v
        return out

    # ── Meta ────────────────────────────────────────────────────────

    def get_fields(self, key: str) -> Set[str]:
        raw = self._backend.raw_client().hkeys(self._k(key))
        return {self._normalise_field(f) for f in raw or []}

    @staticmethod
    def _normalise_field(field: Any) -> str:
        if isinstance(field, bytes):
            return field.decode("utf-8", errors="replace")
        return str(field)

    def size(self, key: str) -> int:
        return int(self._backend.raw_client().hlen(self._k(key)))

    def remove(self, key: str, *fields: str) -> None:
        if not fields:
            return
        self._backend.raw_client().hdel(self._k(key), *fields)

    # ── Batch ───────────────────────────────────────────────────────

    def batch_set(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        """批量添加缓存到 Redis Hash 的方法。
        ----
        跨多个 Hash 批量写入。

        Mapping 形状：``{key1: {field1: v1, field2: v2}, ...}``。使用
        pipeline 一次往返完成批量写入；**非原子性**（对齐 Java 文档）。

        English
        --------
        Bulk set across many Hashes.

        Mapping shape: `{key1: {field1: v1, field2: v2}, ...}`. Use a
        pipeline so the whole batch is one round-trip; NOT atomic
        (per the Java doc).

        Args:
            mapping: 批量添加的缓存数据。
        """
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for key, field_map in mapping.items():
            encoded = {f: encode_value(v) for f, v in field_map.items()}
            pipe.hset(self._k(key), mapping=encoded)
        pipe.execute()

    # ── Stampede prevention (deferred to M4) ────────────────────────

    def get_with_lock(
        self,
        key: str,
        field: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
    ) -> Any:
        raise NotImplementedError(
            "RedisFieldManager.get_with_lock is implemented in R-220 M4 "
            "(requires RedisLockManager + Lua atomic release)."
        )

    def get_with_lock_typed(
        self,
        key: str,
        field: str,
        reference: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
    ) -> Any:
        raise NotImplementedError(
            "RedisFieldManager.get_with_lock_typed is implemented in R-220 M4."
        )

    def get_many_with_lock(
        self,
        key: str,
        fields: Collection[str],
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Dict[str, Any] | None],
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            "RedisFieldManager.get_many_with_lock is implemented in R-220 M4."
        )

    # ══════════════════════════════════════════════════════════════
    # HashFunction (high-level) — anti-stampede + aliases
    # ══════════════════════════════════════════════════════════════

    def get_object_from_hash_with_lock(
        self,
        key: str,
        clazz: type,
        db_loader: Callable[[], Any],
        timeout_millis: int,
    ) -> Any:
        raise NotImplementedError(
            "get_object_from_hash_with_lock is implemented in R-220 M4 "
            "(Bloom + L2 + Redis lock)."
        )

    def get_from_hash_with_lock(
        self,
        key: str,
        hash_key: str,
        clazz: type,
        db_loader: Callable[[], Any],
        timeout_millis: int,
    ) -> Any:
        raise NotImplementedError(
            "get_from_hash_with_lock is implemented in R-220 M4."
        )

    def get_from_hash_with_lock_typed(
        self,
        key: str,
        hash_key: str,
        reference: type,
        db_loader: Callable[[], Any],
        timeout_millis: int,
    ) -> Any:
        raise NotImplementedError(
            "get_from_hash_with_lock_typed is implemented in R-220 M4."
        )


__all__ = ["RedisFieldManager"]
