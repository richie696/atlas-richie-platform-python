"""L2 缓存工厂（R-223）— 按 `(max_size, ttl_seconds)` 缓存 `L2DistributedCache` 实例。
----
对位 Java 端行为：相同配置返回相同实例（`cache.l1()` 始终是同一个
默认配置实例），不同配置返回不同实例（`cache.l1(max_size=2)` 是
另一个 per-config 实例）。

线程安全：内置 `Lock` 保护 `_instances` dict；并发首次创建同一配置
只会真正构造一次。

English
--------
L2 cache factory (R-223) — caches `L2DistributedCache` instances
per `(max_size, ttl_seconds)` combo.

Mirrors the Java side's behavior: `cache.l1()` returns the same
default-configured `L2DistributedCache` instance every time, while
`cache.l1(max_size=2)` returns a different (per-config) one.
"""

from __future__ import annotations

import threading
from typing import Dict, Tuple

from .l2_distributed_cache import L2DistributedCache


class L2CacheFactory:
    """Caches `L2DistributedCache` instances per configuration key.

    The cache key is `(max_size, ttl_seconds)`. The first call with
    a given config creates the instance; subsequent calls with the
    same config return the same instance. This matches the legacy
    `cache.l1()` behavior where the same configuration maps to the
    same cache.
    """

    def __init__(self, default_region: str = "default") -> None:
        self._default_region = default_region
        self._instances: Dict[
            Tuple[int, int], L2DistributedCache
        ] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        value_ops,
        max_size: int = 10_000,
        ttl_seconds: int = 300,
        region: str | None = None,
    ) -> L2DistributedCache:
        """Return the cached `L2DistributedCache` for the given
        configuration, creating it on first call."""
        key = (max_size, ttl_seconds)
        with self._lock:
            cache = self._instances.get(key)
            if cache is not None:
                return cache
            cache = L2DistributedCache(
                value_ops=value_ops,
                region=region or self._default_region,
                max_size=max_size,
                ttl_seconds=ttl_seconds,
            )
            self._instances[key] = cache
            return cache

    def clear(self) -> None:
        """Drop all cached instances. Useful for tests."""
        with self._lock:
            self._instances.clear()


__all__ = ["L2CacheFactory"]
