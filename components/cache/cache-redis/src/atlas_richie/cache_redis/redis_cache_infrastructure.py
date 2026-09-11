"""Redis 后端的 `CacheInfrastructure` 实现。
----
对位 Java 端 `cn.richie696.component.cache.ops.CacheInfrastructure`。
维护按 key 注册的 `type` 表，供 `ValueOps.get_typed` /
`FieldOps.get_typed` 在调用方不传 `clazz` 时反序列化。同时暴露
connection 描述用于诊断。

M1 阶段按 key 的类型注册表是简单的进程内 dict；M5 可能按需加
namespace-aware typing。

English
--------
CacheInfrastructure implementation for the Redis backend.

Mirrors `cn.richie696.component.cache.ops.CacheInfrastructure`. Holds
the per-key `type` registry used by `ValueOps.get_typed` /
`FieldOps.get_typed` to deserialise values without an explicit `clazz`
argument. Also exposes the connection descriptor for diagnostics.

For M1 the per-key type registry is a simple in-process dict; M5 may
add namespace-aware typing if needed.
"""

from __future__ import annotations

import threading
from typing import Optional

from atlas_richie.cache_core.enums.key_type_enum import KeyTypeEnum
from atlas_richie.cache_core.ops.cache_infrastructure import (
    CacheInfrastructure,
)

from .redis_distributed_cache import RedisDistributedCache


class RedisCacheInfrastructure(CacheInfrastructure):
    """Framework-internal infrastructure for the Redis backend.

    Thread-safe (single RLock). The active key → type registry is
    used by `ValueOps.get_typed` / `FieldOps.get_typed` /
    `HashFunction.get_from_hash_with_lock_typed` / etc. to deserialise
    when the caller does not pass an explicit `clazz`.

    L2 caching is **always enabled** in the Python translation
    (matches Java's default). Per-key-type switches are exposed but
    default to `True`; callers can opt out via `disable_key_type`.
    """

    def __init__(self, backend: RedisDistributedCache) -> None:
        self._backend = backend
        self._lock = threading.RLock()
        self._value_types: dict[str, type] = {}
        # Per KeyTypeEnum: which types have L2 caching enabled.
        self._l2_enabled: dict[KeyTypeEnum, bool] = dict.fromkeys(
            KeyTypeEnum, True
        )

    @property
    def backend(self) -> RedisDistributedCache:
        return self._backend

    # ── CacheInfrastructure interface ──────────────────────────────

    def get_connection_string(self) -> str:
        return self._backend.connection_string

    def enable_l2_caching(self) -> bool:
        return True

    def enable_key_type_cache(self, key_type: KeyTypeEnum) -> bool:
        with self._lock:
            return self._l2_enabled.get(key_type, True)

    def get_value_type(self, key: str) -> Optional[type]:
        with self._lock:
            return self._value_types.get(self._backend.make_key(key))

    def register_type(self, key: str, clazz: type) -> None:
        with self._lock:
            self._value_types[self._backend.make_key(key)] = clazz

    # ── Backend-only diagnostics (NOT in the protocol) ─────────────

    def disable_key_type(self, key_type: KeyTypeEnum) -> None:
        with self._lock:
            self._l2_enabled[key_type] = False

    def enable_key_type(self, key_type: KeyTypeEnum) -> None:
        with self._lock:
            self._l2_enabled[key_type] = True


__all__ = ["RedisCacheInfrastructure"]
