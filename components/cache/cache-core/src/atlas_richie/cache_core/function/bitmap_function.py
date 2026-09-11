"""Bitmap 位图缓存操作函数。
----
Bitmap 相关 API 管理器接口，封装了 Redis 中 Bitmap 位操作的常用方法。
主要用于高效地进行布尔标记、用户签到、唯一性统计等场景。
支持设置和获取指定 key 的某个位（bit）值。
推荐配合布隆过滤器等高性能场景使用。

English
--------
Bitmap cache function (high-level, built on `BitmapOps`).

Mirrors `cn.richie696.component.cache.function.BitmapFunction`. Offset-
level bit read/write for high-density boolean markers (签到, 唯一性标记,
Bloom filter bitmap, etc.).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class BitmapFunction(Protocol):
    """Bitmap 相关 API。

    封装了 Redis 中 Bitmap 位操作的常用方法。主要用于高效地进行布尔标记、
    用户签到、唯一性统计等场景。支持设置和获取指定 key 的某个位（bit）值。
    推荐配合布隆过滤器等高性能场景使用。

    English
    --------
    Maps to the underlying Bitmap data structure; provides offset-level
    bit read/write capabilities for high-density boolean markers.
    """

    @abstractmethod
    def set_bit(self, key: str, offset: int, value: bool) -> None:
        """设置指定 key 的某个位（bit）值。

        Args:
            key: Redis 键
            offset: 位偏移（从 0 开始）
            value: 位值（true / false）

        English
        --------
        Set the bit at the given offset.
        """
        ...

    @abstractmethod
    def get_bit(self, key: str, offset: int) -> bool:
        """获取指定 key 的某个位（bit）值。

        Args:
            key: Redis 键
            offset: 位偏移（从 0 开始）

        Returns:
            指定位的布尔值，`True` 表示 1，`False` 表示 0。

        English
        --------
        Read the bit at the given offset.

        Returns:
            The boolean at that offset (`True` = 1, `False` = 0).
        """
        ...


__all__ = ["BitmapFunction"]
