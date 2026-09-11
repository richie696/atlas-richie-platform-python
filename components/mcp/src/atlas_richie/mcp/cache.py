"""有界、传输无关的 MCP 客户端稳定响应缓存。

中文
----
`McpResponseCache`：按 `cacheScope` 失效、TTL 驱动的进程内 LRU 缓存。

**设计要点：**

- **只缓存 JSON 快照**（`json.dumps` 后再 `json.loads`），调用方无法通过返回值
  突变影响缓存。
- **LRU 淘汰**（`OrderedDict` + `move_to_end`）。
- **TTL 过期**在 `get` 路径上惰性检查，过期项不写回。
- **线程安全**：所有 mutation 在 `RLock` 内执行；`get` 在锁内仅做命中与过期
  判断，JSON 反序列化放在锁外（命中结果是新 dict，安全共享）。
- 容量必须 > 0；TTL <= 0 的 `put` 是 no-op（与"不过期"语义统一）。

适用于：list / discover / read 这一类"对实时性宽松、频度高"的请求 —— 用进程内
缓存节省 95% 以上的远端 list / discover 调用，而无需拉入 Redis / Caffeine 依赖。

English
--------
Bounded, transport-neutral cache for stable MCP client responses.

`McpResponseCache` is a process-local LRU keyed by `(version, identity,
method, partition, serialized params)` and expired by a per-entry TTL
returned by the server in the result envelope.

**Design points:**

- **JSON snapshots only** — values are `json.dumps`'d on write and
  `json.loads`'d on read, so callers cannot mutate cached response
  state by mutating the returned object.
- **LRU eviction** — `OrderedDict` + `move_to_end` on every hit.
- **Lazy TTL** — expiry is checked on the `get` path; expired entries
  are not re-inserted.
- **Thread-safe** — all mutations run under an `RLock`; the JSON decode
  happens outside the lock (the returned dict is a fresh allocation, so
  safe to share).
- Capacity must be > 0; `put` with `ttl_ms <= 0` is a no-op
  (consistent with the "do not cache" semantics).

Suitable for the high-frequency, freshness-tolerant read paths
(`server/discover`, `tools/list`, `resources/list`,
`resources/templates/list`, `resources/read`, `prompts/list`) where a
process-local cache saves >95% of remote list/discover round-trips
without pulling in a Redis / Caffeine dependency.

Mirrors `cn.richie696.component.mcp.client.spring.boot.McpClientResultCache`
(Java — same motivation, different storage primitive).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any

DEFAULT_CACHE_CAPACITY = 256


@dataclass(frozen=True, slots=True)
class _CachedResponse:
    serialized: str
    expires_at: float


class McpResponseCache:
    """中文
    ----
    只存储 JSON 快照，调用方无法通过返回值突变污染缓存状态。

    English
    --------
    Stores JSON snapshots only, so callers cannot mutate cached
    response state.
    """

    def __init__(self, *, capacity: int = DEFAULT_CACHE_CAPACITY) -> None:
        """中文
        ----
        Args:
            capacity: 最大条目数，必须为正数。

        Raises:
            ValueError: `capacity <= 0`。

        English
        --------
        Args:
            capacity: maximum number of entries; must be positive.

        Raises:
            ValueError: when `capacity <= 0`.
        """
        if capacity <= 0:
            raise ValueError("MCP response cache capacity must be positive")
        self._capacity = capacity
        self._entries: OrderedDict[str, _CachedResponse] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> Mapping[str, Any] | None:
        """中文
        ----
        获取缓存项；过期或缺失返回 `None`；命中后 LRU 置尾。

        Args:
            key: 缓存键。

        Returns:
            反序列化后的 JSON 快照（dict）；过期 / 缺失返回 `None`；非 dict 结果
            一律视作无效并返回 `None`。

        English
        --------
        Fetch a cached entry; return `None` on miss / expiry; mark hit
        as MRU.

        Args:
            key: cache key.

        Returns:
            The deserialised JSON snapshot (dict), or `None` if missing,
            expired, or the stored value is not a dict.
        """
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
        value = json.loads(entry.serialized)
        return value if isinstance(value, dict) else None

    def put(self, key: str, value: Mapping[str, Any], *, ttl_ms: int) -> None:
        """中文
        ----
        写入缓存；TTL <= 0 时为 no-op（不缓存语义）。

        Args:
            key: 缓存键。
            value: 要缓存的 JSON 可序列化对象。
            ttl_ms: 过期时间（毫秒），<= 0 视为"不要缓存"。

        English
        --------
        Write a cache entry; `ttl_ms <= 0` is a no-op (do-not-cache
        semantic).

        Args:
            key: cache key.
            value: JSON-serialisable object to cache.
            ttl_ms: TTL in milliseconds; `<= 0` is the do-not-cache
                signal.
        """
        if ttl_ms <= 0:
            return
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        entry = _CachedResponse(serialized, monotonic() + ttl_ms / 1000)
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def invalidate(self) -> None:
        """中文
        ----
        清空全部缓存（外部失效信号到达时调用，例如 `list_changed` 通知）。

        English
        --------
        Drop every cached entry (called on external invalidation signals
        such as a `list_changed` notification).
        """
        with self._lock:
            self._entries.clear()
