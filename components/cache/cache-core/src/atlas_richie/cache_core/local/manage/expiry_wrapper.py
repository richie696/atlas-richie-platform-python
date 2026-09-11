"""带过期时间的值包装。
----
带过期时间的值包装，用于本地缓存条目。

English
--------
Internal value wrapper carrying expiry metadata.

Mirrors `cn.richie696.component.cache.local.manage.ExpiryWrapper`. Holds
the stored value plus the (epoch millis) absolute expiry timestamp.
Used for `CREATED` / `MODIFIED` / `TOUCHED` policy implementations and
for `expiry(key, ttl_millis)` writes against an ETERNAL bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExpiryWrapper:
    """持有缓存值与过期时间戳的不可变包装。

    Attributes:
        value: 原始值（已做防御性拷贝）。
        expire_at_millis: 绝对过期时间（epoch 毫秒）；
            `0` 表示不过期。

    English
    --------
    Immutable wrapper carrying the cached value and its absolute
    expiry timestamp.
    """

    value: Any
    expire_at_millis: int = 0

    @property
    def has_expiry(self) -> bool:
        """是否设置了过期时间。

        English
        --------
        Whether the wrapper carries an explicit expiry.
        """
        return self.expire_at_millis > 0


__all__ = ["ExpiryWrapper"]
