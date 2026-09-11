"""位图操作接口。

中文
----
位图操作接口。
对应底层 Bitmap 数据结构，提供偏移量级的位读写能力。

English
--------
Bitmap ops interface.

Mirrors `cn.richie696.component.cache.ops.BitmapOps`. Maps to the
underlying Bitmap data structure; offset-level bit read/write.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class BitmapOps(Protocol):
    """中文
    ----
    位图操作接口。对应底层 Bitmap 数据结构，提供偏移量级的位读写能力。

    English
    --------
    Bitmap ops. Maps to the underlying Bitmap data structure; offset-level
    bit read/write.
    """

    @abstractmethod
    def set(self, key: str, offset: int, value: bool) -> None:
        """中文
        ----
        设置 `key` 在 `offset` 偏移量处的位为 `value`。

        English
        --------
        Set the bit at `offset` of `key` to `value`.
        """
        ...

    @abstractmethod
    def get(self, key: str, offset: int) -> bool:
        """中文
        ----
        读取 `key` 在 `offset` 偏移量处的位。

        English
        --------
        Get the bit at `offset` of `key`.
        """
        ...


__all__ = ["BitmapOps"]
