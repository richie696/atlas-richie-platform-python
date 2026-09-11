"""缓存名称接口。
----
缓存名称。定义返回 JSR-107 Cache 名称的契约。

English
--------
L2 cache region name contract.

Mirrors `cn.richie696.component.cache.local.manage.CacheName`.
"""

from __future__ import annotations

from typing import Protocol


class CacheName(Protocol):
    """缓存名称契约。

    English
    --------
    Cache name contract.
    """

    def get_cache(self) -> str:
        """返回缓存名称。

        Returns:
            缓存名称。

        English
        --------
        Return the cache-region name (JSR-107 Cache name).

        Returns:
            The cache name.
        """
        ...


__all__ = ["CacheName"]
