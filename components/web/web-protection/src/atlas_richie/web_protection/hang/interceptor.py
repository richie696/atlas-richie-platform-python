"""看门狗检测拦截器（对位 Java `web.core.hang.HangDetectionInterceptor`）。

链上最后一位（`ORDER = 500`）：注册 3 档看门狗，逐档触发时做不同动作。

`4.4.5 **与 Java 的一处刻意差异**：Java 的 kill 档调 `Thread.interrupt()`
中断业务线程——CPython **没有**等价的安全中断 API（`ctypes` 强插异常会在 C 扩展
里破坏状态）。本移植默认**只记录不中断**，并提供 `kill_interrupter` 回调让业务
方自己决定（例：`signal.pthread_kill` + `SIGINT`）。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from typing import Callable

from ..hook import HookBus
from ..spi import LONG_LIVED_ATTRIBUTE, WebInterceptor, WebInterceptorChain, WebRequestContext
from .events import HangEvent, stack_of
from .scheduler import WatchHandle, WatchdogScheduler

# 触发档位。
LEVEL_WARN = "WARN"
LEVEL_DUMP = "DUMP"
LEVEL_KILL_SWITCH = "KILL_SWITCH"


class _OneShot:
    """一次性闸门（对位 Java 的 `AtomicBoolean.compareAndSet`）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._taken = False

    def try_acquire(self) -> bool:
        with self._lock:
            if self._taken:
                return False
            self._taken = True
            return True


class HangDetectionInterceptor:
    """看门狗检测拦截器（对位 Java `HangDetectionInterceptor`）。

    `4.4.6 3 档动作分级：

    | 档位 | 动作 |
    | --- | --- |
    | warn | 记警告日志 + 发布 HangEvent(level=WARN) |
    | dump | 追加线程快照 + 发布 HangEvent(level=DUMP) |
    | kill_switch | 追加线程快照 + 调 `kill_interrupter` + 发布 HangEvent(level=KILL_SWITCH) |

    `4.4.7 **背压**：同一请求同一档只触发一次——高开销的线程快照最多跑一次。
    """

    ORDER = 500

    WATCH_HANDLE_ATTRIBUTE = "platform.web.hang.watch-handle"

    HANG_LEVEL_ATTRIBUTE = "platform.web.hang.level"

    def __init__(
        self,
        warn_ms: int,
        dump_ms: int,
        kill_switch_ms: int,
        *,
        dump_enabled: bool = False,
        scheduler: WatchdogScheduler | None = None,
        hook_bus: HookBus | None = None,
        kill_interrupter: Callable[[threading.Thread], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if warn_ms <= 0 or dump_ms <= 0 or kill_switch_ms <= 0:
            raise ValueError("thresholds must be > 0")
        if warn_ms > dump_ms or dump_ms > kill_switch_ms:
            raise ValueError(
                "warn_ms <= dump_ms <= kill_switch_ms required: "
                f"({warn_ms}, {dump_ms}, {kill_switch_ms})"
            )
        self._warn_ms = warn_ms
        self._dump_ms = dump_ms
        self._kill_switch_ms = kill_switch_ms
        self._dump_enabled = dump_enabled
        self._scheduler = scheduler if scheduler is not None else WatchdogScheduler.get_default()
        self._hook_bus = hook_bus
        self._kill_interrupter = kill_interrupter
        self._logger = logger if logger is not None else logging.getLogger(__name__)

    @property
    def warn_ms(self) -> int:
        return self._warn_ms

    @property
    def dump_ms(self) -> int:
        return self._dump_ms

    @property
    def kill_switch_ms(self) -> int:
        return self._kill_switch_ms

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        """注册看门狗 → 放行 → 结束时取消全部看门狗。"""
        if ctx.attribute(LONG_LIVED_ATTRIBUTE) is True:
            chain.proceed(ctx)
            return

        start_nanos = time.monotonic_ns()
        request_thread = threading.current_thread()
        warn_gate = _OneShot()
        dump_gate = _OneShot()
        kill_gate = _OneShot()

        warn_handle = self._scheduler.schedule(
            self._warn_ms,
            lambda: self._on_hang_level(
                ctx, start_nanos, LEVEL_WARN, request_thread, warn_gate
            ),
        )
        dump_handle = self._scheduler.schedule(
            self._dump_ms,
            lambda: self._on_hang_level(
                ctx, start_nanos, LEVEL_DUMP, request_thread, dump_gate
            ),
        )
        kill_handle = self._scheduler.schedule(
            self._kill_switch_ms,
            lambda: self._on_hang_level(
                ctx, start_nanos, LEVEL_KILL_SWITCH, request_thread, kill_gate
            ),
        )
        ctx.set_attribute(self.WATCH_HANDLE_ATTRIBUTE, warn_handle)

        try:
            chain.proceed(ctx)
        finally:
            warn_handle.cancel()
            dump_handle.cancel()
            kill_handle.cancel()

    # ───────────────────────── 内部 ─────────────────────────

    def _on_hang_level(
        self,
        ctx: WebRequestContext,
        start_nanos: int,
        level: str,
        request_thread: threading.Thread,
        gate: _OneShot,
    ) -> None:
        if not gate.try_acquire():
            return
        elapsed = (time.monotonic_ns() - start_nanos) // 1_000_000
        threshold = self._threshold_of(level)
        thread_dump = (
            self._snapshot_threads() if (self._dump_enabled and level != LEVEL_WARN) else None
        )
        message = (
            f"Hang detected level={level} method={ctx.method} path={ctx.path} "
            f"elapsedMs={elapsed} thresholdMs={threshold} "
            f"clientKey={ctx.client_key} traceId={ctx.trace_id}"
        )
        if thread_dump:
            self._logger.warning("%s\n%s", message, thread_dump)
        else:
            self._logger.warning("%s", message)

        ctx.set_attribute(self.HANG_LEVEL_ATTRIBUTE, level)
        self._publish(ctx, elapsed, threshold, request_thread)
        if level == LEVEL_KILL_SWITCH and self._kill_interrupter is not None:
            self._kill_interrupter(request_thread)

    def _publish(
        self,
        ctx: WebRequestContext,
        elapsed: int,
        threshold: int,
        request_thread: threading.Thread,
    ) -> None:
        if self._hook_bus is None:
            return
        event = HangEvent.of(
            method=ctx.method,
            path=ctx.path,
            elapsed_millis=elapsed,
            threshold_millis=threshold,
            client_key=ctx.client_key,
            trace_id=ctx.trace_id,
            stack_trace=stack_of(request_thread),
        )
        try:
            self._hook_bus.publish(event)
        except Exception:  # noqa: BLE001 — 事件发布失败不得影响请求
            return

    def _threshold_of(self, level: str) -> int:
        if level == LEVEL_DUMP:
            return self._dump_ms
        if level == LEVEL_KILL_SWITCH:
            return self._kill_switch_ms
        return self._warn_ms

    @staticmethod
    def _snapshot_threads() -> str:
        """线程快照（对位 Java `Thread.getAllStackTraces()`）。"""
        frames = sys._current_frames()
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        lines = [f"--- thread dump ({len(frames)} threads) ---"]
        for ident, frame in frames.items():
            lines.append(f'"{names.get(ident, ident)}" state=running')
            for entry in traceback.format_stack(frame):
                lines.append("    at " + entry.rstrip("\n"))
            lines.append("")
        return "\n".join(lines)


__all__ = [
    "LEVEL_DUMP",
    "LEVEL_KILL_SWITCH",
    "LEVEL_WARN",
    "HangDetectionInterceptor",
    "WatchHandle",
]
