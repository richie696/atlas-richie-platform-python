"""MDC 渲染（对位 Logback 的 `includeMdc` 与 `%desensitizeMsg`）。

Java 侧 `DesensitizeConverter` 是一条 Logback conversionRule（`%desensitizeMsg`），
负责输出脱敏后的消息；MDC 则由 JSON layout 的 `includeMdc` 输出。Python 侧没有
conversionRule 机制，等价物是 `logging.Formatter` 的子类。
"""

from __future__ import annotations

import logging
from typing import Mapping

from .mdc import MdcContext


def mdc_of(record: logging.LogRecord) -> dict[str, str | None]:
    """取记录上的 MDC。

    优先取过滤器挂上的**脱敏快照**（`record.mdc`）；没有过滤器时回落到当前上下文
    （未脱敏，由调用方自己负责）。
    """
    masked = getattr(record, "mdc", None)
    if isinstance(masked, Mapping):
        return dict(masked)
    return MdcContext.current()


class MdcFormatter(logging.Formatter):
    """把 MDC 追加到格式化结果末尾（对位 Logback 的 `includeMdc`）。

    ```python
    handler.setFormatter(MdcFormatter("%(asctime)s %(levelname)s %(message)s"))
    ```

    输出形如：`... message [traceId=abc] [userId=u-1]`。

    只渲染**过滤器提供的脱敏快照**时才是安全的 —— 没挂
    `SensitiveMdcFilter` 时本 formatter 渲染的是**原始** MDC。
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        *,
        mdc_separator: str = " ",
        mdc_template: str = "[{key}={value}]",
    ) -> None:
        super().__init__(fmt, datefmt, style)
        self._mdc_separator = mdc_separator
        self._mdc_template = mdc_template

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        mdc = mdc_of(record)
        if not mdc:
            return base
        rendered = " ".join(
            self._mdc_template.format(key=key, value=value)
            for key, value in mdc.items()
            if value is not None
        )
        if not rendered:
            return base
        return base + self._mdc_separator + rendered


__all__ = ["MdcFormatter", "mdc_of"]
