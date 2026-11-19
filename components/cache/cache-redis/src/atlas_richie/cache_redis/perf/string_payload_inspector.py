"""String 写入载荷的形状与体量检查。
----
检测向 Redis **String** 类型写入的值是否存在典型滥用：集合 / Map / 数组 /
大对象整包序列化、超大文本、疑似 JSON 整包。

对位 Java `cn.richie696.component.cache.redis.perf.RedisStringPayloadInspector`。

**为什么必须看"序列化之前"的值**：Java 的
`RedisStringManager.guardStringPayload` 拿到的是 `Object value`——原始对象，
所以 `value instanceof Collection` 直接成立。Python 侧若沿用"先
`encode_value` 再检查"的顺序，集合已经被压成 JSON 字符串，形状就丢了，
只剩下"长度像 JSON"这种弱启发式。因此 Python 侧把检查点前移到
`encode_value` **之前**，用**原始值**判定。

English
--------
Static shape and size inspection of a value about to be written to a Redis
String. Catches whole-collection / whole-object serialisation, oversized
text and JSON-looking blobs.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from pathlib import PurePath
from typing import Any
from uuid import UUID

from ..redis_cache_properties import RedisPerfSettings


class StringPayloadSeverity(StrEnum):
    """String 载荷检查的告警级别。

    English
    --------
    Severity of a String payload inspection.
    """

    #: 无问题。
    OK = "OK"
    #: 可疑但可用（疑似整包 / 超大文本）。
    WARN = "WARN"
    #: 明确滥用（集合 / Map / 数组整包）。
    ERROR = "ERROR"


@dataclass(frozen=True)
class StringPayloadInspection:
    """一次 String 载荷检查的结果。

    Attributes:
        severity: 告警级别。
        detail: 人类可读说明（日志前缀由调用方拼接）。

    English
    --------
    Outcome of one String payload inspection.
    """

    severity: StringPayloadSeverity
    detail: str = ""

    @property
    def is_ok(self) -> bool:
        """是否无问题。"""
        return self.severity is StringPayloadSeverity.OK


#: 视为"简单标量"、不值得告警的类型。
_SIMPLE_SCALAR_TYPES = (
    int,
    float,
    complex,
    bool,
    Decimal,
    UUID,
    datetime,
    date,
    time,
    timedelta,
    PurePath,
)


def _is_simple_scalar(value: Any) -> bool:
    """是否为简单标量（数字 / 布尔 / 枚举 / 时间 / UUID …）。"""
    if isinstance(value, _SIMPLE_SCALAR_TYPES):
        return True
    return isinstance(value, Enum)


class RedisStringPayloadInspector:
    """String 写入载荷的静态形状检查器。

    English
    --------
    Static shape inspector for values written to a Redis String.
    """

    @staticmethod
    def inspect(
        value: Any, perf: RedisPerfSettings
    ) -> StringPayloadInspection:
        """对即将写入 String 的值做静态形状与体量检查。

        不涉及真实序列化字节数——避免"为了检查而先序列化一遍"的双份开销。

        Args:
            value: **序列化之前**的原始值。
            perf: 23 字段的 perf 配置，阈值从这里读。

        Returns:
            检查结果；`severity=OK` 表示无需告警。
        """
        if value is None:
            return StringPayloadInspection(StringPayloadSeverity.OK)

        # bytes / bytearray：按字节阈值判定（与 Java 的 byte[] 分支一致）。
        if isinstance(value, (bytes, bytearray)):
            return RedisStringPayloadInspector._inspect_bytes(len(value), perf)

        # str：按字符阈值判定，再看是否"疑似整包 JSON"。
        if isinstance(value, str):
            return RedisStringPayloadInspector._inspect_str(value, perf)

        # 集合 / Map 整包：明确滥用。注意 str / bytes 已在上面拦掉——
        # 它们在 Python 里也是 Collection，不能误判。
        if isinstance(value, (Collection, Mapping)):
            return StringPayloadInspection(
                StringPayloadSeverity.ERROR,
                "集合或 Map 不应整包序列化进 Redis String，"
                "应使用 Hash/List/ZSet 等结构或拆分 key",
            )

        if _is_simple_scalar(value):
            return StringPayloadInspection(StringPayloadSeverity.OK)

        return StringPayloadInspection(
            StringPayloadSeverity.WARN,
            "疑似复杂对象整包写入 String（会被序列化器打成单一大 value），"
            "建议 Hash 字段建模、拆 key 或专用存储",
        )

    @staticmethod
    def _inspect_bytes(
        length: int, perf: RedisPerfSettings
    ) -> StringPayloadInspection:
        if length >= perf.string_payload_max_bytes_error:
            return StringPayloadInspection(
                StringPayloadSeverity.ERROR,
                f"bytes 长度过大 ({length} bytes >= errorThreshold)，"
                "不宜作为 String value（易 BIGKEY/网络放大）",
            )
        if length >= perf.string_payload_max_bytes_warn:
            return StringPayloadInspection(
                StringPayloadSeverity.WARN,
                f"bytes 长度较大 ({length} bytes >= warnThreshold)，"
                "请确认是否应使用独立二进制通道或拆分",
            )
        return StringPayloadInspection(StringPayloadSeverity.OK)

    @staticmethod
    def _inspect_str(value: str, perf: RedisPerfSettings) -> StringPayloadInspection:
        length = len(value)
        if length >= perf.string_payload_max_chars_error:
            return StringPayloadInspection(
                StringPayloadSeverity.ERROR,
                f"字符长度过大 ({length} >= errorThreshold)，"
                "String value 易形成 BIGKEY，请拆分或换结构",
            )
        if length >= perf.string_payload_max_chars_warn:
            return StringPayloadInspection(
                StringPayloadSeverity.WARN,
                f"字符长度较大 ({length} >= warnThreshold)，请评估是否拆分或压缩",
            )
        if perf.warn_json_like_string_blob and length >= perf.json_like_min_chars_for_warn:
            stripped = value.lstrip()
            if stripped[:1] in ("{", "["):
                return StringPayloadInspection(
                    StringPayloadSeverity.WARN,
                    "值以 '{' 或 '[' 开头且长度>=阈值，"
                    "疑似将 JSON 对象/数组整包写入 String，"
                    "请确认是否误用（更推荐 Hash/List）",
                )
        return StringPayloadInspection(StringPayloadSeverity.OK)


__all__ = [
    "RedisStringPayloadInspector",
    "StringPayloadInspection",
    "StringPayloadSeverity",
]
