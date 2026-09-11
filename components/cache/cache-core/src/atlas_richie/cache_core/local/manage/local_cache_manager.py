"""本地缓存管理器。
----
本地缓存管理器，封装了 JCache（JSR-107）规范的本地缓存操作。
所有缓存操作均强制启用防御性拷贝，确保外部代码对缓存数据的修改不会影响缓存内容。
使用 Fury 序列化框架实现高性能深拷贝，兼容虚拟线程环境。

English
--------
Per-instance Holder for the process-local in-memory cache.

Mirrors `cn.richie696.component.cache.local.manage.LocalCacheManager`
**without** the JSR-107 contract. This is a Pythonic Holder: one
`_CacheBucket` per region name (`CacheName` or str), each backed by
`cachetools.LRUCache` plus manual expiry tracking so per-key TTL
overrides work cleanly across all `ExpiryPolicy` values.

Design choices:

- **LRUCache, not TTLCache**: `cachetools.TTLCache` does not support
  per-entry TTL overrides; we keep a single `LRUCache` per region and
  carry expiry metadata in `_expiries` (a parallel dict) for the four
  non-ETERNAL policies. Reads check expiry inline; expired entries
  are removed lazily on access. Eviction at max-size is automatic.
- **Defensive copy on every put/get**: prevents the caller from
  mutating the stored value and vice versa. Skip-copy for trivially
  immutable values (None, bool, int, float, str, bytes, complex,
  tuple/frozenset of immutable) keeps the fast path allocation-free.
- **One RLock per bucket**: the bucket is the natural contention
  scope; we don't need a process-wide lock. Every bucket method
  acquires the same RLock so callers can compose operations safely.
- **Lazy bucket creation**: a region's bucket is built on first use
  from `LocalCacheProperties.cache_definitions[name]` if present,
  else from the `default_*` properties. The manager holds a single
  `_buckets_lock` only for the lookup-or-create critical section.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import cachetools

from ..config.local_cache_properties import LocalCacheProperties
from ..enums.expiry_policy import ExpiryPolicy
from ..util.defensive_copy_utils import DefensiveCopyUtils
from .expiry_wrapper import ExpiryWrapper  # noqa: F401  (kept for downstream re-export)


class _CacheBucket:
    """Single-region (CacheName) cache bucket.

    Internal to `LocalCacheManager`. Holds one `cachetools.LRUCache`
    and a parallel expiry dict (when policy ≠ ETERNAL). Every public
    method is RLock-protected so callers can compose safely.
    """

    __slots__ = (
        "_policy",
        "_default_ttl_ms",
        "_max_size",
        "_lock",
        "_entries",
        "_expiries",
    )

    def __init__(
        self,
        policy: ExpiryPolicy,
        default_ttl_ms: int,
        max_size: int,
    ) -> None:
        self._policy = policy
        self._default_ttl_ms = int(default_ttl_ms)
        self._max_size = int(max_size)
        self._lock = threading.RLock()
        self._entries: cachetools.LRUCache = cachetools.LRUCache(maxsize=max_size)
        # None means ETERNAL (no expiry tracking); {} means tracked.
        self._expiries: Optional[Dict[str, int]] = (
            None if policy == ExpiryPolicy.ETERNAL else {}
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _now_millis() -> int:
        return int(time.time() * 1000)

    def _expire_at(self, ttl_ms: Optional[int]) -> int:
        """Compute the absolute expiry timestamp for a new entry.

        Returns 0 for ETERNAL policy; otherwise
        `now + (ttl_ms if ttl_ms is not None else self._default_ttl_ms)`.
        A 0/None `ttl_ms` falls back to the region default (the API
        contract is "no override ⇒ use default", not "no override ⇒
        immediate expiry"). Callers wanting explicit non-expiry can
        set the region's policy to ETERNAL.
        """
        if self._expiries is None:
            return 0
        ttl = ttl_ms if ttl_ms else self._default_ttl_ms
        return self._now_millis() + ttl

    def _is_expired(self, key: str) -> bool:
        if self._expiries is None:
            return False
        expire_at = self._expiries.get(key, 0)
        if expire_at > 0 and self._now_millis() >= expire_at:
            # Lazy expiry
            self._entries.pop(key, None)
            self._expiries.pop(key, None)
            return True
        return False

    def _set_entry(
        self, key: str, value: Any, ttl_ms: Optional[int]
    ) -> None:
        self._entries[key] = DefensiveCopyUtils.copy(value)
        if self._expiries is not None:
            self._expiries[key] = self._expire_at(ttl_ms)

    # ── Public API (RLock-protected) ───────────────────────────────

    def put(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> None:
        with self._lock:
            self._set_entry(key, value, ttl_ms)

    def get(self, key: str) -> Any:
        with self._lock:
            if key not in self._entries:
                return None
            if self._is_expired(key):
                return None
            return DefensiveCopyUtils.copy(self._entries[key])

    def contains_key(self, key: str) -> bool:
        with self._lock:
            if key not in self._entries:
                return False
            return not self._is_expired(key)

    def remove(self, key: str) -> bool:
        with self._lock:
            existed = key in self._entries
            self._entries.pop(key, None)
            if self._expiries is not None:
                self._expiries.pop(key, None)
            return existed

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            if self._expiries is not None:
                self._expiries.clear()
            return count

    def put_if_absent(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> bool:
        with self._lock:
            if key in self._entries and not self._is_expired(key):
                return False
            self._set_entry(key, value, ttl_ms)
            return True

    def replace(
        self, key: str, old_value: Any, new_value: Any
    ) -> bool:
        with self._lock:
            if key not in self._entries or self._is_expired(key):
                return False
            if self._entries[key] != old_value:
                return False
            self._entries[key] = DefensiveCopyUtils.copy(new_value)
            if self._expiries is not None:
                # Touch TTL on replace (MODIFIED semantics for free).
                self._expiries[key] = self._expire_at(None)
            return True

    def get_and_remove(self, key: str) -> Any:
        with self._lock:
            if key not in self._entries or self._is_expired(key):
                return None
            value = self._entries.pop(key)
            if self._expiries is not None:
                self._expiries.pop(key, None)
            return DefensiveCopyUtils.copy(value)

    def get_and_put(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> Any:
        with self._lock:
            old = self.get(key)
            self._set_entry(key, value, ttl_ms)
            return old

    def get_and_replace(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> Any:
        with self._lock:
            old = self.get(key)
            if old is not None or (
                key in self._entries and not self._is_expired(key)
            ):
                self._set_entry(key, value, ttl_ms)
            return old

    def get_all(self, keys: List[str]) -> Dict[str, Any]:
        with self._lock:
            return {
                k: v
                for k in keys
                if (v := self.get(k)) is not None or k in self._entries
            }

    def remove_all(self, keys: List[str]) -> int:
        with self._lock:
            count = 0
            for k in keys:
                if self.remove(k):
                    count += 1
            return count

    def pop_by_count(self, count: int) -> Dict[str, Any]:
        if count <= 0:
            return {}
        with self._lock:
            # cachetools.LRUCache iterates most-recently-used first;
            # the first `count` keys are the OLDEST — exactly what
            # "pop by count" should evict.
            keys = list(self._entries.keys())[:count]
            return {k: self.get_and_remove(k) for k in keys}

    def expiry(self, key: str, ttl_ms: int) -> None:
        """Update the TTL of an existing entry.

        If the entry doesn't exist, the call is a no-op (matches Java
        behaviour; the entry is not created).
        """
        with self._lock:
            if key not in self._entries or self._is_expired(key):
                return
            if self._expiries is not None:
                self._expiries[key] = self._now_millis() + ttl_ms

    def put_all(
        self,
        mapping: Dict[str, Any],
        ttl_ms: Optional[int] = None,
    ) -> None:
        with self._lock:
            for k, v in mapping.items():
                self._set_entry(k, v, ttl_ms)

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._entries.keys())

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


class LocalCacheManager:
    """本地缓存管理器实例。

    通过 `LocalCacheManager()` 使用默认设置；或传入 `LocalCacheProperties`
    覆盖默认值与每个 region 的自定义定义。

    线程安全：每个公共方法都会获取对应 bucket 的 RLock。
    管理器仅在 lookup-or-create 临界区内持有一把 `_buckets_lock`。

    English
    --------
    Per-instance Holder for the process-local in-memory cache.

    Construct via ``LocalCacheManager()`` for default settings, or
    pass a ``LocalCacheProperties`` to override defaults / per-region
    definitions.

    Thread-safe: every public method acquires the relevant bucket's
    RLock. The manager holds only a single ``_buckets_lock`` for the
    lookup-or-create critical section.
    """

    def __init__(self, properties: LocalCacheProperties | None = None) -> None:
        self._props = properties or LocalCacheProperties()
        self._buckets: Dict[str, _CacheBucket] = {}
        self._buckets_lock = threading.Lock()

    @property
    def properties(self) -> LocalCacheProperties:
        return self._props

    def _bucket(self, region: str) -> _CacheBucket:
        with self._buckets_lock:
            bucket = self._buckets.get(region)
            if bucket is None:
                override = self._props.cache_definitions.get(region)
                if override is not None:
                    policy = override.expiry_policy
                    ttl_ms = override.ttl_millis
                    max_size = override.max_size
                else:
                    policy = self._props.default_expiry_policy
                    ttl_ms = self._props.default_ttl_millis
                    max_size = self._props.default_max_size
                bucket = _CacheBucket(policy, ttl_ms, max_size)
                self._buckets[region] = bucket
            return bucket

    @staticmethod
    def _region_name(region: str | Any) -> str:
        """Normalise a region argument to its string name.

        Accepts a `CacheName` Protocol, a string, or any object that
        has a `get_cache()` callable returning a str. Anything else
        raises `TypeError` to surface misuse early.
        """
        if isinstance(region, str):
            return region
        get_cache = getattr(region, "get_cache", None)
        if callable(get_cache):
            result = get_cache()
            if not isinstance(result, str):
                raise TypeError(
                    f"CacheName.get_cache() must return str, got "
                    f"{type(result).__name__}"
                )
            return result
        raise TypeError(
            f"region must be str or CacheName, got {type(region).__name__}"
        )

    # ── Capability API ──────────────────────────────────────────────

    def put(self, region: str | Any, key: str, value: Any) -> None:
        self._bucket(self._region_name(region)).put(key, value)

    def put_with_ttl(
        self, region: str | Any, key: str, value: Any, ttl_millis: int
    ) -> None:
        self._bucket(self._region_name(region)).put(key, value, ttl_millis)

    def put_if_absent(
        self, region: str | Any, key: str, value: Any
    ) -> bool:
        return self._bucket(self._region_name(region)).put_if_absent(key, value)

    def put_if_absent_with_ttl(
        self,
        region: str | Any,
        key: str,
        value: Any,
        ttl_millis: int,
    ) -> bool:
        return (
            self._bucket(self._region_name(region))
            .put_if_absent(key, value, ttl_millis)
        )

    def get(self, region: str | Any, key: str) -> Any:
        return self._bucket(self._region_name(region)).get(key)

    def get_all(
        self, region: str | Any, keys: List[str]
    ) -> Dict[str, Any]:
        return self._bucket(self._region_name(region)).get_all(keys)

    def contains_key(self, region: str | Any, key: str) -> bool:
        return self._bucket(self._region_name(region)).contains_key(key)

    def remove(self, region: str | Any, key: str) -> bool:
        return self._bucket(self._region_name(region)).remove(key)

    def remove_keys(
        self, region: str | Any, keys: List[str]
    ) -> int:
        return self._bucket(self._region_name(region)).remove_all(keys)

    def clear_region(self, region: str | Any) -> int:
        """Remove all entries in a single region. Returns count removed."""
        return self._bucket(self._region_name(region)).clear()

    def replace(
        self,
        region: str | Any,
        key: str,
        old_value: Any,
        new_value: Any,
    ) -> bool:
        return (
            self._bucket(self._region_name(region))
            .replace(key, old_value, new_value)
        )

    def get_and_remove(self, region: str | Any, key: str) -> Any:
        return self._bucket(self._region_name(region)).get_and_remove(key)

    def get_and_put(
        self, region: str | Any, key: str, value: Any
    ) -> Any:
        return self._bucket(self._region_name(region)).get_and_put(key, value)

    def get_and_replace(
        self, region: str | Any, key: str, value: Any
    ) -> Any:
        return self._bucket(self._region_name(region)).get_and_replace(key, value)

    def pop_by_count(
        self, region: str | Any, count: int
    ) -> Dict[str, Any]:
        return self._bucket(self._region_name(region)).pop_by_count(count)

    def expiry(
        self, region: str | Any, key: str, ttl_millis: int
    ) -> None:
        self._bucket(self._region_name(region)).expiry(key, ttl_millis)

    def put_all(
        self,
        region: str | Any,
        mapping: Dict[str, Any],
        ttl_millis: int | None = None,
    ) -> None:
        self._bucket(self._region_name(region)).put_all(mapping, ttl_millis)

    def region_size(self, region: str | Any) -> int:
        return self._bucket(self._region_name(region)).size()

    def close(self) -> None:
        """Drop all regions. Idempotent."""
        with self._buckets_lock:
            for bucket in self._buckets.values():
                bucket.clear()
            self._buckets.clear()


__all__ = ["LocalCacheManager"]
