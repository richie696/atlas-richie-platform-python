"""缓存过期策略枚举。
----
缓存过期策略枚举。列出 JSR-107 定义的 5 种过期触发方式。

English
--------
Local-cache expiry policy enum (JSR-107 semantics, Python-native).

Mirrors `cn.richie696.component.cache.local.enums.ExpiryPolicy`. JSR-107
defines five expiry triggers; the Python translation implements the
two that map cleanly to `cachetools`:

- `ACCESSED` → `cachetools.TTLCache` (auto-expire on read/write).
- `ETERNAL` → `cachetools.LRUCache` (evict by LRU when full, no TTL).
- `CREATED` / `MODIFIED` / `TOUCHED` → fall back to `ACCESSED` semantics
  with a `@deprecated` warning in code paths that opt in. A future
  revision may track per-key timestamps for strict JSR-107 semantics;
  today this would duplicate complexity the user explicitly does not
  want (per locked decision: "用 cachetools 不用 Spring/JSR-107").
"""

from __future__ import annotations

from enum import StrEnum


class ExpiryPolicy(StrEnum):
    """本地缓存过期策略枚举。

    English
    --------
    Local cache expiry policy enum.
    """

    #: Entry expires on read or write (last-accessed timestamp).
    ACCESSED = "accessed"

    #: Entry expires a fixed duration after first insert.
    CREATED = "created"

    #: Entry never expires; only evicted when the cache is full.
    ETERNAL = "eternal"

    #: Entry expires a fixed duration after the last write.
    MODIFIED = "modified"

    #: Entry expires a fixed duration after the last read or write.
    TOUCHED = "touched"


__all__ = ["ExpiryPolicy"]
