"""本地缓存管理器。
----
本地缓存管理器，封装了 JCache（JSR-107）规范的本地缓存操作。

English
--------
Per-instance Holder for the process-local in-memory cache.

Mirrors `cn.richie696.component.cache.local.manage.LocalCacheManager`
as a Pythonic Holder rather than a full JCache implementation: one
`_CacheBucket` per region name (`CacheName` or str), each backed by
`cachetools.LRUCache` plus manual expiry tracking.

Expiry follows the JSR-107 policy semantics that the Java side gets from
its JCache `ExpiryPolicy` factories:

| policy   | create | access (read) | update (write) |
|----------|--------|---------------|----------------|
| CREATED  | set    | unchanged     | unchanged      |
| ACCESSED | set    | reset         | unchanged      |
| MODIFIED | set    | unchanged     | reset          |
| TOUCHED  | set    | reset         | reset          |
| ETERNAL  | never expires                           |

`contains_key` is not an access event. A per-key TTL override is remembered
in `_ttls` so a refresh reuses it instead of the region default, and an
explicit `ttl_ms` on a write always applies.

L1 capabilities (mirroring the JSR-107 `MutableConfiguration` switches the
Java side sets from `CacheDefinition`):

- **statistics** (`statistics_enabled`) — cumulative hit / miss / put /
  removal counters, exposed via `LocalCacheManager.stats(region)`.
  Counters are only maintained when the flag is on.
- **store by value** (`store_by_value`) — defensive copy on put *and* get.
  Off means the stored object is shared with the caller (Java semantics).
- **read-through** (`read_through`) — on a miss, a registered loader is
  asked for the value and the result is cached. Concurrent misses for
  the same key collapse into one load.
- **write-through** (`write_through`) — mutations are pushed to a
  registered writer *after* the cache is updated (JSR-107 ordering).
- **refresh-ahead** (`refresh_ahead`) — entries close to expiry are
  refreshed in the background through the read-through loader, so a hot
  key does not pay a source round-trip at the moment it expires.

Design choices:

- **LRUCache, not TTLCache**: `cachetools.TTLCache` does not support
  per-entry TTL overrides; we keep a single `LRUCache` per region and
  carry expiry metadata in `_expiries` (a parallel dict) for the four
  non-ETERNAL policies. Reads check expiry inline; expired entries
  are removed lazily on access, and eagerly by `size()`/`keys()` so
  those report live counts. Capacity eviction goes through
  `_PruningLRUCache.popitem`, which drops the evicted key metadata —
  without that hook the parallel dicts would grow without bound.
- **Defensive copy on every put/get**: prevents the caller from
  mutating the stored value and vice versa. Skip-copy for trivially
  immutable values (None, bool, int, float, str, bytes, complex,
  tuple/frozenset of immutable) keeps the fast path allocation-free.
  This is the `store_by_value` behaviour, and it is the default here.
- **One RLock per bucket**: the bucket is the natural contention
  scope; we do not need a process-wide lock. Every bucket method
  acquires the same RLock so callers can compose operations safely.
- **Lazy bucket creation**: a region bucket is built on first use
  from `LocalCacheProperties.cache_definitions[name]` if present,
  else from the `default_*` properties. The manager holds a single
  `_buckets_lock` only for the lookup-or-create critical section.
- **Loaders and writers are registered, not configured by name**: the
  Java side wires them through `CacheDefinition.cacheLoaderClassName`
  (a class-path string) plus a reflection factory; Python has no such
  idiom, so `register_loader` / `register_writer` take callables.
"""

from __future__ import annotations

import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import cachetools

from ..config.local_cache_properties import LocalCacheProperties
from ..enums.expiry_policy import ExpiryPolicy
from ..util.defensive_copy_utils import DefensiveCopyUtils
from .cache_loader import CacheLoader, as_cache_loader
from .cache_statistics import CacheStatistics
from .cache_writer import CacheWriter, as_cache_writer
from .expiry_wrapper import ExpiryWrapper  # noqa: F401  (kept for downstream re-export)


