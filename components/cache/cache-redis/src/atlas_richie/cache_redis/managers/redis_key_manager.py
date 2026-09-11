"""Redis Key 操作管理器。
----
``KeyOps`` 协议的 Redis 后端实现（M3.A）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisKeyManager`` 的结构；
实现底层的 ``KeyOps`` Protocol（key 生命周期 + 元信息 + 批量操作）。共 14
个方法，没有对应的 ``KeyFunction``（Java 端也没有 ``KeyFunction`` —— key
相关操作都是低层操作）。

所有与时间相关的参数单位均为**毫秒**（对齐 Java 的 ``PEXPIRE`` / ``PEXPIREAT``
语义，以及 cache-core ``KeyOps.get_expire`` 文档中“单位：毫秒”的说明）。

English
--------
Redis-backed `KeyOps` (M3.A).

Mirrors `cn.richie696.component.cache.redis.manage.RedisKeyManager`
1:1. Implements the low-level `KeyOps` Protocol (key lifecycle +
metadata + batch operations). 14 methods, no corresponding
`KeyFunction` (Java has no `KeyFunction` either — key operations
are all low-level).

All time-related parameters are in **milliseconds** (per Java's
`PEXPIRE` / `PEXPIREAT` semantics, and per the cache-core
`KeyOps.get_expire` doc which states "单位：毫秒").
"""

from __future__ import annotations

import time
from typing import Collection, Set

from atlas_richie.cache_core.enums.key_type_enum import KeyTypeEnum
from atlas_richie.cache_core.ops.key_ops import KeyOps

from .._perf_guard import RedisPerfGuard
from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from .redis_string_manager import _noop_cm


_TYPE_MAP: dict[str, KeyTypeEnum] = {
    "string": KeyTypeEnum.STRING,
    "hash": KeyTypeEnum.HASH,
    "list": KeyTypeEnum.LIST,
    "set": KeyTypeEnum.SET,
    # `zset` and `stream` are not in the cache-core enum (which
    # only covers the four primary data structures). They map to
    # `None` in `get_key_type`.
}


