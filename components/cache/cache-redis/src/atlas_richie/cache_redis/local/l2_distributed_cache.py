"""L2 DistributedCache (R-223) — two-tier cache-aside.

Mirrors `cn.richie696.component.cache.l2.L2DistributedCache` (Java).

**Architecture**:
    caller → L1 (process-local cachetools) → L2 (Redis) → loader (caller)

  - L1 hit: return immediately, no network.
  - L1 miss, L2 hit: copy to L1 (read-through), return.
  - Both miss: caller is responsible for loading from a downstream
    source (DB / API) and writing back via `set(...)`.

**L1 and L2 share the same TTL** so an expired L2 entry won't
silently live on in L1. The TTL is per-instance (set at construction).

**Per-region L1 sizing**: each `L2DistributedCache` instance owns a
`LocalCacheManager` configured with a per-region `CacheDefinition`
that pins `max_size` to the caller's request. This way the LRU
`max_size` budget is honored per-instance rather than the default
10_000.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from atlas_richie.cache_core.local.config.local_cache_properties import (
    CacheDefinition,
    LocalCacheProperties,
)
from atlas_richie.cache_core.local.enums.expiry_policy import ExpiryPolicy
from atlas_richie.cache_core.local.manage.local_cache_manager import (
    LocalCacheManager,
)

from ..managers.redis_string_manager import RedisStringManager


class L2DistributedCache:
    """Two-tier cache facade (L1 in-process + L2 Redis).

    Construction is intentionally cheap: the L1 bucket is a lazy
    `cachetools.LRUCache` and the L2 is just a reference to a
    `RedisStringManager`. Use ``L2CacheFactory`` (or
    ``RedisProviderRegistrar.l1(...)``) to obtain cached instances.
    """

    def __init__(
        self,
        value_ops: RedisStringManager,
        region: str,
        max_size: int = 10_000,
        ttl_seconds: int = 300,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._value_ops = value_ops
        self._region = region
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        # Per-instance LocalCacheManager with a per-region
        # `CacheDefinition` so the L1 budget matches the L2 cache's
        # `max_size` request.
        properties = LocalCacheProperties(
            cache_definitions={
                region: CacheDefinition(
                    expiry_policy=ExpiryPolicy.ACCESSED,
                    ttl_millis=ttl_seconds * 1000,
                    max_size=max_size,
                )
            }
        )
        self._local = LocalCacheManager(properties)
        self._hits = 0
        self._misses = 0
        self._stats_lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────

    def get(self, key: str) -> Optional[bytes]:
        """Look up a key. Returns the raw bytes, or `None` on miss."""
        # L1 first.
        l1_value = self._local.get(self._region, key)
        if l1_value is not None:
            with self._stats_lock:
                self._hits += 1
            return l1_value
        # L1 miss — try L2.
        with self._stats_lock:
            self._misses += 1
        l2_value = self._value_ops.get(key, bytes)
        if l2_value is None:
            return None
        # Read-through: copy L2 → L1.
        try:
            self._local.put(self._region, key, l2_value)
            self._local.expiry(self._region, key, self._ttl_seconds * 1000)
        except Exception:
            pass
        return l2_value

    def set(self, key: str, value: bytes, ttl_seconds: int = 0) -> None:
        """Set a key. `ttl_seconds=0` uses the instance default.

        Writes go to BOTH L1 and L2 synchronously. A L2 failure does
        not roll back L1 (callers that need strict consistency should
        invalidate L1 after a successful L2 write).
        """
        effective_ttl = ttl_seconds if ttl_seconds > 0 else self._ttl_seconds
        # L1 first (cheap, no network).
        try:
            self._local.put(self._region, key, value)
            self._local.expiry(self._region, key, effective_ttl * 1000)
        except Exception:
            pass
        # L2 (network).
        self._value_ops.set_with_ttl(key, value, effective_ttl * 1000)

    def delete(self, key: str) -> None:
        """Delete from BOTH L1 and L2."""
        try:
            self._local.remove(self._region, key)
        except Exception:
            pass
        # L2 delete: `value_ops` is the ValueOps Protocol and doesn't
        # expose `delete`; the Redis-side key manager owns the key-level
        # operations. We grab a fresh `key_ops` from the same backend.
        self._value_ops._backend.raw_client().delete(  # type: ignore[attr-defined]
            self._value_ops._k(key)  # type: ignore[attr-defined]
        )

    def invalidate_l1(self, key: str) -> None:
        """Delete from L1 only (force a fresh L2 read on the next get)."""
        try:
            self._local.remove(self._region, key)
        except Exception:
            pass

    def stats(self) -> Dict[str, int]:
        """Return a snapshot of L1 hit / miss counters and current
        L1 size. Useful for tuning and observability."""
        with self._stats_lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "l1_size": self._l1_size(),
                "max_size": self._max_size,
            }

    # ── Internal ─────────────────────────────────────────────────

    def _l1_size(self) -> int:
        """Best-effort L1 size — the local cache doesn't expose a
        `__len__` directly, so we walk the bucket's entries."""
        try:
            bucket = self._local._buckets[self._region]  # type: ignore[attr-defined]
            with bucket._lock:  # type: ignore[attr-defined]
                return len(bucket._entries)  # type: ignore[attr-defined]
        except (KeyError, AttributeError):
            return 0

    # ── Properties ───────────────────────────────────────────────

    @property
    def region(self) -> str:
        return self._region

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds


__all__ = ["L2DistributedCache"]
