"""日志拦截器（对位 Java `desensitize.logging.logback` 的两个 TurboFilter）。

Java 侧两个类：`SensitiveMdcTurboFilter`（MDC 脱敏）/ `SensitiveLogArgTurboFilter`
（参数脱敏）。Python 标准库没有 Logback 的 TurboFilter，等价点是
`logging.Filter` —— 它在 record 创建之后、`Formatter.format()` 之前运行，正是
「消息落地前」的位置。

两条铁律：**脱敏失败绝不影响日志链路**。所有异常都被吞掉并放行 —— 日志
是旁路，丢日志比漏一条脱敏更糟。
"""

from __future__ import annotations

import logging
from typing import Mapping

from atlas_richie.desensitize_core.serializer import SensitiveLogArg

from .mdc import MdcContext
from .service import DefaultLoggingMaskingService, LoggingMaskingService


class SensitiveMdcFilter(logging.Filter):
    """MDC 脱敏过滤器（对位 Java `SensitiveMdcTurboFilter`）。

    **与 Java 的差异**：Java 把脱敏值**就地写回 MDC** 且不还原 —— 同一
    线程后续日志的该字段永远是脱敏值（fail-safe，但业务再也拿不到原值）。本移植
    默认**不改上下文**，而是把脱敏快照挂到 `record.mdc` 交给 formatter；要 1:1
    复刻 Java 行为传 `in_place=True`。

    用法：

    ```python
    handler.addFilter(SensitiveMdcFilter(service))
    handler.setFormatter(MdcFormatter("%(message)s"))
    ```
    """

    def __init__(
        self,
        service: LoggingMaskingService | None = None,
        name: str = "",
        *,
        in_place: bool = False,
    ) -> None:
        super().__init__(name)
        self._service = service if service is not None else DefaultLoggingMaskingService()
        self._in_place = in_place

    @property
    def in_place(self) -> bool:
        """是否就地改写 MDC 上下文（Java 行为）。"""
        return self._in_place

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            source = self._source_of(record)
            if not source:
                return True
            masked = self._service.mask_mdc(source)
            if masked is None or masked == dict(source):
                return True
            if self._in_place:
                self._write_back(masked)
            record.mdc = masked
            record.mdc_masked = True
        except Exception:  # noqa: BLE001 — 脱敏失败不得影响日志链路
            return True
        return True

    @staticmethod
    def _source_of(record: logging.LogRecord) -> Mapping[str, str | None]:
        """MDC 来源：record 上显式传的 `mdc` 优先，否则取当前上下文。"""
        explicit = getattr(record, "mdc", None)
        if isinstance(explicit, Mapping):
            return explicit
        return MdcContext.current()

    @staticmethod
    def _write_back(masked: Mapping[str, str | None]) -> None:
        """把脱敏值写回上下文（值为 None 的键删除）——对位 Java 的 MDC.put/remove。"""
        for key, value in masked.items():
            if value is None:
                MdcContext.remove(key)
            else:
                MdcContext.put(key, value)


class SensitiveLogArgFilter(logging.Filter):
    """参数脱敏过滤器（对位 Java `SensitiveLogArgTurboFilter`）。

    把 `record.args` 里的 `SensitiveLogArg` **就地换成脱敏后的字符串**，
    其余参数原样 —— 与 Java 的 turbo filter 同序同效果。

    Python 的 `SensitiveLogArg.__str__` 本身就会脱敏，所以标准 formatter
    下本过滤器是「双保险」；它的真正价值是让自定义 formatter / 结构化 handler
    读到的 `record.args` 里**不再持有敏感对象**（否则读 `arg.raw_value` 就漏了）。
    """

    def __init__(self, name: str = "") -> None:
        super().__init__(name)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if not args:
                return True
            if isinstance(args, tuple):
                record.args = tuple(
                    str(arg) if isinstance(arg, SensitiveLogArg) else arg for arg in args
                )
            elif isinstance(args, Mapping):
                record.args = {
                    key: (str(value) if isinstance(value, SensitiveLogArg) else value)
                    for key, value in args.items()
                }
        except Exception:  # noqa: BLE001 — 脱敏失败不得影响日志链路
            return True
        return True


__all__ = ["SensitiveLogArgFilter", "SensitiveMdcFilter"]
