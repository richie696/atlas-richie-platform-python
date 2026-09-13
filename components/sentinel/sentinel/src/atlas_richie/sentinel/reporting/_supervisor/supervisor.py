"""Atlas Richie Sentinel — Agent Reporter Supervisor (C 层, Mavis 治理).

中文
----
``AgentReporterSupervisor`` 是 AgentReporter 的内部状态机 (C 层
私有, 跟 Mavis 治理一致). 仿主包 ``source/_supervisor/RuleSourceSupervisor``
模式: Reporter 把"发 event"和"投递 batch"解耦, supervisor 在
background task 里跑 outbox flush 循环, 关闭时 drain.

跟 M6.5.7 / M6.7 决策一致:
- 1.x 显式禁止 ``asyncio.run()`` 反复构造 (用 explicit supervisor)
- 1.x 显式禁止复用 Engine event loop
- 1.x 显式禁止跨线程共享

English
--------
``AgentReporterSupervisor`` is the internal state machine of
``AgentReporter`` (C-layer private, per Mavis governance). Following
the main package ``source/_supervisor/RuleSourceSupervisor`` pattern:
the reporter decouples "emit event" from "submit batch"; the
supervisor runs the outbox flush loop in a background task, draining
on close.

Per M6.5.7 / M6.7 decision:
- 1.x explicitly forbids ``asyncio.run()`` repeated construction
  (use explicit supervisor)
- 1.x explicitly forbids reusing Engine event loop
- 1.x explicitly forbids cross-thread sharing
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from atlas_richie.contracts.reporting.v1 import ReportingBatch

from ..config import AgentReporterConfig
from ..errors import (
    ReporterAuthError,
    ReporterConnectionError,
    ReporterProtocolError,
    ReporterSendTimeoutError,
)
from ..outbox import ReportingOutbox
from ..transport import ReportingTransport

_log = logging.getLogger(__name__)


class AgentReporterSupervisor:
    """Agent Reporter 内部状态机 (C 层私有).

    中文
    ----
    状态机 (4 态):

    - ``CREATED`` — ``__init__`` 完毕, background task 未启动
    - ``RUNNING`` — ``start()`` 之后, flush loop 在跑
    - ``DRAINING`` — ``aclose()`` 进入, 等当前 flush 完毕 + drain
    - ``CLOSED`` — drain 完毕, 不可恢复

    flush loop 行为 (M6.5.5):

    1. 触发条件: 256 events / 64 KiB / 100ms / aclose
    2. flush → outbox.try_build_batch (256 / 64 KiB) OR build_batch_all
       (时间触发) → transport.submit (3 次 retry) → ack handler 更新
       max_contiguous_sequence
    3. retry: 4xx 不重试 (ProtocolError / AuthError) → supervisor fatal;
       5xx / 网络 / 超时 3 次 retry → transport 内置
    4. flush loop 跑 ``batch_send_interval_ns`` (默认 100ms) 周期

    English
    --------
    State machine (4 states):

    - ``CREATED`` — ``__init__`` done, background task not yet started
    - ``RUNNING`` — after ``start()``, flush loop running
    - ``DRAINING`` — entered by ``aclose()``, waiting for current
      flush + drain
    - ``CLOSED`` — drain done, not recoverable

    Flush loop behavior (M6.5.5):

    1. Triggers: 256 events / 64 KiB / 100ms / aclose
    2. flush → outbox.try_build_batch (256 / 64 KiB) OR
       build_batch_all (time trigger) → transport.submit (3 retries) →
       ack handler updates max_contiguous_sequence
    3. retry: 4xx no retry (ProtocolError / AuthError) → supervisor
       fatal; 5xx / network / timeout 3-attempt retry → built into
       transport
    4. flush loop period: ``batch_send_interval_ns`` (default 100ms)
    """

    def __init__(
        self,
        *,
        config: AgentReporterConfig,
        instance_id: str,
        startup_epoch: int,
        max_contiguous_sequence: int,
    ) -> None:
        self._config = config
        self._instance_id = instance_id
        self._startup_epoch = startup_epoch
        self._state: str = "CREATED"
        self._max_contiguous_sequence: int = max_contiguous_sequence
        self._close_event: asyncio.Event | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._last_fatal_exc: BaseException | None = None
        # 内部: outbox + transport (start() 时构造)
        self._outbox: ReportingOutbox | None = None
        self._transport: ReportingTransport | None = None
        # 公开回调 (Reporter 注册, supervisor 失败 / close 调)
        self._on_fatal: Any = None  # Callable[[BaseException], None] | None

    @property
    def state(self) -> str:
        return self._state

    @property
    def max_contiguous_sequence(self) -> int:
        return self._max_contiguous_sequence

    @property
    def last_fatal_exc(self) -> BaseException | None:
        return self._last_fatal_exc

    def set_fatal_callback(self, callback: Any) -> None:
        """注册 fatal 回调 (Reporter.start() 后调)."""
        self._on_fatal = callback

    async def start(self) -> None:
        """启动 supervisor + background flush task.

        Raises:
            RuntimeError: 重复 start / state 不为 CREATED
        """
        if self._state != "CREATED":
            raise RuntimeError(
                f"supervisor already started (state={self._state})"
            )
        # 1. 构造 outbox + transport
        self._transport = ReportingTransport(config=self._config)
        outbox = ReportingOutbox(
            config=self._config,
            instance_id=self._instance_id,
            startup_epoch=self._startup_epoch,
        )
        outbox.assign_startup_epoch_offset(self._max_contiguous_sequence)
        self._outbox = outbox
        # 2. 启动 background task
        self._close_event = asyncio.Event()
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="atlas-richie-sentinel.AgentReporterSupervisor.flush",
        )
        self._state = "RUNNING"

    async def aclose(self) -> None:
        """Drain + 关闭.

        中文
        ----
        幂等: 重复 aclose 直接返回. RUNNING → DRAINING → 唤醒
        flush loop → flush task drain → CLOSED.

        English
        --------
        Idempotent: repeated aclose returns immediately. RUNNING →
        DRAINING → wake flush loop → flush task drains → CLOSED.
        """
        if self._state == "CLOSED":
            return
        if self._state == "CREATED":
            # 从未 start, 直接 closed
            self._state = "CLOSED"
            return
        # RUNNING / DRAINING
        if self._close_event is not None:
            self._close_event.set()
        if self._flush_task is not None:
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                # background task 异常已被记录到 last_fatal_exc,
                # aclose 阶段 swallow
                pass
        # outbox drain (强制 flush 最后一批, 即使不满 256)
        if self._outbox is not None and not self._outbox.closed:
            try:
                batch = self._outbox.drain()
                if batch is not None:
                    # drain 阶段也投递, 让最后一批进 server
                    await self._submit_one_batch(batch)
            except (ReporterConnectionError, ReporterProtocolError, ReporterAuthError):
                # drain 阶段失败, 接受损失 (1.0 不持久化 outbox)
                pass
        if self._transport is not None:
            self._transport.aclose()
        self._state = "CLOSED"

    async def _flush_loop(self) -> None:
        """background flush task 主循环.

        中文
        ----
        周期性 (默认 100ms) 检查 outbox 触发条件:
        - 256 events / 64 KiB → try_build_batch (满足条件才 flush)
        - 100ms 到 → build_batch_all (无条件 flush, 即使空)
        - aclose 唤醒 → 退出

        注意: try_build_batch 跟 build_batch_all 都可能返回 None
        (buffer 空), 此时 background task 啥都不做继续等.
        """
        interval_s = self._config.batch_send_interval_ns / 1_000_000_000
        assert self._outbox is not None
        assert self._close_event is not None
        while True:
            # 1. 等 interval 或 close 信号
            try:
                if interval_s > 0:
                    await asyncio.wait_for(
                        self._close_event.wait(),
                        timeout=interval_s,
                    )
                else:
                    await self._close_event.wait()
                # close_event.set() → 退出
                break
            except asyncio.TimeoutError:
                # interval 到, 继续走 flush 检查
                pass
            # 2. 时间触发: 无条件 build batch
            try:
                batch = self._outbox.build_batch_all()
            except Exception as e:  # noqa: BLE001
                self._mark_fatal(e)
                return
            if batch is not None:
                await self._submit_one_batch(batch)
                continue
            # 3. 数量 / 字节触发
            try:
                batch = self._outbox.try_build_batch()
            except Exception as e:  # noqa: BLE001
                self._mark_fatal(e)
                return
            if batch is not None:
                await self._submit_one_batch(batch)

    async def _submit_one_batch(self, batch: ReportingBatch) -> None:
        """单 batch 投递: transport.submit + ack 处理.

        中文
        ----
        1. 调 transport.submit (3 次 retry 内置)
        2. 拿 ack: 更新 max_contiguous_sequence
        3. 4xx / 5xx 处理: 协议错 / 鉴权错 → supervisor fatal

        English
        --------
        1. Call transport.submit (3-attempt retry built in)
        2. Get ack: update max_contiguous_sequence
        3. 4xx / 5xx handling: protocol / auth error → supervisor fatal
        """
        assert self._transport is not None
        try:
            result = await self._transport.submit(batch)
        except ReporterAuthError as e:
            self._mark_fatal(e)
            return
        except ReporterProtocolError as e:
            # 4xx 不重试, 触发 fatal (协议错必须中止)
            self._mark_fatal(e)
            return
        except (ReporterConnectionError, ReporterSendTimeoutError) as e:
            # 3 次 retry 后 transport.submit 自己 raise, 触发 fatal
            self._mark_fatal(e)
            return
        # 成功 → 处理 ack
        if result.ack is not None and len(result.ack.ack_sequences) == 1:
            seq = result.ack.ack_sequences[0]
            if (
                seq.instance_id == self._instance_id
                and seq.startup_epoch == self._startup_epoch
            ):
                if seq.max_contiguous_sequence >= self._max_contiguous_sequence:
                    self._max_contiguous_sequence = seq.max_contiguous_sequence
                # duplicate_count 静默累计到 metrics (1.0 不暴露 public API,
                # 跟 Cluster Server 决策一致)

    def _mark_fatal(self, exc: BaseException) -> None:
        """记录 fatal + 通知 Reporter + 触发自身关闭."""
        if self._last_fatal_exc is not None:
            return  # 只记录第一个
        self._last_fatal_exc = exc
        _log.error("AgentReporterSupervisor fatal: %r", exc)
        if self._on_fatal is not None:
            try:
                self._on_fatal(exc)
            except Exception:  # noqa: BLE001
                pass
        # 唤醒 flush loop, 退出
        if self._close_event is not None:
            self._close_event.set()


__all__: list[str] = []  # C 层私有
