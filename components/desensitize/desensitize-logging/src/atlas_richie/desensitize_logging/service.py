"""日志脱敏 SPI（对位 Java `desensitize.logging.service`）。

Java 侧两个类：`LoggingMaskingService`（接口）/ `DefaultLoggingMaskingService`
（实现）。

**一处刻意差异**（对位 Java README §3.3.3）：Java 的默认实现依赖**静态** `DesensitizeUtils` 全局绑定，
未初始化时抛 `IllegalStateException`（`maskMdc` 捕获它并回退原值）。Python 侧的
core 明确没有全局运行时（见 `desensitize_core.service` 的说明），故这里**注入**
`MaskingService`，没有「未初始化」这个状态。
"""

from __future__ import annotations

import logging
from typing import Mapping, Protocol, runtime_checkable

from atlas_richie.desensitize_core import MaskScene, MaskingService
from atlas_richie.desensitize_core.serializer import SensitiveLogArg
from atlas_richie.desensitize_core.service import DefaultMaskingService


@runtime_checkable
class LoggingMaskingService(Protocol):
    """日志脱敏 SPI（对位 Java `LoggingMaskingService`）。"""

    def to_masked_message(self, record: logging.LogRecord) -> str | None:
        """把日志事件渲染为脱敏后的消息。

        对位 Java `toMaskedMessage(ILoggingEvent)` —— Python 侧没有
        `ILoggingEvent`，但 `logging.LogRecord` 携带同样的信息（模板 + 参数）。
        """
        ...

    def mask_mdc(self, mdc: Mapping[str, str | None] | None) -> dict[str, str | None] | None:
        """按敏感键规则对 MDC 字段脱敏（结构化日志用）。

        对位 Java `maskMdc(Map<String, String>)`：入参为 None 返回 None，空 map
        返回空 map。
        """
        ...


class DefaultLoggingMaskingService:
    """默认日志脱敏服务（对位 Java `DefaultLoggingMaskingService`）。"""

    def __init__(self, masking: MaskingService | None = None) -> None:
        self._masking = masking if masking is not None else DefaultMaskingService()

    @property
    def masking(self) -> MaskingService:
        """底层脱敏服务（core 的 `MaskingService`）。"""
        return self._masking

    def to_masked_message(self, record: logging.LogRecord) -> str | None:
        """渲染脱敏后的消息。

        参数里的 `SensitiveLogArg` 换成脱敏后的**字符串**，其余参数原样；
        然后用原模板重新格式化 —— 与 Java 的 `MessageFormatter.arrayFormat` 同序。

        Python 的 `SensitiveLogArg.__str__` 本身就会脱敏，所以本方法在
        多数场景下与 `record.getMessage()` 等价；它的价值在于让**自定义
        formatter** 能拿到「已替换好的参数列表」（例如把参数单独渲染成 JSON）。
        """
        if record is None:
            return None
        args = record.args
        if not args:
            return record.getMessage()
        masked_args = self._mask_args(args)
        try:
            return record.msg % masked_args
        except Exception:  # noqa: BLE001 — 格式化失败回退原消息，不丢日志
            try:
                return record.getMessage()
            except Exception:  # noqa: BLE001 — 模板本身坏了：退回裸模板，绝不抛
                return str(record.msg)

    def mask_mdc(self, mdc: Mapping[str, str | None] | None) -> dict[str, str | None] | None:
        """按敏感键规则脱敏 MDC 字段。

        与 Java 的差异只有一处：Java 只捕获 `IllegalStateException`
        （core 未初始化），Python 侧没有那个状态，故捕获**任何**异常并回退原值
        —— 脱敏是旁路，绝不能因为它失败而中断日志链路。
        """
        if mdc is None:
            return None
        if not mdc:
            return {}
        try:
            masked = self._masking.mask_map(dict(mdc), MaskScene.LOG)
            if masked is None:
                return dict(mdc)
            return {
                key: (None if value is None else str(value))
                for key, value in masked.items()
            }
        except Exception:  # noqa: BLE001 — 脱敏失败回退原值，不得中断日志链路
            return dict(mdc)

    @staticmethod
    def _mask_args(args: object) -> object:
        """把参数里的 `SensitiveLogArg` 换成脱敏字符串。"""
        if isinstance(args, tuple):
            return tuple(
                str(arg) if isinstance(arg, SensitiveLogArg) else arg for arg in args
            )
        if isinstance(args, Mapping):
            return {
                key: (str(value) if isinstance(value, SensitiveLogArg) else value)
                for key, value in args.items()
            }
        return args


__all__ = ["DefaultLoggingMaskingService", "LoggingMaskingService"]
