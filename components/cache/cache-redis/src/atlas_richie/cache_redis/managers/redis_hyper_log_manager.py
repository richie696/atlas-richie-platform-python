"""HyperLogLog 相关 API 管理器，封装了 Redis 中 HyperLogLog 数据结构的常用操作。
----
``HyperLogOps`` + ``HyperLogFunction`` 的 Redis 后端实现（M3.B）。

主要用于大规模基数统计（如 UV、去重计数）等场景，具有极低内存消耗和
可接受误差。

镜像 ``cn.richie696.component.cache.redis.manage.RedisHyperLogManager`` 的结构。
同时实现底层 ``HyperLogOps`` Protocol 与高层 ``HyperLogFunction`` Protocol。
共 2 + 2 = 4 个方法，无冲突。

HyperLogLog 是一种用于基数估计的概率数据结构。标准误差约 0.81%。内存
开销恒定（每个 key 约 12 KB，与加入的不同元素数量无关）。不适用于需要
精确计数的场景。

English
--------
Redis-backed `HyperLogOps` + `HyperLogFunction` (M3.B).

Mirrors `cn.richie696.component.cache.redis.manage.RedisHyperLogManager`
1:1. Implements both the low-level `HyperLogOps` Protocol and the
high-level `HyperLogFunction` Protocol. 2 + 2 = 4 methods, no
collisions.

HyperLogLog is a probabilistic data structure for cardinality
estimation. Standard error ~0.81%. Memory cost is constant (12 KB
per key regardless of how many distinct elements are added). Not
suitable when exact counts are required.
"""

from __future__ import annotations

from typing import Any

from atlas_richie.cache_core.function.hyper_log_function import HyperLogFunction
from atlas_richie.cache_core.ops.hyper_log_ops import HyperLogOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import encode_value


class RedisHyperLogManager(HyperLogOps, HyperLogFunction):
    """HyperLogLog 相关 API 管理器，封装了 Redis 中 HyperLogLog 数据结构的常用操作。
    ----
    Redis 后端的 HyperLogLog 管理器。

    English
    --------
    Redis-backed HyperLogLog manager.
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

    def _enc(self, v: Any) -> str | bytes:
        if isinstance(v, (bytes, bytearray)):
            return bytes(v)
        if isinstance(v, str):
            return v
        return encode_value(v)

    def add(self, key: str, *values: Any) -> None:
        if not values:
            return
        self._backend.raw_client().pfadd(
            self._k(key), *[self._enc(v) for v in values]
        )

    def count(self, key: str) -> int:
        return int(self._backend.raw_client().pfcount(self._k(key)))

    def pf_add(self, key: str, *values: Any) -> None:
        self.add(key, *values)

    def pf_count(self, key: str) -> int:
        return self.count(key)


__all__ = ["RedisHyperLogManager"]
