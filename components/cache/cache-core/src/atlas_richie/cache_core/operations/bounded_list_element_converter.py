"""Bounded-list element deserialiser.

Mirrors `cn.richie696.component.cache.redis.operations.BoundedListElementConverter`.
Single-failure → WARN log + return None; batch → log dropped count.
"""

from __future__ import annotations

import logging
from typing import Any, List, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BoundedListElementConverter:
    """有界队列/栈读取时的元素反序列化；失败时记录 WARN 便于排查（批量读取会跳过坏元素）。"""

    @staticmethod
    def convert_one(raw: Any, key: str, clazz: type[T], operation: str) -> T | None:
        """单次读取：Redis 无元素时 `raw` 为 None，静默返回 None；有元素但反序列化失败时打 WARN 并返回 None。"""
        if raw is None:
            return None
        try:
            result = clazz(raw) if clazz in (bytes, bytearray, str, int, float, bool) else _json_convert(raw, clazz)
            return result if result is not None else None
        except Exception as ex:
            logger.warning(
                "有界列表读取反序列化失败: key=%s, operation=%s, type=%s, failure=%s",
                key, operation, clazz.__name__ if hasattr(clazz, "__name__") else clazz, ex,
            )
            return None

    @staticmethod
    def convert_all(raw: List[Any], key: str, clazz: type[T], operation: str) -> List[T]:
        """批量反序列化，跳过 None / 失败元素并 WARN。"""
        result: list = []
        dropped = 0
        first_reason: str | None = None
        for i, element in enumerate(raw):
            try:
                converted = clazz(element) if clazz in (bytes, bytearray, str, int, float, bool) else _json_convert(element, clazz)
                if converted is not None:
                    result.append(converted)
                else:
                    dropped += 1
                    if first_reason is None:
                        first_reason = f"index={i} convertResult=null"
            except Exception as ex:
                dropped += 1
                if first_reason is None:
                    first_reason = f"index={i} error={ex}"
        if dropped > 0:
            logger.warning(
                "有界列表批量读取丢弃 %d 个元素（null 或反序列化失败）: key=%s, operation=%s, "
                "type=%s, rawCount=%d, returned=%d, firstFailure=%s",
                dropped, key, operation, clazz.__name__ if hasattr(clazz, "__name__") else clazz,
                len(raw), len(result), first_reason,
            )
        return result


def _json_convert(raw: Any, clazz: type[T]) -> T | None:
    """JSON helper. Implemented at backend level (no JSON dep in core)."""
    raise NotImplementedError(
        "BoundedListElementConverter requires JSON conversion; "
        "the redis backend must inject a JSON helper via subclassing"
    )


__all__ = ["BoundedListElementConverter"]
