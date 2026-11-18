"""租户信息提供者 SPI 与缓存（对位 Java `TenantInfoProvider` /
`CachingTenantInfoProvider` / `NoOpTenantInfoProvider`）。

缓存采用访问时惰性过期（Java 用后台 janitor 线程）：少一个常驻线程，
过期条目在下次访问或 size() 时清理，语义等价。ttl<=0 关闭缓存直透 delegate。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Protocol, runtime_checkable

from .model import TenantInfo


@runtime_checkable
class TenantInfoProvider(Protocol):
    def get_tenant_info(self, tenant_id: int) -> TenantInfo | None: ...

    def exists(self, tenant_id: int) -> bool: ...


class NoOpTenantInfoProvider:
    """Always absent — for single-tenant deployments or tests."""

    def get_tenant_info(self, tenant_id: int) -> TenantInfo | None:
        return None

    def exists(self, tenant_id: int) -> bool:
        return False


class CachingTenantInfoProvider:
    def __init__(
        self,
        delegate: TenantInfoProvider,
        ttl_seconds: float,
        max_size: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if delegate is None:
            raise ValueError("delegate must not be None")
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._delegate = delegate
        self._ttl = ttl_seconds if ttl_seconds > 0 else 0.0
        self._max_size = max_size
        self._clock = clock
        self._cache: dict[int, tuple[float, TenantInfo | None]] = {}
        self._lock = threading.Lock()

    @property
    def caching_enabled(self) -> bool:
        return self._ttl > 0

    def get_tenant_info(self, tenant_id: int) -> TenantInfo | None:
        if not self.caching_enabled:
            return self._delegate.get_tenant_info(tenant_id)
        now = self._clock()
        with self._lock:
            entry = self._cache.get(tenant_id)
            if entry is not None and now - entry[0] <= self._ttl:
                return entry[1]
        info = self._delegate.get_tenant_info(tenant_id)
        with self._lock:
            self._evict_if_full()
            self._cache[tenant_id] = (self._clock(), info)
        return info

    def exists(self, tenant_id: int) -> bool:
        return self.get_tenant_info(tenant_id) is not None

    def invalidate(self, tenant_id: int) -> None:
        with self._lock:
            self._cache.pop(tenant_id, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        now = self._clock()
        with self._lock:
            self._cache = {
                k: v for k, v in self._cache.items() if now - v[0] <= self._ttl
            }
            return len(self._cache)

    def _evict_if_full(self) -> None:
        if len(self._cache) < self._max_size:
            return
        oldest = min(self._cache, key=lambda k: self._cache[k][0])
        del self._cache[oldest]


__all__ = ["TenantInfoProvider", "NoOpTenantInfoProvider", "CachingTenantInfoProvider"]