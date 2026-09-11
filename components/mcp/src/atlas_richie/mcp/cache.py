"""Bounded, transport-neutral cache for stable MCP client responses."""

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
    """Stores JSON snapshots only, so callers cannot mutate cached response state."""

    def __init__(self, *, capacity: int = DEFAULT_CACHE_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError("MCP response cache capacity must be positive")
        self._capacity = capacity
        self._entries: OrderedDict[str, _CachedResponse] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> Mapping[str, Any] | None:
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
        with self._lock:
            self._entries.clear()
