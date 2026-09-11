"""分布式限流 API 管理器，封装了基于 Redis 的固定窗口计数器。
----
``LimiterOps`` 的 Redis 后端实现（M3.A）。

适用于接口防刷、限流、突发流量控制等场景。

镜像 ``cn.richie696.component.cache.redis.manage.RedisLimiterManager`` 的结构。
通过一个原子 Lua 脚本实现固定窗口限流器，在一次往返中完成 ``INCR`` +
``EXPIRE``。

Lua 脚本确保 EXPIRE 在新窗口的第一次请求时设置（``INCR`` 返回 1 时）。
若没有原子性，``INCR`` 与 ``EXPIRE`` 之间的崩溃会让计数器失去 TTL，
从而几乎永久拒绝该用户。

``try_acquire`` 检查（``current > max_count``）在脚本返回当前计数后于
Python 中进行。``current = max_count`` 与 ``current = max_count + 1``
之间的竞争由脚本中的原子 INCR 关闭；检查本身只是对返回值的单次读取，
不涉及多步竞争。

English
--------
Redis-backed `LimiterOps` (M3.A).

Mirrors `cn.richie696.component.cache.redis.manage.RedisLimiterManager`
1:1. Fixed-window rate limiter via an atomic Lua script that does
`INCR` + `EXPIRE` in a single round-trip.

The Lua script ensures the EXPIRE is set on the first request of a
new window (when `INCR` returns 1). Without atomicity, a crash
between `INCR` and `EXPIRE` would leave the counter without a TTL
and effectively deny the user forever.

The `try_acquire` check (`current > max_count`) happens in Python
after the script returns the current count. The race between
"current = max_count" and "current = max_count + 1" is closed by the
atomic INCR inside the script; the check itself is a single read of
the return value and is not subject to multi-step races.
"""

from __future__ import annotations

from atlas_richie.cache_core.ops.limiter_ops import LimiterOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache


# Atomic INCR + EXPIRE. Sets EXPIRE only on the first request of a
# new window (when INCR returns 1).
_LUA_TRY_ACQUIRE = """
local current = redis.call('INCR', KEYS[1])
if tonumber(current) == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RedisLimiterManager(LimiterOps):
    """Redis 后端的固定窗口限流器。
    ----
    基于 Lua 脚本的 ``INCR`` + ``EXPIRE`` 原子操作实现固定窗口限流。

    English
    --------
    Redis-backed fixed-window rate limiter.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra
        self._script_sha: str | None = None

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    def _load_script(self) -> str:
        """Load the Lua script and cache the SHA. `EVALSHA` is used
        on subsequent calls to avoid sending the script body
        repeatedly."""
        if self._script_sha is None:
            self._script_sha = self._backend.raw_client().script_load(
                _LUA_TRY_ACQUIRE
            )
        return self._script_sha

    def try_acquire(
        self, key: str, max_count: int, window_seconds: int
    ) -> bool:
        sha = self._load_script()
        try:
            current = self._backend.raw_client().evalsha(
                sha, 1, self._k(key), str(int(window_seconds))
            )
        except Exception:
            # `NOSCRIPT` etc. — reload and retry once.
            self._script_sha = None
            sha = self._load_script()
            current = self._backend.raw_client().evalsha(
                sha, 1, self._k(key), str(int(window_seconds))
            )
        return int(current) <= int(max_count)


__all__ = ["RedisLimiterManager"]
