"""`4.5 事件总线的契约与事件载荷（对位 Java `web.core.hook`）。

Java 侧五个类：`HookEvent`（标记接口）/ `HookSubscriber` / `HookBus` /
`DefaultHookBus` / `RequestCompletedEvent`。

`4.5.1 `HookEvent` 在 Java 是空标记接口，Python 侧用**基类**表达——这样
`isinstance(event, HookEvent)` 才有意义（Protocol 的空协议会让任何对象都满足）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..spi import WebRequestContext


class HookEvent:
    """`4.5.2 事件标记基类。

    `4.5.3 事件应当**不可变**（避免订阅者改共享状态）
    `4.5.4 事件**不应抛**异常（订阅者抛异常由 HookBus 隔离）
    `4.5.5 事件数据应**轻量**，避免跨线程传递大型对象
    """

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class RequestCompletedEvent(HookEvent):
    """`4.5.6 请求完成事件。

    `4.5.7 由适配层在请求结束时派发——无论正常完成、短路还是抛异常。
    """

    method: str
    path: str
    response_status: int
    start_nanos: int
    end_nanos: int
    short_circuited: bool
    has_error: bool
    client_key: str | None
    trace_id: str | None

    @classmethod
    def of(cls, ctx: WebRequestContext, end_nanos: int) -> "RequestCompletedEvent":
        """`4.5.8 从请求上下文构造事件（end_nanos = 请求结束时刻的纳秒数）。

        `4.5.8.1 end_nanos **必填**（对位 Java `of(ctx, endNanos)`）：缺省值会
        静默算成 0 耗时，比报错更难查。
        """
        return cls(
            method=ctx.method,
            path=ctx.path,
            response_status=ctx.response_status,
            start_nanos=ctx.start_nanos,
            end_nanos=end_nanos,
            short_circuited=ctx.is_short_circuited,
            has_error=ctx.error is not None,
            client_key=ctx.client_key,
            trace_id=ctx.trace_id,
        )

    def duration_millis(self) -> int:
        """`4.5.9 请求耗时（毫秒）。

        `4.5.9.1 整数毫秒（对位 Java 的 `long` 整除），不做浮点除法。
        """
        return (self.end_nanos - self.start_nanos) // 1_000_000


def now_nanos() -> int:
    """`4.5.10 单调时钟纳秒（对位 Java `System.nanoTime()`）。"""
    return time.monotonic_ns()


__all__ = ["HookEvent", "RequestCompletedEvent", "now_nanos"]
