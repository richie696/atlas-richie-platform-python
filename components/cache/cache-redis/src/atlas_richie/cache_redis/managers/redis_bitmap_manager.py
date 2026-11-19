"""Redis-backed `BitmapOps` + `BitmapFunction` (M3.B).

Mirrors `cn.richie696.component.cache.redis.manage.RedisBitmapManager`
1:1. Implements both the low-level `BitmapOps` Protocol and the
high-level `BitmapFunction` Protocol. 2 + 2 = 4 methods, no
collisions.

Bitmaps are an efficient way to store boolean values indexed by
integer offset. Useful for:

- Daily-active-user / monthly-active-user flags.
- Bloom-filter-like markers (without the hash).
- Feature toggles.

`SETBIT` / `GETBIT` operate on a single bit at a 0-based offset;
`BITCOUNT` / `BITOP` are not in the cache-core Protocol but are
available via the raw `redis-py` client when needed.
"""

from __future__ import annotations

from atlas_richie.cache_core.function.bitmap_function import BitmapFunction
from atlas_richie.cache_core.ops.bitmap_ops import BitmapOps

from ..perf import RedisOperationCatalog, RedisPerfGuard
from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache


class RedisBitmapManager(BitmapOps, BitmapFunction):
    """Redis-backed Bitmap manager."""

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

    def set(self, key: str, offset: int, value: bool) -> None:
        self._backend.raw_client().setbit(
            self._k(key), int(offset), 1 if value else 0
        )

    def get(self, key: str, offset: int) -> bool:
        return bool(
            self._backend.raw_client().getbit(self._k(key), int(offset))
        )

    def set_bit(self, key: str, offset: int, value: bool) -> None:
        if self._perf is not None:
            self._perf.check_operation_tier(
                "set_bit", RedisOperationCatalog.BIT_OP
            )
        self.set(key, offset, value)

    def get_bit(self, key: str, offset: int) -> bool:
        if self._perf is not None:
            self._perf.check_operation_tier(
                "get_bit", RedisOperationCatalog.BIT_OP
            )
        return self.get(key, offset)


__all__ = ["RedisBitmapManager"]