class RedisKeyManager(KeyOps):
    """Redis Key 操作管理器。
    ----
    Redis 后端的 key 管理器。

    English
    --------
    Redis-backed key manager.

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (currently unused; reserved
            for typed read plumbing if needed).
        perf: Optional `RedisPerfGuard` (R-M5.4). When provided
            AND enabled, the most-called metadata paths
            (`get_expire`, `set_expired_time`, `exists`, `delete`,
            `delete_many`) are timed via `time_op`. No payload /
            batch-size checks — key operations have neither
            payload nor meaningful batch size in this layer.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
        perf: RedisPerfGuard | None = None,
    ) -> None:
        self._backend = backend
        self._infra = infra
        self._perf = perf

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    # ── TTL ────────────────────────────────────────────────────────

    def get_expire(self, key: str) -> int:
        """获取指定 KEY 过期时间的方法。
        ----
        获取指定 KEY 的过期时间（单位：毫秒）。无过期返回 ``-1``，KEY
        不存在返回 ``-2``。

        English
        --------
        Return TTL in **milliseconds**. -1 if no expiry, -2 if missing.

        Args:
            key: 需要获取过期时间的 key。

        Returns:
            过期时间（单位：毫秒）。
        """
        with self._perf.time_op("get_expire") if self._perf is not None else _noop_cm():
            return int(self._backend.raw_client().pttl(self._k(key)))

    def set_expired_time(self, key: str, timeout: int) -> None:
        """设置对应缓存过期时间的方法。
        ----
        以毫秒为单位设置缓存的过期时间。

        English
        --------
        Set TTL in **milliseconds**.

        Args:
            key: 缓存键。
            timeout: 超时时间（单位：毫秒）。
        """
        self._backend.raw_client().pexpire(self._k(key), int(timeout))

    def persist(self, key: str) -> bool:
        """移除指定 key 的过期时间（执行后 KEY 将不再过期）。
        ----
        移除指定 KEY 的过期时间；执行后该 KEY 将不再过期。

        English
        --------
        Remove the TTL from the given key; after the call, the key
        will never expire.

        Args:
            key: 待移除过期时间的 KEY。

        Returns:
            移除结果。
        """
        return bool(self._backend.raw_client().persist(self._k(key)))

    def expire_at(self, key: str, timestamp: float) -> bool:
        """指定时间点设置过期时间的方法。
        ----
        在指定时间点为 KEY 设置过期时间。

        English
        --------
        `timestamp` is **epoch milliseconds** (Java `PEXPIREAT`).

        Args:
            key: 待设置过期时间的 KEY。
            timestamp: 过期的时间点（epoch 毫秒）。

        Returns:
            设置结果。
        """
        return bool(
            self._backend.raw_client().pexpireat(self._k(key), int(timestamp))
        )

    # ── Existence / type ───────────────────────────────────────────

    def has_key(self, key: str) -> bool:
        """检查指定的 Key 是否存在的方法。
        ----
        判断指定缓存 key 是否存在。

        English
        --------
        Return whether the given cache key exists.

        Args:
            key: 缓存键。

        Returns:
            检查结果。
        """
        return self._backend.exists(key)

    def get_key_type(self, key: str) -> KeyTypeEnum | None:
        """获取指定 Key 的类型的方法。
        ----
        获取指定 key 的 Redis 数据类型。

        English
        --------
        Return the Redis data type of the given key.

        Args:
            key: 需要获取类型的 key。

        Returns:
            Key 的类型枚举（``KeyTypeEnum``），如果 key 不存在或类型不支持
            则返回 ``None``。
        """
        raw = self._backend.raw_client().type(self._k(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        raw_lower = str(raw).lower()
        return _TYPE_MAP.get(raw_lower)

    def count_existing_keys(self, keys: Collection[str]) -> int:
        """获取匹配的 KEY 数量的方法。
        ----
        统计给定的 key 集合中实际存在的数量。

        English
        --------
        Return how many of the supplied keys currently exist.

        Args:
            keys: key 集合。

        Returns:
            匹配的 key 的个数。
        """
        if not keys:
            return 0
        if self._perf is not None:
            self._perf.check_batch_size("count_existing_keys", len(keys))
        with self._perf.time_op("count_existing_keys") if self._perf is not None else _noop_cm():
            return int(
                self._backend.raw_client().exists(*[self._k(k) for k in keys])
            )

    # ── Deletion ───────────────────────────────────────────────────

    def remove_cache(self, key: str) -> None:
        """根据 Key 删除指定元素的方法。
        ----
        删除指定 key（涵盖所有 Redis 数据类型：string、list、set、zset、
        hash、stream）。

        English
        --------
        Remove the element stored under the given key (covers all
        Redis data types: string, list, set, zset, hash, stream).

        Args:
            key: 列表名称（实际为任意 Redis key）。
        """
        with self._perf.time_op("remove_cache") if self._perf is not None else _noop_cm():
            self._backend.delete(key)

    def remove_cache_many(self, keys: Collection[str]) -> None:
        """根据 Key 列表删除指定元素的方法。
        ----
        批量删除给定的 key 列表（涵盖所有 Redis 数据类型）。

        English
        --------
        Remove the elements stored under the given keys (covers all
        Redis data types: string, list, set, zset, hash, stream).

        Args:
            keys: key 列表。
        """
        if not keys:
            return
        if self._perf is not None:
            self._perf.check_batch_size("remove_cache_many", len(keys))
        with self._perf.time_op("remove_cache_many") if self._perf is not None else _noop_cm():
            client = self._backend.raw_client()
            # Pipeline so the batch is one round-trip; not transactional.
            pipe = client.pipeline(transaction=False)
            for k in keys:
                pipe.delete(self._k(k))
            pipe.execute()

    # ── Rename / copy / move ──────────────────────────────────────

    def copy(self, source_key: str, target_key: str, replace: bool) -> bool:
        """合并两个数据集的方法。
        ----
        将源 key 的值复制到目标 key。

        English
        --------
        Copy the value of the source key into the target key.

        Args:
            source_key: 源 key。
            target_key: 目标 key。
            replace: 是否替换目标 key 的现有值。

        Returns:
            复制是否成功。
        """
        try:
            result = self._backend.raw_client().copy(
                self._k(source_key),
                self._k(target_key),
                replace=replace,
            )
        except Exception:
            # `redis-py` raises if the source doesn't exist or the
            # target exists without `replace`. Treat as a no-copy.
            return False
        return bool(result)

    def move(self, key: str, db_index: int) -> bool:
        """移动指定的 Key 到指定的数据库的方法。
        ----
        将指定 key 移动到另一个 Redis 逻辑数据库。

        English
        --------
        Move the given key to a different Redis logical database.

        Args:
            key: 需要移动的 KEY。
            db_index: 目标数据库索引。

        Returns:
            移动结果。
        """
        return bool(self._backend.raw_client().move(self._k(key), int(db_index)))

    def rename(self, old_key: str, new_key: str) -> None:
        """重命名 KEY 的方法。
        ----
        将 ``old_key`` 重命名为 ``new_key``。如果 ``old_key`` 不存在则抛出
        ``DataAccessException``。

        English
        --------
        Rename ``old_key`` to ``new_key``. Raises ``DataAccessException``
        if the source key does not exist.

        Args:
            old_key: 旧 KEY。
            new_key: 新 KEY。

        Raises:
            DataAccessException: 当访问的 ``old_key`` 不存在时抛出此异常。
        """
        self._backend.raw_client().rename(self._k(old_key), self._k(new_key))

    def rename_if_absent(self, old_key: str, new_key: str) -> bool:
        """仅当目标 KEY 不存在时才将指定 KEY 重命名为目标 KEY 的方法。
        ----
        仅当 ``new_key`` 不存在时才将 ``old_key`` 重命名为 ``new_key``。

        English
        --------
        Rename ``old_key`` to ``new_key`` only when the destination does
        not already exist.

        Args:
            old_key: 旧 KEY。
            new_key: 新 KEY。

        Returns:
            是否执行了重命名（true：已重命名，false：未重命名）。

        Raises:
            DataAccessException: 当访问的 ``old_key`` 不存在时抛出此异常。
        """
        return bool(
            self._backend.raw_client().renamenx(
                self._k(old_key), self._k(new_key)
            )
        )

    # ── Misc ───────────────────────────────────────────────────────

    def dump(self, key: str) -> bytes:
        """序列化 KEY 的方法。
        ----
        序列化指定 key 的当前值，返回可供 ``RESTORE`` 使用的字节序列。

        English
        --------
        Serialise the current value of the given key into the byte
        form accepted by ``RESTORE``.

        Args:
            key: 待序列化的 KEY。

        Returns:
            序列化后的 KEY 字节序列。

        Raises:
            DataAccessException: 当访问的 key 不存在时抛出此异常。
        """
        raw = self._backend.raw_client().dump(self._k(key))
        if raw is None:
            return b""
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return bytes(raw)

    def get_all_keys(self, key: str) -> Set[str]:
        """获取指定节点下的所有 KEY 的方法。
        ----
        按 pattern 匹配并返回所有 key（使用 SCAN 迭代）。

        按 cache-core 文档 “获取指定节点下的所有 KEY”：``key`` 参数被当作
        Redis 模式串（如 ``user:*``）。出于生产环境安全考虑使用 SCAN，
        而非 ``KEYS``。

        English
        --------
        Return all keys matching the pattern `key` (SCAN-iter based).

        Per the cache-core doc "获取指定节点下的所有KEY" — the `key`
        argument is treated as a Redis pattern (e.g. `user:*`). SCAN
        is used (not `KEYS`) for production safety.

        Args:
            key: 需要获取的某组 key 的父节点（实际是 Redis 模式串）。

        Returns:
            该父节点下的所有子节点 key。
        """
        out: Set[str] = set()
        prefix = f"{self._backend.namespace}:"
        for raw in self._backend.raw_client().scan_iter(
            match=self._k(key), count=200
        ):
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            if raw.startswith(prefix):
                out.add(raw[len(prefix):])
        return out


__all__ = ["RedisKeyManager"]
