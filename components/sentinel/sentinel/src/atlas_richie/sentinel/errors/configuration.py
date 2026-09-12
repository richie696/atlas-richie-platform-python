"""Sentinel 配置错误异常(M1.1 引入)。

中文
----
``SentinelConfigurationError`` 在配置解析 / 校验失败时抛出;Engine
不进入 READY 状态,直接转入 FAILED。``__init__`` 接受 ``field`` /
``reason`` / ``value`` 三个可选字段,便于用户定位错误配置项。

English
--------
Sentinel configuration error exception (M1.1).

``SentinelConfigurationError`` is raised when configuration parsing /
validation fails; the Engine does not enter READY and goes straight to
FAILED. ``__init__`` accepts optional ``field`` / ``reason`` / ``value``
triples so users can pinpoint the offending config entry."""

from __future__ import annotations

from typing import Any

from .base import SentinelError


class SentinelConfigurationError(SentinelError):
    """中文
    ----
    配置错误。Engine 启动时如果解析 / 校验失败,直接抛此异常并
    转入 FAILED 状态。

    - `field` — 出错的配置字段名(点路径,如 ``"rules[2].threshold"``)
    - `reason` — 人类可读的原因
    - `value` — 出错的原始 value(可选;过大时可截断或省略)

    English
    --------
    Configuration error. Raised at Engine init when parsing / validation
    fails; the Engine goes straight to FAILED.

    - ``field`` — dotted config field path (e.g.
      ``"rules[2].threshold"``).
    - ``reason`` — human-readable reason.
    - ``value`` — offending value (optional; may be truncated or
      omitted for huge payloads).
    """

    def __init__(
        self,
        message: str,
        *,
        field: str = "",
        reason: str = "",
        value: Any = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason
        self.value = value


__all__ = ["SentinelConfigurationError"]