#: Counter names kept in each bucket statistics dictionary.
_STAT_NAMES = (
    "hits",
    "misses",
    "gets",
    "puts",
    "removals",
    "expirations",
    "evictions",
)


class _PruningLRUCache(cachetools.LRUCache):
    """LRUCache that reports evictions so parallel metadata stays bounded.

    `cachetools.LRUCache` iterates in *insertion* order, not LRU order, and
    exposes no eviction callback. Both matter here: expiry metadata lives in
    parallel dicts, so a silent capacity eviction would leak them forever.
    `popitem()` does evict the true least-recently-used entry, and
    `__setitem__` routes capacity eviction through it, so overriding it is
    enough to catch every eviction path.
    """

    def __init__(self, maxsize: int, on_evict: Any) -> None:
        super().__init__(maxsize=maxsize)
        self._on_evict = on_evict

    def popitem(self) -> tuple:
        key, value = super().popitem()
        self._on_evict(key)
        return key, value


class _KeyLock:
    """Weakly-referenceable holder around a per-key `threading.Lock`.

    The lock itself cannot be weakly referenced, so it lives inside this
    wrapper; the wrapper is kept in a `WeakValueDictionary` and therefore
    disappears once no thread holds it. Same pattern as the L2 facade.
    """

    __slots__ = ("lock", "__weakref__")

    def __init__(self) -> None:
        self.lock = threading.Lock()


