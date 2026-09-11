"""缓存键工具类。
----
缓存键工具类。提供从原始 key 中剥离命名空间前缀的工具方法。

English
--------
Cache key utility (strip namespace prefix from raw key).

Mirrors `cn.richie696.component.cache.commons.CacheKeyUtils`.
"""

from __future__ import annotations

from typing import List


class CacheKeyUtils:
    """缓存键工具类。

    English
    --------
    Cache key utility.
    """

    @staticmethod
    def get_real_key(key: str) -> str:
        """获取真实的 key。

        若 key 包含 `@@`，则返回首个 `@@` 之后的后缀；否则原样返回。

        English
        --------
        Get the real key. If the key contains `@@`, returns the suffix
        after the first `@@`; otherwise returns the key as-is.
        """
        if "@@" in key:
            return key.split("@@", 1)[1]
        return key

    @staticmethod
    def get_real_keys(keys: List[str]) -> List[str]:
        """获取真实 key 列表。

        English
        --------
        Apply `get_real_key` to a list of keys.
        """
        return [CacheKeyUtils.get_real_key(k) for k in keys]


__all__ = ["CacheKeyUtils"]
