"""看门狗调度器（对位 Java `web.core.hang.WatchdogScheduler`）。

每个请求注册一个定时任务；阈值到点触发回调（dump 线程栈 / 发布 HangEvent）；
请求正常完成时用 `WatchHandle.cancel()` 取消。

`4.4.3 **线程模型**：默认共享单例（`get_default()`），3 个**守护**工作线程 +
1 个守护定时线程——对位 Java 的「3 线程守护 ScheduledExecutorService」。
"""

from __future__ import annotations

import heapq
import itertools
import queue
import threading
import time
from typing import Callable


class _DaemonPool:
    """固定大小的守护线程池（跑看门狗回调）。

    `4.4.4 不用 `concurrent.futures.ThreadPoolExecutor`：它的线程在 Python 3.9+
    是**非守护**线程，进程退出时会被 `atexit` 钩子 join 住——卡住的回调能把
    整个进程挂住。Java 的看门狗线程是守护线程，语义要对齐。
    """

    def __init__(self, size: int, name_prefix: str) -> None:
        if size < 1:
            raise ValueError("size must be >= 1")
        self._queue: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        for index in range(size):
            thread = threading.Thread(
                target=self._worker,
                name=f"{name_prefix}{index + 1}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def _worker(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            try:
                task()
            except Exception:  # noqa: BLE001 — 看门狗回调异常不得影响调度器
                pass
            finally:
                self._queue.task_done()

    def submit(self, task: Callable[[], None]) -> None:
        self._queue.put(task)

    def shutdown(self) -> None:
        for _ in self._threads:
            self._queue.put(None)


class WatchHandle:
    """看门狗任务的取消 token（对位 Java `WatchdogScheduler.WatchHandle`）。"""

    def __init__(self, scheduler: "WatchdogScheduler", entry_id: int) -> None:
        self._scheduler = scheduler
        self._entry_id = entry_id
        self._cancelled = False

    def cancel(self) -> bool:
        """取消看门狗任务；重复取消返回 False，已触发的任务取消不了（也返回 False）。"""
        if self._cancelled:
            return False
        self._cancelled = True
        return self._scheduler._cancel(self._entry_id)

    def is_cancelled(self) -> bool:
        """是否已被取消。"""
        return self._cancelled

    def is_fired(self) -> bool:
        """是否已经触发过（触发后无法再取消）。"""
        return self._scheduler._is_fired(self._entry_id)

    def __enter__(self) -> "WatchHandle":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cancel()


class WatchdogScheduler:
    """看门狗调度器（对位 Java `WatchdogScheduler`）。"""

    _default: "WatchdogScheduler | None" = None
    _default_lock = threading.Lock()

    def __init__(self, *, max_workers: int = 3, name_prefix: str = "web-hang-watchdog-") -> None:
        self._pool = _DaemonPool(max_workers, name_prefix)
        self._condition = threading.Condition()
        self._pending: list[tuple[float, int, Callable[[], None]]] = []
        self._counter = itertools.count()
        self._cancelled: set[int] = set()
        self._fired: set[int] = set()
        self._shutdown = False
        self._timer = threading.Thread(
            target=self._run,
            name=f"{name_prefix}timer",
            daemon=True,
        )
        self._timer.start()

    @classmethod
    def get_default(cls) -> "WatchdogScheduler":
        """默认单例（3 线程守护池，对位 Java `getDefault()`）。"""
        with cls._default_lock:
            if cls._default is None:
                cls._default = cls()
            return cls._default

    def schedule(self, threshold_millis: int, on_timeout: Callable[[], None]) -> WatchHandle:
        """注册一个看门狗；阈值到达后调用 `on_timeout`。"""
        if threshold_millis <= 0:
            raise ValueError("threshold_millis must be > 0")
        if on_timeout is None:
            raise ValueError("on_timeout must not be None")
        deadline = time.monotonic() + threshold_millis / 1000
        entry_id = next(self._counter)
        with self._condition:
            if self._shutdown:
                raise RuntimeError("scheduler is shut down")
            heapq.heappush(self._pending, (deadline, entry_id, on_timeout))
            self._condition.notify_all()
        return WatchHandle(self, entry_id)

    def shutdown(self) -> None:
        """关闭调度器（幂等；对位 Java `shutdown`）。"""
        with self._condition:
            if self._shutdown:
                return
            self._shutdown = True
            self._pending.clear()
            self._condition.notify_all()
        self._pool.shutdown()

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    # ───────────────────────── 内部 ─────────────────────────

    def _cancel(self, entry_id: int) -> bool:
        with self._condition:
            if entry_id in self._cancelled:
                return False
            self._cancelled.add(entry_id)
            fired = entry_id in self._fired
            self._condition.notify_all()
            return not fired

    def _is_fired(self, entry_id: int) -> bool:
        with self._condition:
            return entry_id in self._fired

    def _run(self) -> None:
        while True:
            task: Callable[[], None] | None = None
            with self._condition:
                while True:
                    if self._shutdown:
                        return
                    if not self._pending:
                        self._condition.wait(timeout=1.0)
                        continue
                    deadline = self._pending[0][0]
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue
                    _, entry_id, on_timeout = heapq.heappop(self._pending)
                    if entry_id in self._cancelled:
                        continue
                    self._fired.add(entry_id)
                    task = on_timeout
                    break
            if task is None:
                continue
            try:
                task()
            except Exception:  # noqa: BLE001 — 回调异常不得拖垮调度器
                pass


__all__ = ["WatchHandle", "WatchdogScheduler"]