class _CacheBucket:
    """Single-region (CacheName) cache bucket.

    Internal to `LocalCacheManager`. Holds one `cachetools.LRUCache` plus
    parallel expiry metadata. Under ETERNAL no deadline is written on create
    or access, but an explicit `expiry()` call still applies — matching the
    Java `setExpiry`, which wraps the value in an `ExpiryWrapper` regardless
    of policy. Every public method is RLock-protected so callers can compose.
    """

    __slots__ = (
        "_policy",
        "_default_ttl_ms",
        "_max_size",
        "_lock",
        "_entries",
        "_expiries",
        "_ttls",
        "_statistics_enabled",
        "_store_by_value",
        "_read_through",
        "_write_through",
        "_refresh_ahead",
        "_refresh_ahead_ratio",
        "_loader",
        "_writer",
        "_stats",
        "_load_locks",
        "_refreshing",
        "_explicit_pop_depth",
    )

    def __init__(
        self,
        policy: ExpiryPolicy,
        default_ttl_ms: int,
        max_size: int,
        *,
        statistics_enabled: bool = False,
        store_by_value: bool = True,
        read_through: bool = False,
        write_through: bool = False,
        refresh_ahead: bool = False,
        refresh_ahead_ratio: float = 0.1,
    ) -> None:
        self._policy = policy
        self._default_ttl_ms = int(default_ttl_ms)
        self._max_size = int(max_size)
        self._lock = threading.RLock()
        self._entries: cachetools.LRUCache = _PruningLRUCache(
            max_size, self._on_capacity_evict
        )
        self._expiries: Dict[str, int] = {}
        # Effective per-key TTL, so an ACCESSED/TOUCHED refresh reuses the duration
        # the entry was created with instead of falling back to the region default
        # and silently discarding a per-key override.
        self._ttls: Dict[str, int] = {}
        self._statistics_enabled = bool(statistics_enabled)
        self._store_by_value = bool(store_by_value)
        self._read_through = bool(read_through)
        self._write_through = bool(write_through)
        self._refresh_ahead = bool(refresh_ahead)
        self._refresh_ahead_ratio = float(refresh_ahead_ratio)
        self._loader: CacheLoader | None = None
        self._writer: CacheWriter | None = None
        self._stats: Dict[str, int] = {name: 0 for name in _STAT_NAMES}
        # Per-key load locks, so concurrent read-through misses for one key
        # collapse into a single source load.
        self._load_locks: "weakref.WeakValueDictionary[str, _KeyLock]" = (
            weakref.WeakValueDictionary()
        )
        # Keys with a refresh-ahead load already in flight.
        self._refreshing: set[str] = set()
        # >0 while an explicit pop_by_count() is draining the LRU order.
        # Capacity eviction and explicit removal both go through
        # LRUCache.popitem(), so this flag is what keeps the "eviction"
        # counter reserved for capacity pressure only.
        self._explicit_pop_depth = 0

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _now_millis() -> int:
        return int(time.time() * 1000)

    def _count(self, name: str, delta: int = 1) -> None:
        """Bump a counter — only when statistics are enabled."""
        if self._statistics_enabled:
            self._stats[name] += delta

    def _on_capacity_evict(self, key: str) -> None:
        """Capacity eviction hook: count it and drop the key metadata.

        `pop_by_count()` drains the same LRU order through
        `LRUCache.popitem()`, but an explicit removal is not a capacity
        eviction — it is counted as a removal instead. The depth flag
        tells the two apart.
        """
        if self._explicit_pop_depth == 0:
            self._count("evictions")
        self._forget(key)

    def _forget(self, key: str) -> None:
        """Drop expiry metadata for a key that is no longer stored."""
        self._expiries.pop(key, None)
        self._ttls.pop(key, None)

    def _copy_out(self, value: Any) -> Any:
        """Hand a stored value to the caller, honouring store-by-value."""
        if self._store_by_value:
            return DefensiveCopyUtils.copy(value)
        return value

    def _copy_in(self, value: Any) -> Any:
        """Take a value from the caller, honouring store-by-value."""
        if self._store_by_value:
            return DefensiveCopyUtils.copy(value)
        return value

    def _reap_expired(self) -> None:
        """Eagerly drop expired entries so size()/keys() report live counts."""
        now = self._now_millis()
        for key, expire_at in list(self._expiries.items()):
            if expire_at > 0 and now >= expire_at:
                self._entries.pop(key, None)
                self._forget(key)
                self._count("expirations")

    def _is_expired(self, key: str) -> bool:
        expire_at = self._expiries.get(key, 0)
        if expire_at > 0 and self._now_millis() >= expire_at:
            # Lazy expiry
            self._entries.pop(key, None)
            self._forget(key)
            self._count("expirations")
            return True
        return False

    def _set_entry(
        self, key: str, value: Any, ttl_ms: Optional[int]
    ) -> None:
        """Write an entry, applying the JSR-107 expiry policy.

        Creation always sets the deadline. An update refreshes it only under
        MODIFIED / TOUCHED; under CREATED / ACCESSED the existing deadline is
        kept, matching `CreatedExpiryPolicy` / `AccessedExpiryPolicy`, whose
        `getExpiryForUpdate` leaves expiry unchanged. An explicit `ttl_ms` is a
        caller instruction and always applies.

        ETERNAL writes no deadline at all, so only `expiry()` can expire an
        entry in such a region.

        A 0/None `ttl_ms` means "use the region default", NOT "expire
        immediately"; callers wanting non-expiry set the policy to ETERNAL.
        """
        is_update = key in self._entries and not self._is_expired(key)
        self._entries[key] = self._copy_in(value)
        if self._policy is ExpiryPolicy.ETERNAL:
            return
        ttl = ttl_ms if ttl_ms else self._default_ttl_ms
        if ttl_ms or not is_update:
            self._ttls[key] = ttl
            self._expiries[key] = self._now_millis() + ttl
        elif self._policy in (ExpiryPolicy.MODIFIED, ExpiryPolicy.TOUCHED):
            self._expiries[key] = self._now_millis() + self._ttls.get(key, ttl)

    def _peek(self, key: str) -> Any:
        """Read a value without triggering the read-through loader.

        JSR-107 only invokes the CacheLoader from `get` / `getAll`.
        The atomic get-and-modify operations (`getAndPut`,
        `getAndReplace`) must not fire a source load as a side effect,
        so they read through this path instead of `get`.

        English
        --------
        Read a value without triggering the read-through loader.
        """
        with self._lock:
            if key in self._entries and not self._is_expired(key):
                self._touch_access(key)
                return self._copy_out(self._entries[key])
            return None

    def _touch_access(self, key: str) -> None:
        """JSR-107 access event: ACCESSED and TOUCHED reset the deadline."""
        if self._policy in (ExpiryPolicy.ACCESSED, ExpiryPolicy.TOUCHED):
            self._expiries[key] = self._now_millis() + self._ttls.get(
                key, self._default_ttl_ms
            )

    # ── Strategy wiring ─────────────────────────────────────────────

    def set_loader(self, loader: CacheLoader | None) -> None:
        """Attach (or detach) the read-through loader."""
        with self._lock:
            self._loader = loader

    def set_writer(self, writer: CacheWriter | None) -> None:
        """Attach (or detach) the write-through writer."""
        with self._lock:
            self._writer = writer

    @property
    def refresh_enabled(self) -> bool:
        return self._refresh_ahead

    # ── Write-through helpers ───────────────────────────────────────

    def _notify_write(self, key: str, value: Any) -> None:
        """Push a new value to the source of truth (cache already updated)."""
        if not self._write_through:
            return
        writer = self._writer
        if writer is None:
            return
        writer.write(key, value)

    def _notify_delete(self, key: str) -> None:
        """Push a deletion to the source of truth (cache already updated)."""
        if not self._write_through:
            return
        writer = self._writer
        if writer is None:
            return
        writer.delete(key)

    # ── Read-through helpers ────────────────────────────────────────

    def _load_lock_for(self, key: str) -> _KeyLock:
        """Per-key load lock; concurrent misses for one key collapse."""
        with self._lock:
            holder = self._load_locks.get(key)
            if holder is None:
                holder = _KeyLock()
                self._load_locks[key] = holder
            return holder

    def _load_through(self, key: str) -> Any:
        """Fetch `key` from the source of truth, one loader call per key."""
        loader = self._loader
        if loader is None:
            return None
        holder = self._load_lock_for(key)
        with holder.lock:
            # Another thread may have populated the entry meanwhile.
            with self._lock:
                if key in self._entries and not self._is_expired(key):
                    return self._entries[key]
            return loader.load(key)

    # ── Refresh-ahead helpers ───────────────────────────────────────

    def refresh_candidates(self) -> List[tuple]:
        """Keys whose remaining lifetime dropped below the refresh ratio.

        Returns ``(key, ttl_millis)`` pairs — the TTL is the *duration*
        the entry was created with, so a refresh extends the entry by the
        same amount instead of shortening it.

        Refresh-ahead requires read-through to be enabled, matching the
        Java rule that the refresh-ahead switch only takes effect
        together with readThrough=true and a loader.
        """
        if not self._refresh_ahead or not self._read_through:
            return []
        now = self._now_millis()
        candidates: List[tuple] = []
        with self._lock:
            for key, expire_at in list(self._expiries.items()):
                if expire_at <= 0:
                    continue
                remaining = expire_at - now
                if remaining <= 0:
                    # Already expired — a normal read will reload it.
                    continue
                ttl = self._ttls.get(key, self._default_ttl_ms)
                if ttl > 0 and remaining <= ttl * self._refresh_ahead_ratio:
                    candidates.append((key, ttl))
        return candidates

    def mark_refreshing(self, key: str) -> bool:
        """Claim the refresh slot for `key`; False if one is already running."""
        with self._lock:
            if key in self._refreshing:
                return False
            self._refreshing.add(key)
            return True

    def unmark_refreshing(self, key: str) -> None:
        """Release the refresh slot for `key`."""
        with self._lock:
            self._refreshing.discard(key)

    def refresh(self, key: str, ttl_ms: int) -> bool:
        """Reload `key` through the loader and store the fresh value.

        Returns True when a new value was stored. The entry keeps its
        original TTL *duration*, so a refresh slides the expiry forward
        instead of shortening the entry.
        """
        loader = self._loader
        if loader is None:
            return False
        value = loader.load(key)
        if value is None:
            return False
        with self._lock:
            # The entry may have been removed or replaced meanwhile.
            if key not in self._entries or self._is_expired(key):
                return False
            self._set_entry(key, value, ttl_ms)
            return True

    # ── Public API (RLock-protected) ───────────────────────────────

    def put(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> None:
        with self._lock:
            self._set_entry(key, value, ttl_ms)
            self._count("puts")
        self._notify_write(key, value)

    def get(self, key: str) -> Any:
        with self._lock:
            self._count("gets")
            if key in self._entries and not self._is_expired(key):
                self._touch_access(key)
                self._count("hits")
                return self._copy_out(self._entries[key])
            self._count("misses")
        if not self._read_through or self._loader is None:
            return None
        # Load outside the bucket lock: a slow source must not block the
        # whole region.
        value = self._load_through(key)
        if value is None:
            return None
        with self._lock:
            # Another thread may have populated the entry meanwhile;
            # do not overwrite it with a second, possibly older, value.
            if key not in self._entries:
                self._set_entry(key, value, None)
                self._count("puts")
        return self._copy_out(value)

    def contains_key(self, key: str) -> bool:
        with self._lock:
            if key not in self._entries:
                return False
            return not self._is_expired(key)

    def remove(self, key: str) -> bool:
        with self._lock:
            existed = key in self._entries
            self._entries.pop(key, None)
            self._forget(key)
            if existed:
                self._count("removals")
        if existed:
            self._notify_delete(key)
        return existed

    def clear(self, notify: bool = True) -> int:
        """Drop every entry in the region; returns how many were removed.

        With write-through enabled the deletions are pushed to the
        writer, matching JSR-107 (a `clear()` removes the entries from
        the source of truth as well). `notify=False` suppresses that
        propagation — used when the manager is shutting down, where the
        source of truth must not be wiped as a side effect.
        """
        with self._lock:
            count = len(self._entries)
            keys = list(self._entries.keys())
            self._entries.clear()
            self._expiries.clear()
            self._ttls.clear()
            self._count("removals", count)
        if notify:
            for key in keys:
                self._notify_delete(key)
        return count

    def put_if_absent(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> bool:
        with self._lock:
            if key in self._entries and not self._is_expired(key):
                return False
            self._set_entry(key, value, ttl_ms)
            self._count("puts")
        self._notify_write(key, value)
        return True

    def replace(
        self, key: str, old_value: Any, new_value: Any
    ) -> bool:
        with self._lock:
            if key not in self._entries or self._is_expired(key):
                return False
            if self._entries[key] != old_value:
                return False
            self._entries[key] = self._copy_in(new_value)
            # JSR-107: only MODIFIED / TOUCHED reset expiry on update.
            if self._policy in (ExpiryPolicy.MODIFIED, ExpiryPolicy.TOUCHED):
                self._expiries[key] = self._now_millis() + self._ttls.get(
                    key, self._default_ttl_ms
                )
            self._count("puts")
        self._notify_write(key, new_value)
        return True

    def get_and_remove(self, key: str) -> Any:
        with self._lock:
            if key not in self._entries or self._is_expired(key):
                return None
            value = self._entries.pop(key)
            self._forget(key)
            self._count("removals")
            result = self._copy_out(value)
        self._notify_delete(key)
        return result

    def get_and_put(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> Any:
        with self._lock:
            old = self._peek(key)
            self._set_entry(key, value, ttl_ms)
            self._count("puts")
        self._notify_write(key, value)
        return old

    def get_and_replace(
        self, key: str, value: Any, ttl_ms: Optional[int] = None
    ) -> Any:
        with self._lock:
            old = self._peek(key)
            replaced = False
            if old is not None or (
                key in self._entries and not self._is_expired(key)
            ):
                self._set_entry(key, value, ttl_ms)
                self._count("puts")
                replaced = True
        if replaced:
            self._notify_write(key, value)
        return old

    def get_all(self, keys: List[str]) -> Dict[str, Any]:
        with self._lock:
            result: Dict[str, Any] = {}
            missing: List[str] = []
            for key in keys:
                self._count("gets")
                if key in self._entries and not self._is_expired(key):
                    self._touch_access(key)
                    self._count("hits")
                    result[key] = self._copy_out(self._entries[key])
                else:
                    self._count("misses")
                    missing.append(key)
        if missing and self._read_through and self._loader is not None:
            loader = self._loader
            for key, value in loader.load_all(missing).items():
                if value is None:
                    continue
                with self._lock:
                    self._set_entry(key, value, None)
                    self._count("puts")
                result[key] = self._copy_out(value)
        return result

    def remove_all(self, keys: List[str]) -> int:
        count = 0
        for key in keys:
            if self.remove(key):
                count += 1
        return count

    def pop_by_count(self, count: int) -> Dict[str, Any]:
        if count <= 0:
            return {}
        with self._lock:
            # popitem() evicts the true least-recently-used entry; iterating
            # keys() would not, because LRUCache iterates in insertion order.
            # Snapshot deadlines first: the eviction hook prunes metadata.
            deadlines = dict(self._expiries)
            now = self._now_millis()
            popped: Dict[str, Any] = {}
            self._explicit_pop_depth += 1
            try:
                for _ in range(min(count, len(self._entries))):
                    key, value = self._entries.popitem()
                    expire_at = deadlines.get(key, 0)
                    expired = expire_at > 0 and now >= expire_at
                    popped[key] = None if expired else self._copy_out(value)
            finally:
                self._explicit_pop_depth -= 1
            self._count("removals", len(popped))
            return popped

    def expiry(self, key: str, ttl_ms: int) -> None:
        """Update the TTL of an existing entry.

        Applies under every policy including ETERNAL, matching the Java
        `setExpiry`. If the entry does not exist the call is a no-op (Java
        logs a warning and returns; the entry is not created).
        """
        with self._lock:
            if key not in self._entries or self._is_expired(key):
                return
            self._expiries[key] = self._now_millis() + ttl_ms
            self._ttls[key] = ttl_ms

    def put_all(
        self,
        mapping: Dict[str, Any],
        ttl_ms: Optional[int] = None,
    ) -> None:
        for key, value in mapping.items():
            self.put(key, value, ttl_ms)

    def keys(self) -> List[str]:
        with self._lock:
            self._reap_expired()
            return list(self._entries.keys())

    def size(self) -> int:
        with self._lock:
            self._reap_expired()
            return len(self._entries)

    def statistics(self) -> CacheStatistics:
        """Snapshot of the counters for this region."""
        with self._lock:
            return CacheStatistics(**self._stats)


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

    Thread-safe: every public method acquires the relevant bucket RLock.
    The manager holds only a single ``_buckets_lock`` for the
    lookup-or-create critical section.
    """

    def __init__(
        self,
        properties: LocalCacheProperties | None = None,
        *,
        refresh_ahead_scan_interval_seconds: float = 1.0,
    ) -> None:
        self._props = properties or LocalCacheProperties()
        self._buckets: Dict[str, _CacheBucket] = {}
        self._buckets_lock = threading.Lock()
        # Registered read-through loaders / write-through writers, per region.
        self._loaders: Dict[str, CacheLoader] = {}
        self._writers: Dict[str, CacheWriter] = {}
        self._strategies_lock = threading.Lock()
        # Refresh-ahead machinery: one scanning thread for the manager, one
        # executor per region (its thread count comes from that region
        # `refresh_ahead_threads`).
        self._scan_interval = max(0.01, float(refresh_ahead_scan_interval_seconds))
        self._refresher: threading.Thread | None = None
        self._refresher_stop = threading.Event()
        self._refresh_executors: Dict[str, ThreadPoolExecutor] = {}

    @property
    def properties(self) -> LocalCacheProperties:
        return self._props

    def _bucket(self, region: str) -> _CacheBucket:
        """Return the bucket for `region`, creating it on first use."""
        start_refresher = False
        with self._buckets_lock:
            bucket = self._buckets.get(region)
            if bucket is None:
                override = self._props.cache_definitions.get(region)
                props = self._props
                if override is not None:
                    policy = override.expiry_policy
                    ttl_ms = override.ttl_millis
                    max_size = override.max_size
                    statistics_enabled = override.statistics_enabled
                    store_by_value = override.store_by_value
                    read_through = override.read_through
                    write_through = override.write_through
                    refresh_ahead = override.refresh_ahead
                    refresh_ahead_ratio = override.refresh_ahead_ratio
                    refresh_threads = override.refresh_ahead_threads
                else:
                    policy = props.default_expiry_policy
                    ttl_ms = props.default_ttl_millis
                    max_size = props.default_max_size
                    statistics_enabled = props.default_statistics_enabled
                    store_by_value = props.default_store_by_value
                    read_through = props.default_read_through
                    write_through = props.default_write_through
                    refresh_ahead = props.default_refresh_ahead
                    refresh_ahead_ratio = props.default_refresh_ahead_ratio
                    refresh_threads = props.default_refresh_ahead_threads
                bucket = _CacheBucket(
                    policy,
                    ttl_ms,
                    max_size,
                    statistics_enabled=statistics_enabled,
                    store_by_value=store_by_value,
                    read_through=read_through,
                    write_through=write_through,
                    refresh_ahead=refresh_ahead,
                    refresh_ahead_ratio=refresh_ahead_ratio,
                )
                bucket.set_loader(self._loaders.get(region))
                bucket.set_writer(self._writers.get(region))
                self._buckets[region] = bucket
                if refresh_ahead:
                    self._refresh_executors[region] = ThreadPoolExecutor(
                        max_workers=max(1, refresh_threads),
                        thread_name_prefix=f"cache-refresh-{region}",
                    )
                    start_refresher = True
        # Start the scanning thread outside the lock: it takes the very
        # same lock when it snapshots the buckets.
        if start_refresher:
            self._start_refresher()
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

    # ── Strategy registration ───────────────────────────────────────

    def register_loader(self, region: str | Any, loader: Any) -> None:
        """注册某 region 的 read-through 加载器。

        接受实现了 ``load`` / ``load_all`` 的对象，或单个
        ``key -> value | None`` 可调用对象。注册会覆盖此前的加载器，
        并立即对已存在的 bucket 生效。

        English
        --------
        Register the read-through loader for `region`.

        Accepts an object implementing `load` / `load_all`, or a single
        `key -> value | None` callable. Re-registration replaces the
        previous loader and takes effect on an existing bucket at once.
        """
        name = self._region_name(region)
        normalized = as_cache_loader(loader)
        with self._strategies_lock:
            self._loaders[name] = normalized
        bucket = self._buckets.get(name)
        if bucket is not None:
            bucket.set_loader(normalized)

    def register_writer(self, region: str | Any, writer: Any) -> None:
        """注册某 region 的 write-through 写入器。

        接受同时实现 ``write`` 与 ``delete`` 的对象，或 ``(write, delete)``
        二元组。注册会覆盖此前的写入器，并立即对已存在的 bucket 生效。

        English
        --------
        Register the write-through writer for `region`.

        Accepts an object implementing both `write` and `delete`, or a
        `(write, delete)` pair. Re-registration replaces the previous
        writer and takes effect on an existing bucket at once.
        """
        name = self._region_name(region)
        normalized = as_cache_writer(writer)
        with self._strategies_lock:
            self._writers[name] = normalized
        bucket = self._buckets.get(name)
        if bucket is not None:
            bucket.set_writer(normalized)

    # ── Statistics ─────────────────────────────────────────────────

    def stats(self, region: str | Any) -> CacheStatistics:
        """返回某 region 的累计统计快照。

        未知 region 返回全零快照（不创建 bucket）。计数只在 region 的
        ``statistics_enabled`` 为真时维护，因此关闭时永远返回全零。

        English
        --------
        Cumulative statistics snapshot for `region`.

        An unknown region yields an all-zero snapshot (no bucket is
        created). Counters are only maintained when the region has
        `statistics_enabled` set, so a disabled region always reports
        zeros.
        """
        name = self._region_name(region)
        bucket = self._buckets.get(name)
        if bucket is None:
            return CacheStatistics()
        return bucket.statistics()

    def all_stats(self) -> Dict[str, CacheStatistics]:
        """返回所有已创建 region 的统计快照。

        English
        --------
        Statistics snapshots for every region that has been created.
        """
        with self._buckets_lock:
            buckets = list(self._buckets.items())
        return {name: bucket.statistics() for name, bucket in buckets}

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

    def remove_keys(self, region: str | Any, keys: List[str]) -> int:
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

    def pop_by_count(self, region: str | Any, count: int) -> Dict[str, Any]:
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

    def size(self, region: str | Any) -> int:
        """返回 region 中存活（未过期）的条目数。

        未知 region 返回 0。线程安全：在 bucket 的 RLock 内读取
        ``_entries`` 的长度，调用方无需自加锁。

        与 ``region_size`` 行为一致；命名为 ``size`` 是为了与外部
        L2 facade 的 ``stats()["l1_size"]`` 字段语义对齐，也便于
        不希望暴露 "region" 前缀的调用方使用。

        English
        --------
        Return the number of live (non-expired) entries in `region`.

        Returns 0 if the region is unknown. Thread-safe: reads
        `len(_entries)` under the bucket RLock; the caller does not
        need to acquire any additional lock.

        Behaviourally identical to `region_size`; the shorter `size`
        name aligns with the L2 facade `stats()["l1_size"]` field
        and is the preferred public API for new code.
        """
        try:
            return self._bucket(self._region_name(region)).size()
        except Exception:
            return 0

    # ── Refresh-ahead ───────────────────────────────────────────────

    def _start_refresher(self) -> None:
        """Start the background scanning thread (idempotent)."""
        with self._buckets_lock:
            if self._refresher is not None and self._refresher.is_alive():
                return
            self._refresher_stop.clear()
            thread = threading.Thread(
                target=self._refresher_loop,
                name="cache-refresh-scan",
                daemon=True,
            )
            self._refresher = thread
        thread.start()

    def _refresher_loop(self) -> None:
        """Scan for entries close to expiry and refresh them in background."""
        while not self._refresher_stop.wait(self._scan_interval):
            try:
                self._refresh_pass()
            except Exception:  # noqa: BLE001 — a refresh failure must not kill the thread
                pass

    def _refresh_pass(self) -> None:
        """One scan: submit refreshes for every region that wants them."""
        with self._buckets_lock:
            buckets = list(self._buckets.items())
            executors = dict(self._refresh_executors)
        for region, bucket in buckets:
            if not bucket.refresh_enabled:
                continue
            executor = executors.get(region)
            if executor is None:
                continue
            for key, ttl_ms in bucket.refresh_candidates():
                if not bucket.mark_refreshing(key):
                    continue
                try:
                    executor.submit(self._refresh_entry, bucket, key, ttl_ms)
                except RuntimeError:
                    # Executor already shut down (close() raced us).
                    bucket.unmark_refreshing(key)

    @staticmethod
    def _refresh_entry(bucket: _CacheBucket, key: str, ttl_ms: int) -> None:
        """Refresh one entry; failures are swallowed — the entry simply
        expires normally if the source is unreachable.
        """
        try:
            bucket.refresh(key, ttl_ms)
        except Exception:  # noqa: BLE001 — refresh is best-effort
            pass
        finally:
            bucket.unmark_refreshing(key)

    def close(self) -> None:
        """Drop all regions and stop the refresh machinery. Idempotent."""
        self._refresher_stop.set()
        refresher = self._refresher
        self._refresher = None
        if refresher is not None and refresher.is_alive():
            refresher.join(timeout=2.0)
        with self._buckets_lock:
            executors = list(self._refresh_executors.values())
            self._refresh_executors.clear()
            for bucket in self._buckets.values():
                # Shutdown must not wipe the source of truth: the write-through
                # deletes are suppressed here on purpose.
                bucket.clear(notify=False)
            self._buckets.clear()
        for executor in executors:
            executor.shutdown(wait=False)


__all__ = ["LocalCacheManager"]
