"""看门狗事件（对位 Java `web.core.hang.HangEvent`）。"""

from __future__ import annotations

import sys
import threading
import traceback
from dataclasses import dataclass

from ..hook import HookEvent

# 栈帧上限（对位 Java `HangEvent.MAX_STACK_FRAMES`）。
MAX_STACK_FRAMES = 50


@dataclass(frozen=True, slots=True)
class HangEvent(HookEvent):
    """请求耗时超阈值事件。

    `4.4.1 由 `HangDetectionInterceptor` 在看门狗触发时发布到 HookBus。
    """

    method: str
    path: str
    elapsed_millis: int
    threshold_millis: int
    client_key: str | None
    trace_id: str | None
    stack_trace: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        method: str,
        path: str,
        elapsed_millis: int,
        threshold_millis: int,
        client_key: str | None,
        trace_id: str | None,
        stack_trace: tuple[str, ...] = (),
    ) -> "HangEvent":
        """构造 hang 事件。"""
        return cls(
            method=method,
            path=path,
            elapsed_millis=elapsed_millis,
            threshold_millis=threshold_millis,
            client_key=client_key,
            trace_id=trace_id,
            stack_trace=stack_trace,
        )


def stack_of(thread: threading.Thread) -> tuple[str, ...]:
    """取指定线程的调用栈（最多 `MAX_STACK_FRAMES` 帧，内层优先）。

    `4.4.2 **与 Java 的一处刻意差异**：Java 的 `HangEvent.of(...)` 内部调
    `Thread.currentThread()`，而它是在**看门狗线程**上被调用的——拿到的是看门狗
    自己的栈，不是卡住的那个业务线程的栈。本移植显式传被监控的业务线程，捕获
    的才是真正卡住位置的栈。
    """
    if thread is None:
        return ()
    frame = sys._current_frames().get(thread.ident)
    if frame is None:
        return ()
    frames = traceback.format_stack(frame)
    if len(frames) > MAX_STACK_FRAMES:
        frames = frames[-MAX_STACK_FRAMES:]
    return tuple(line.rstrip("\n") for line in frames)


__all__ = ["MAX_STACK_FRAMES", "HangEvent", "stack_of"]
