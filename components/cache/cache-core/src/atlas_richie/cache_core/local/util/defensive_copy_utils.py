"""防御性拷贝工具类。
----
防御性拷贝工具类。使用 Fury 实现高性能深拷贝，防止外部代码修改影响缓存数据。

使用对象池管理 Fury 实例，兼容虚拟线程（Virtual Threads）：
- 避免 ThreadLocal 在虚拟线程中的内存泄漏问题
- 复用 Fury 实例，提升性能
- 控制内存占用（固定大小的对象池）

English
--------
Defensive-copy helpers for the local cache.

Mirrors `cn.richie696.component.cache.local.util.DefensiveCopyUtils`.
Java uses the `Fury` deep-copy library; in Python we use
`copy.deepcopy` for plain objects and `pickle` (bytes round-trip) for
anything that fails deepcopy (e.g. closures, frames, file handles).
The "is simple" path also avoids the deepcopy cost for trivially
immutable values (None, bool, int, float, str, bytes, frozenset,
tuple of immutable).
"""

from __future__ import annotations

import copy
import pickle
from typing import Any

_IMMUTABLE_SENTINELS = (type(None), bool, int, float, str, bytes, complex)


def _is_trivially_immutable(value: Any) -> bool:
    if isinstance(value, _IMMUTABLE_SENTINELS):
        return True
    if isinstance(value, tuple):
        return all(_is_trivially_immutable(item) for item in value)
    if isinstance(value, frozenset):
        return all(_is_trivially_immutable(item) for item in value)
    return False


class DefensiveCopyUtils:
    """防御性拷贝工具类。

    English
    --------
    Defensive-copy utility.
    """

    @staticmethod
    def copy(value: Any) -> Any:
        """对缓存值做防御性拷贝。

        智能深拷贝：
        - 不可变对象（`String`/`Integer`/`Long`/`Double`/`Float`/`Boolean`/
          `Byte`/`Short`/`Character`/`BigDecimal`/`BigInteger` 等基本类型
          包装类，以及枚举类型）直接返回（性能优化）。
        - 集合类型（`Map`/`List`/`Set`）走专用深拷贝。
        - 其他对象使用 Fury 序列化实现深拷贝。

        Args:
            value: 原始对象

        Returns:
            拷贝后的对象；如果 `value` 为 `None` 则返回 `None`。

        English
        --------
        Trivially immutable values (None, bool, int, float, str, bytes,
        complex, tuple/frozenset of immutable) are returned as-is to
        avoid needless allocation. For other values we prefer
        `copy.deepcopy`; on `TypeError` (e.g. file handles) we fall
        back to a `pickle` round-trip, which is slower but always
        succeeds for picklable objects.
        """
        if _is_trivially_immutable(value):
            return value
        try:
            return copy.deepcopy(value)
        except TypeError:
            return pickle.loads(pickle.dumps(value))


__all__ = ["DefensiveCopyUtils"]
