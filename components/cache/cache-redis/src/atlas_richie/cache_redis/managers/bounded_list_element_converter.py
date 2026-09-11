"""有界队列/栈读取时的元素反序列化；失败时记录 WARN 便于排查（批量读取会跳过坏元素）。
----
Redis 后端对 ``BoundedListElementConverter`` 的覆盖实现。

cache-core 中的 ``BoundedListElementConverter.convert_one`` 会调用一个
**模块级** 的 ``_json_convert`` 辅助函数，而该函数直接抛出
``NotImplementedError`` —— 因此仅通过子类化并覆盖该辅助函数无法生效，
框架代码直接引用的是模块级名称。我们在下方完整覆盖 ``convert_one`` 与
``convert_all``，将 cache-core 的实现替换为支持 JSON 的 Redis 版本。

转换规则与 cache-redis 后端的其它部分保持一致：

- bytes / str / int / float / bool：直接透传。
- dict / list / tuple / set：先 JSON 解码再包装。

English
--------
Element deserialisation for bounded queue / stack reads; on failure a
WARN is logged to aid troubleshooting (batch reads drop bad elements).
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_PRIMITIVE_TYPES = (bytes, bytearray, str, int, float, bool)


def _encode_for_json(value: str | bytes) -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _coerce(raw_decoded: Any, raw_str: str, clazz: type) -> Any:
    """Pick the right deserialisation strategy based on `clazz`.

    - Primitives: direct cast via `clazz(raw)`.
    - Dict / list / tuple / set: JSON-decode then wrap.
    - Anything else: pass through.
    """
    if clazz in _PRIMITIVE_TYPES:
        return clazz(raw_str)
    # Non-primitive: try JSON-decode, then wrap in `clazz`.
    try:
        loaded = json.loads(raw_str)
    except json.JSONDecodeError:
        # Raw value isn't JSON — fall back to `clazz(raw_str)`.
        return clazz(raw_str)
    if loaded is None:
        return None
    try:
        return clazz(loaded)
    except (TypeError, ValueError):
        # Class doesn't accept a single argument; pass through.
        return loaded


class RedisBoundedListElementConverter:
    """有界队列/栈读取时的元素反序列化；失败时记录 WARN 便于排查（批量读取会跳过坏元素）。
    ----
    用于有界队列/栈读取的 JSON 感知的元素转换器。

    对外接口与 cache-core 中的 ``BoundedListElementConverter`` 一致
    （``convert_one``、``convert_all``），但内部已接入 JSON 反序列化。
    故意**不**继承 cache-core 的 ``BoundedListElementConverter``，
    因为后者的 ``convert_one`` 调用了一个无法从子类覆盖的模块级辅助函数。

    English
    --------
    JSON-aware element converter for bounded queue / stack reads.

    Implements the same public surface as cache-core's
    `BoundedListElementConverter` (`convert_one`, `convert_all`) but
    with the JSON deserialisation wired in. The cache-core
    `BoundedListElementConverter` itself is intentionally NOT
    subclassed because its `convert_one` calls a module-level helper
    that we cannot override from a subclass.
    """

    @staticmethod
    def convert_one(
        raw: Any, key: str, clazz: type, operation: str
    ) -> Any:
        """有界列表 / 栈的单次反序列化。

        中文
        ----
        单次读取：Redis 无元素时 ``raw`` 为 null，静默返回 null；
        有元素但反序列化失败时打 WARN 并返回 null。

        English
        --------
        Single-read deserialisation for bounded list / stack.

        When Redis has no element, ``raw`` is null and the method
        silently returns null. If an element exists but fails to
        deserialise, a WARN is logged and null is returned.

        Args:
            raw: Redis 返回的原始元素。
            key: 缓存 key（用于日志）。
            clazz: 目标类型。
            operation: 操作名（用于日志）。

        Returns:
            反序列化后的对象；失败时返回 ``None``。
        """
        if raw is None:
            return None
        raw_str = _encode_for_json(raw)
        try:
            return _coerce(raw, raw_str, clazz)
        except Exception as ex:
            logger.warning(
                "有界列表读取反序列化失败: key=%s, operation=%s, type=%s, failure=%s",
                key,
                operation,
                clazz.__name__ if hasattr(clazz, "__name__") else clazz,
                ex,
            )
            return None

    @staticmethod
    def convert_all(
        raw: List[Any], key: str, clazz: type, operation: str
    ) -> List[Any]:
        result: list = []
        dropped = 0
        first_reason: str | None = None
        for i, element in enumerate(raw or []):
            try:
                if element is None:
                    dropped += 1
                    if first_reason is None:
                        first_reason = f"index={i} null"
                    continue
                raw_str = _encode_for_json(element)
                converted = _coerce(element, raw_str, clazz)
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
                "有界列表批量读取丢弃 %d 个元素: key=%s, operation=%s, "
                "type=%s, rawCount=%d, returned=%d, firstFailure=%s",
                dropped,
                key,
                operation,
                clazz.__name__ if hasattr(clazz, "__name__") else clazz,
                len(raw or []),
                len(result),
                first_reason,
            )
        return result


__all__ = ["RedisBoundedListElementConverter"]
