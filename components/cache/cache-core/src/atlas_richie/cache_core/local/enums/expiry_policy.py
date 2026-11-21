"""缓存过期策略枚举。
----
缓存过期策略枚举。列出 JSR-107 定义的 5 种过期触发方式。

English
--------
Local-cache expiry policy enum (JSR-107 semantics, Python-native).

Mirrors `cn.richie696.component.cache.local.enums.ExpiryPolicy`. JSR-107
defines five expiry triggers, and `LocalCacheManager` implements all five
with a per-key deadline kept beside the cached value:

- `CREATED` — the deadline is set on create and never refreshed.
- `ACCESSED` — the deadline is set on create and refreshed by a read.
- `MODIFIED` — the deadline is set on create and refreshed by a write.
- `TOUCHED` — the deadline is refreshed by both reads and writes.
- `ETERNAL` — no deadline at all; entries leave only on eviction.

A write under `CREATED` / `ACCESSED` keeps the existing deadline, matching
JSR-107's `CreatedExpiryPolicy` / `AccessedExpiryPolicy`, whose
`getExpiryForUpdate` leaves expiry unchanged. `contains_key` is not an access
event. The deadline lives beside the value rather than inside `cachetools`,
so a per-key TTL override survives an expiry refresh.
"""

from __future__ import annotations

from enum import StrEnum


class ExpiryPolicy(StrEnum):
    """本地缓存过期策略枚举。

    English
    --------
    Local cache expiry policy enum.
    """

    #: Entry expires a fixed duration after the last read.
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
