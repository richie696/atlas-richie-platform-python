"""高级查询的执行守卫：并发许可 + 超时 + 协作取消。

对应 Java `cn.richie696.component.vector.query.VectorQueryExecutionGuard`。

与 Java 的一处**有意差异**：JVM 可以 `Future.cancel(true)` 中断工作线程，
CPython 不能强杀线程。超时后本守卫放弃等待并抛 TIMEOUT，工作线程继续跑到
自然结束（daemon 线程，不阻塞进程退出），期间仍占用一个并发许可 —— 这让
许可数始终反映真实在途工作量，比 Java 的"取消即释放"更保守。
需要真正可中断的 action 应轮询传入的 `cancelled` 谓词。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError
from datetime import timedelta
from typing import Callable, TypeVar

from .query import VectorQueryErrorCode, VectorQueryValidationException

T = TypeVar("T")

DEFAULT_MAX_CONCURRENT = 16
_POLL_SECONDS = 0.05


class VectorQueryExecutionGuard:
    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        if not 1 <= max_concurrent <= 1_024:
            raise ValueError("maxConcurrent must be within [1,1024]")
        self._permits = threading.BoundedSemaphore(max_concurrent)
        self._max_concurrent = max_concurrent

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def execute(
        self,
        timeout: timedelta,
        action: Callable[[], T],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> T:
        if timeout is None or timeout <= timedelta(0):
            raise ValueError("timeout must be positive")
        if not callable(action):
            raise ValueError("action is required")
        if cancelled is not None and not callable(cancelled):
            raise ValueError("cancelled must be callable")
        is_cancelled = cancelled or (lambda: False)

        if not self._permits.acquire(blocking=False):
            raise VectorQueryValidationException(
                VectorQueryErrorCode.CONCURRENCY_LIMIT,
                "advanced vector query concurrency limit reached",
            )

        outcome: dict[str, object] = {}
        done = threading.Event()

        def run() -> None:
            try:
                outcome["value"] = action()
            except BaseException as error:  # noqa: BLE001 - 原样回传给调用方
                outcome["error"] = error
            finally:
                done.set()
                self._permits.release()

        worker = threading.Thread(
            target=run, name="atlas-vector-advanced", daemon=True
        )
        try:
            worker.start()
        except RuntimeError:
            self._permits.release()
            raise VectorQueryValidationException(
                VectorQueryErrorCode.CONCURRENCY_LIMIT,
                "advanced vector query executor is unavailable",
            ) from None

        deadline = time.monotonic() + timeout.total_seconds()
        while True:
            if is_cancelled():
                raise CancelledError("advanced vector query was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VectorQueryValidationException(
                    VectorQueryErrorCode.TIMEOUT, "advanced vector query timed out"
                )
            if done.wait(min(remaining, _POLL_SECONDS)):
                break

        if is_cancelled():
            raise CancelledError("advanced vector query was cancelled")
        if "error" in outcome:
            raise outcome["error"]  # type: ignore[misc]
        return outcome["value"]  # type: ignore[return-value]


__all__ = ["VectorQueryExecutionGuard", "DEFAULT_MAX_CONCURRENT"]