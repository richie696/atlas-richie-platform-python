"""Lua 脚本原子操作 API 管理器，封装了 Redis 中 Lua 脚本的执行能力。
----
``ScriptOps`` 的 Redis 后端实现（M3.A）。

适用于复杂原子操作、分布式事务、批量处理等场景。

镜像 ``cn.richie696.component.cache.redis.manage.RedisScriptManager`` 的结构。
实现底层 ``ScriptOps`` Protocol（Lua 脚本执行）。共 2 个方法，没有对应的
function Protocol。

该管理器有意保持极简 —— 它是对 ``redis-py`` 的 ``eval`` 的薄封装。有界结构
（M3.C）和布隆过滤器（M4）使用 ScriptOps 运行各自的 Lua 脚本；该管理器
存在是为了让调用方可以通过标准的 ``ProviderRegistrar`` 流程访问 ``eval``，
而不是直接操作 redis 客户端。

English
--------
Redis-backed `ScriptOps` (M3.A).

Mirrors `cn.richie696.component.cache.redis.manage.RedisScriptManager`
1:1. Implements the low-level `ScriptOps` Protocol (Lua script
execution). 2 methods, no corresponding function Protocol.

This manager is intentionally minimal — it's a thin wrapper around
`redis-py`'s `eval`. Bounded structures (M3.C) and the Bloom filter
(M4) use the ScriptOps to run their Lua scripts; the manager exists
so callers can reach `eval` through the standard `ProviderRegistrar`
flow rather than poking the redis client directly.
"""

from __future__ import annotations

from typing import Any, List, TypeVar

from atlas_richie.cache_core.ops.script_ops import ScriptOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache

T = TypeVar("T")


class RedisScriptManager(ScriptOps):
    """Redis 后端的脚本管理器（``EVAL`` 的薄封装）。
    ----
    通过 ``redis-py`` 的 ``eval`` 方法执行 Lua 脚本。

    English
    --------
    Redis-backed script manager (thin wrapper around `EVAL`).
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

    def eval(
        self, script: str, keys: List[str], args: List[str], result_type: type
    ) -> Any:
        """Evaluate a Lua script.

        `redis-py`'s `eval` signature is `eval(script, numkeys, *keys_and_args)`.
        We unpack the `keys` list and `args` list into a flat args
        tuple so the namespaced-key prefix is applied to all KEYS[]
        references in the script.
        """
        namespaced = [self._k(k) for k in keys]
        raw = self._backend.raw_client().eval(
            script, len(namespaced), *namespaced, *args
        )
        return self._coerce(raw, result_type)

    def eval_single_key(
        self, script: str, key: str, args: List[str], result_type: type
    ) -> Any:
        namespaced = [self._k(key)]
        raw = self._backend.raw_client().eval(
            script, 1, *namespaced, *args
        )
        return self._coerce(raw, result_type)

    @staticmethod
    def _coerce(raw: Any, result_type: type) -> Any:
        """Best-effort type coercion for Lua return values.

        - `int` / `float` / `bool` / `str` / `bytes`: pass-through
          (after a quick cast when applicable).
        - `list` / `tuple` / `set`: collect per-element if the
          caller passed a generic collection type.
        - any other `type[T]`: pass through (caller is responsible
          for decoding).
        """
        if result_type is int and not isinstance(raw, bool):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return raw
        if result_type is float:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return raw
        if result_type is bool:
            return bool(raw)
        if result_type is str:
            return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if result_type is bytes:
            return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        return raw


__all__ = ["RedisScriptManager"]
