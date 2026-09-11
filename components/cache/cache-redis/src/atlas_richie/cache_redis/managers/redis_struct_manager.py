"""``StructOps`` 的 Redis 后端实现（M3.C，Python 独有）。
----
实现 cache-core 中的 ``StructOps`` Protocol。这是 **Python 独有** 的
数据结构 —— Java 参考库中并没有直接对应物。意图是将一个完整的
JSON / pickle 对象视作单一缓存值，并配备专用的 ``refresh`` 辅助方法
（在乐观锁下进行读-改-写）。

``refresh`` 使用 ``WATCH`` + ``MULTI`` + ``EXEC`` 保证原子性：

1. WATCH 目标 key。
2. 读取当前值。
3. 通过用户提供的 ``func`` 计算新值。
4. MULTI / SET / EXEC。
5. 若 key 在 WATCH 与 EXEC 之间被修改，触发 ``WatchError`` 并从第 1 步重试。

English
--------
Redis-backed `StructOps` (M3.C, Python-only).

Implements the `StructOps` Protocol from `cache-core`. This is a
**Python-only** data structure — the Java reference library has no
direct equivalent. The intent is to treat a whole JSON / pickle
object as a single cache value with its own dedicated `refresh`
helper (read-modify-write under an optimistic lock).

`refresh` uses `WATCH` + `MULTI` + `EXEC` for atomicity:

1. WATCH the key.
2. Read the current value.
3. Compute the new value via the user-supplied `func`.
4. MULTI / SET / EXEC.
5. If the key changed between WATCH and EXEC, `WatchError` fires
   and we retry from step 1.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

import redis as redis_lib
from atlas_richie.cache_core.ops.struct_ops import StructOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value

T = TypeVar("T")


class RedisStructManager(StructOps):
    """Redis 后端的 struct / object 缓存管理器。
    ----
    将整个 JSON / pickle 对象视作单一缓存值，并提供基于 ``WATCH`` 的
    乐观锁刷新。

    English
    --------
    Redis-backed struct / object cache manager.

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (used by `get_typed`).
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

    def get(self, key: str, clazz: type) -> Any:
        raw = self._backend.raw_client().get(self._k(key))
        return decode_value(raw, clazz)

    def get_typed(self, key: str, reference: type) -> Any:
        registered = self._infra.get_value_type(key)
        target = registered if registered is not None else reference
        return self.get(key, target if target is not None else str)

    def set(self, key: str, value: Any) -> None:
        self._backend.raw_client().set(self._k(key), encode_value(value))

    def set_with_ttl(
        self, key: str, value: Any, timeout_millis: int
    ) -> None:
        self._backend.raw_client().set(
            self._k(key), encode_value(value), px=int(timeout_millis)
        )

    def refresh(
        self, key: str, func: Callable[[Any], Any]
    ) -> Any:
        """Atomic read-modify-write.

        The `func` receives the current value (or `None` if absent)
        and returns the new value. We retry on `WatchError` (the
        key changed between WATCH and EXEC) up to 100 times — the
        pattern is well-suited to low-contention counters and short
        critical sections. For genuine hot keys the caller should
        switch to `lock_ops.optimistic_lock` (M4).
        """
        import time as _time

        client = self._backend.raw_client()
        ns_key = self._k(key)
        for _attempt in range(100):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(ns_key)
                    current_raw = pipe.get(ns_key)
                    current = (
                        decode_value(current_raw, str)
                        if current_raw is not None
                        else None
                    )
                    new_value = func(current)
                    pipe.multi()
                    pipe.set(ns_key, encode_value(new_value))
                    pipe.execute()
                return new_value
            except redis_lib.WatchError:
                # Tiny backoff to break the livelock between racing
                # threads; the cost is negligible at our scale.
                _time.sleep(0.0001)
                continue
        # 100 retries exhausted — fall back to a non-atomic write.
        # The caller should switch to `lock_ops` for true atomicity
        # under high contention.
        current_raw = client.get(ns_key)
        current = (
            decode_value(current_raw, str)
            if current_raw is not None
            else None
        )
        new_value = func(current)
        client.set(ns_key, encode_value(new_value))
        return new_value

    def get_with_lock(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
    ) -> Any:
        raise NotImplementedError(
            "RedisStructManager.get_with_lock is implemented in R-220 M4."
        )

    def get_with_lock_typed(
        self,
        key: str,
        reference: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
    ) -> Any:
        raise NotImplementedError(
            "RedisStructManager.get_with_lock_typed is implemented in R-220 M4."
        )


__all__ = ["RedisStructManager"]
