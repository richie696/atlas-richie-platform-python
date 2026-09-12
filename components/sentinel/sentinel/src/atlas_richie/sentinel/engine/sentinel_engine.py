"""Sentinel Engine(M1.2 — 6 状态机 async 上下文管理器)。

中文
----
``SentinelEngine`` 是 Sentinel 的运行时入口,持有 7 类内置 Slot
(``NodeSelector`` / ``Statistic`` / ``Authority`` / ``System`` /
``Flow`` / ``ParamFlow`` / ``Degrade``,M2 才全部实现,M1.2 只保留
SlotChain 与 6 状态机骨架)。

6 状态机迁移:

    CREATED ──[__aenter__]──▶ INITIALIZING ──[ready]──▶ READY
                                                              │
                                              ┌──[__aexit__]──┤
                                              ▼               ▼
                                       SHUTTING_DOWN     [entry 接受]
                                              │               │
                                       [in-flight 结束]      │
                                              ▼               │
                                          SHUTDOWN            │
                                                              ▼
                                                       FAILED (init 或运行出错)

非法迁移(例如 SHUTDOWN → READY)抛 ``SentinelLifecycleError``。

fail-safe 三种策略(M1.3 完整实现,M1.2 仅保留字段):

- FAIL_CLOSED:Slot 异常 → 拒绝(默认;主包默认最保守)
- FAIL_OPEN:Slot 异常 → 放行(observe),不计入指标
- FAIL_FAST:Slot 异常 → 启动时直接进入 FAILED 状态

CancelledError(M1.3 完整语义):

- 等待中取消:Outcome.CANCELLED
- 业务执行中取消:Outcome.CANCELLED,lease 仍逆序释放
- 流式响应取消:Outcome.CANCELLED,流式 slot 仍能 release

English
--------
Sentinel Engine (M1.2 — 6-state machine async context manager).

``SentinelEngine`` is the Sentinel runtime entry point. It owns the
7 built-in Slots (``NodeSelector`` / ``Statistic`` / ``Authority`` /
``System`` / ``Flow`` / ``ParamFlow`` / ``Degrade``; M2 implements
them in full, M1.2 only the SlotChain + 6-state machine skeleton).

6-state machine transitions:

    CREATED ──[__aenter__]──▶ INITIALIZING ──[ready]──▶ READY
                                                              │
                                              ┌──[__aexit__]──┤
                                              ▼               ▼
                                       SHUTTING_DOWN     [entry accepted]
                                              │               │
                                       [in-flight 结束]      │
                                              ▼               │
                                          SHUTDOWN            │
                                                              ▼
                                                       FAILED (init or runtime error)

Illegal transitions (e.g. SHUTDOWN → READY) raise
``SentinelLifecycleError``.

fail-safe strategies (M1.3 implements fully; M1.2 only the field):

- ``FAIL_CLOSED``: Slot exception → reject (default; main wheel
  defaults to most conservative).
- ``FAIL_OPEN``: Slot exception → admit (observe only), not counted
  in metrics.
- ``FAIL_FAST``: Slot exception → Engine never enters READY."""

from __future__ import annotations

import asyncio
import enum
import time
from contextlib import suppress
from dataclasses import dataclass
from types import TracebackType
from typing import TypeAlias

from ..errors import (
    SentinelConfigurationError,
    SentinelError,
    SentinelLifecycleError,
)
from ..model.argument import InvocationArguments
from ..model.context import (
    SentinelContext,
    bind_current_context,
    current_context,
    reset_current_context,
)
from ..model.enums import EngineState
from ..model.outcome import Outcome, OutcomeKind
from ..model.resource import Resource
from .entry import EntryLease, EntryRequest
from .slot import Slot
from .slot_chain import SlotChain


class FailSafe(enum.Enum):
    """中文
    ----
    fail-safe 策略(M1.2 仅声明;M1.3 完整实现)。

    English
    --------
    fail-safe strategy (M1.2 declares; M1.3 implements).
    """

    FAIL_CLOSED = "fail_closed"  # 默认:Slot 异常 → 拒绝
    FAIL_OPEN = "fail_open"      # Slot 异常 → 放行(observe)
    FAIL_FAST = "fail_fast"      # Slot 异常 → 启动直接 FAILED


# Type alias for entry outcome observers (M1.3 完整实现)
OutcomeObserver: TypeAlias = "callable[[Outcome], None]"
"""中文
----
Entry Outcome 观察者回调。Engine 在每次 entry 完成后调用;不能抛异常
(失败吞到 Engine.last_error)。

English
--------
Entry Outcome observer callback. Called by the Engine on every entry
completion; must not raise (failures swallowed to Engine.last_error)."""


@dataclass
class _EngineContext:
    """中文
    ----
    内部状态(仅 Engine 持有)。

    English
    --------
    Internal state (Engine only).
    """

    state: EngineState = EngineState.CREATED
    fail_safe: FailSafe = FailSafe.FAIL_CLOSED
    last_error: BaseException | None = None
    last_outcome: Outcome | None = None
    in_flight: int = 0
    # Track bind tokens for contextvars cleanup
    _context_token: object | None = None


class SentinelEngine:
    """中文
    ----
    Sentinel 运行时入口(async context manager)。

    用法::

        async with SentinelEngine() as engine:
            engine.add_slot(MyFlowSlot())
            async with engine.entry(Resource("orders-api")) as entry:
                result = await business_call()
                # entry.outcome holds the final Outcome

    状态机非法迁移(例如 SHUTDOWN 后再 ``entry()``)抛
    ``SentinelLifecycleError``;**不**走 Outcome 化(状态错误是
    代码 bug,不是业务错误)。

    English
    --------
    Sentinel runtime entry point (async context manager).

    Usage::

        async with SentinelEngine() as engine:
            engine.add_slot(MyFlowSlot())
            async with engine.entry(Resource("orders-api")) as entry:
                result = await business_call()
                # entry.outcome holds the final Outcome

    Illegal state transitions (e.g. ``entry()`` after SHUTDOWN) raise
    ``SentinelLifecycleError``; they are **not** normalized to
    Outcome (state errors are code bugs, not business errors).
    """

    def __init__(self, *, fail_safe: FailSafe = FailSafe.FAIL_CLOSED) -> None:
        self._ctx = _EngineContext(fail_safe=fail_safe)
        self._chain = SlotChain()
        # M1.2 uses an asyncio.Event to serialize state transitions
        # (the Engine is a single-process, single-loop object).
        self._state_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def state(self) -> EngineState:
        """中文
        ----
        当前状态(只读)。

        English
        --------
        Current state (read-only).
        """
        return self._ctx.state

    @property
    def fail_safe(self) -> FailSafe:
        return self._ctx.fail_safe

    @property
    def last_error(self) -> BaseException | None:
        """中文
        ----
        上次错误(Slot 异常被 swallow、Engine 进入 FAILED 时记录)。

        English
        --------
        Last error (recorded when a Slot exception is swallowed or the
        Engine enters FAILED).
        """
        return self._ctx.last_error

    @property
    def last_outcome(self) -> Outcome | None:
        """中文
        ----
        上次 entry 的 Outcome(M1.2 占位;M1.3 完整暴露给 observers)。

        English
        --------
        Last entry's Outcome (placeholder in M1.2; M1.3 fully exposed
        to observers).
        """
        return self._ctx.last_outcome

    @property
    def in_flight(self) -> int:
        """中文
        ----
        当前在飞 entry 数(M1.3 close 时用)。

        English
        --------
        Current in-flight entry count (used by M1.3 close).
        """
        return self._ctx.in_flight

    # ------------------------------------------------------------------
    # async context manager — Engine 生命周期
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "SentinelEngine":
        """中文
        ----
        Engine 进入 ``INITIALIZING`` → ``READY``(M1.2 占位:跳过
        INITIALIZING 直接到 READY;M1.3 加 metric sampler 启动等)。

        English
        --------
        Engine transitions to ``INITIALIZING`` → ``READY`` (M1.2
        placeholder: skip INITIALIZING, go straight to READY; M1.3 adds
        metric sampler startup, etc.).
        """
        async with self._state_lock:
            if self._ctx.state is not EngineState.CREATED:
                raise SentinelLifecycleError(
                    f"__aenter__ only allowed in CREATED state (current: {self._ctx.state.value})",
                    from_state=self._ctx.state.value,
                    to_state=EngineState.READY.value,
                    component="engine",
                )
            # M1.2 placeholder: direct CREATED → READY (M1.3 inserts
            # INITIALIZING for metric sampler startup).
            self._ctx.state = EngineState.READY
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """中文
        ----
        Engine 进入 ``SHUTTING_DOWN`` → ``SHUTDOWN``。

        **M1.3 graceful close**: 默认 ``graceful_timeout=30.0`` 秒等待
        in-flight 归零;超时后切到 ``SHUTDOWN``(in-flight 仍会被
        ``_finalize_entry`` 走完释放流程,但**不**抛错)。

        English
        --------
        Engine transitions to ``SHUTTING_DOWN`` → ``SHUTDOWN``.

        **M1.3 graceful close**: by default waits up to
        ``graceful_timeout=30.0`` seconds for in-flight to drain; on
        timeout, transitions to ``SHUTDOWN`` (in-flight entries still
        run ``_finalize_entry`` to completion; no error raised).
        """
        await self.close(graceful_timeout=30.0)

    async def close(self, *, graceful_timeout: float = 30.0) -> None:
        """中文
        ----
        显式关闭 Engine(不依赖 ``async with``)。

        - READY → SHUTTING_DOWN,等待 in_flight == 0 或 timeout
        - SHUTTING_DOWN → SHUTDOWN(timeout 触发也走完)
        - SHUTDOWN / FAILED 重复调用安全(no-op)
        - 非 READY / SHUTTING_DOWN 抛 ``SentinelLifecycleError``

        ``aclose()`` 是此方法的别名,匹配 Python async close 协议。

        English
        --------
        Explicit Engine close (independent of ``async with``).

        - READY → SHUTTING_DOWN, wait for in_flight == 0 or timeout.
        - SHUTTING_DOWN → SHUTDOWN (timeout-triggered also completes).
        - SHUTDOWN / FAILED: repeated calls are no-ops.
        - Other states: raise ``SentinelLifecycleError``.

        ``aclose()`` is an alias matching Python's async close protocol.
        """
        async with self._state_lock:
            if self._ctx.state is EngineState.SHUTDOWN:
                return
            if self._ctx.state is not EngineState.READY:
                # FAILED is allowed for idempotent close
                if self._ctx.state is not EngineState.FAILED:
                    raise SentinelLifecycleError(
                        f"close() requires READY/SHUTTING_DOWN/SHUTDOWN/FAILED "
                        f"(current: {self._ctx.state.value})",
                        from_state=self._ctx.state.value,
                        to_state=EngineState.SHUTDOWN.value,
                        component="engine",
                    )
                return
            self._ctx.state = EngineState.SHUTTING_DOWN
        # Wait for in-flight outside the lock (so new entries can fail fast)
        if graceful_timeout is not None and graceful_timeout > 0:
            deadline = time.monotonic() + graceful_timeout
            while self._ctx.in_flight > 0 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
        # Transition to SHUTDOWN regardless of whether in-flight drained
        async with self._state_lock:
            self._ctx.state = EngineState.SHUTDOWN

    async def aclose(self) -> None:
        """中文
        ----
        ``close()`` 的别名;匹配 Python async close 协议
        (e.g. 配合 ``async with engine:`` 之后的清理)。

        English
        --------
        Alias of ``close()``; matches Python's async close protocol
        (e.g. for use after ``async with engine:`` block exit).
        """
        await self.close()

    # ------------------------------------------------------------------
    # Slot management
    # ------------------------------------------------------------------

    def add_slot(self, slot: Slot) -> None:
        """中文
        ----
        添加 Slot。**仅** READY 状态允许;其它状态抛
        ``SentinelLifecycleError``。

        English
        --------
        Add a Slot. Allowed **only** in READY state; other states raise
        ``SentinelLifecycleError``.
        """
        if self._ctx.state is not EngineState.READY:
            raise SentinelLifecycleError(
                f"add_slot only allowed in READY state (current: {self._ctx.state.value})",
                from_state=self._ctx.state.value,
                to_state="add_slot",
                component="engine",
            )
        self._chain.add_slot(slot)

    def remove_slot(self, slot: Slot) -> bool:
        """中文
        ----
        移除 Slot。READY 状态才允许。

        English
        --------
        Remove a Slot. READY state only.
        """
        if self._ctx.state is not EngineState.READY:
            raise SentinelLifecycleError(
                f"remove_slot only allowed in READY state (current: {self._ctx.state.value})",
                from_state=self._ctx.state.value,
                to_state="remove_slot",
                component="engine",
            )
        return self._chain.remove_slot(slot)

    @property
    def slots(self) -> tuple[Slot, ...]:
        """中文
        ----
        当前 SlotChain 的 Order 升序快照(只读)。

        English
        --------
        Current SlotChain's Order-ascending snapshot (read-only).
        """
        return self._chain.frozen_slots()

    # ------------------------------------------------------------------
    # entry() factory
    # ------------------------------------------------------------------

    def entry(
        self,
        resource: Resource,
        *,
        args: InvocationArguments | None = None,
        context: SentinelContext | None = None,
    ) -> EntryRequest:
        """中文
        ----
        构造一次 entry(async context manager)。

        **非** READY 状态抛 ``SentinelLifecycleError``(SHUTTING_DOWN /
        SHUTDOWN / FAILED 全部拒绝);READY 时构造 ``EntryRequest`` 并返回,
        延迟到 ``__aenter__`` 才走 SlotChain。

        English
        --------
        Construct a single entry (async context manager).

        Non-READY states raise ``SentinelLifecycleError`` (SHUTTING_DOWN
        / SHUTDOWN / FAILED all reject); READY constructs an
        ``EntryRequest`` and returns it; the actual SlotChain run is
        deferred to ``__aenter__``.
        """
        if self._ctx.state is not EngineState.READY:
            raise SentinelLifecycleError(
                f"entry() only allowed in READY state (current: {self._ctx.state.value})",
                from_state=self._ctx.state.value,
                to_state="entry",
                component="engine",
            )
        ctx = context or SentinelContext()
        return EntryRequest(
            engine=self,
            resource=resource,
            args=args,
            context=ctx,
        )

    # ------------------------------------------------------------------
    # Internal: SlotChain enter (called by EntryRequest.__aenter__)
    # ------------------------------------------------------------------

    async def _run_slot_chain_enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
        lease: EntryLease,
    ) -> None:
        """中文
        ----
        Engine 内部: 按 Order 调 ``Slot.enter``;任一抛
        ``SentinelBlockedError`` 即短路 + 释放已收 lease。

        **in_flight 簿记**:本方法进入时 +1,退出时 -1(无论成功 / 失败)。
        BLOCKED 路径的 Outcome 已经在本方法内构造,``__aexit__`` 不会再
        调 ``_finalize_entry``(Python 不会在 ``__aenter__`` 抛异常时调
        ``__aexit__``)。

        M1.3 在 M1.2 基础上: 增加 fail-safe 三策略落地(FailSafe
        FAIL_CLOSED / FAIL_OPEN / FAIL_FAST),BLOCKED 路径下 in_flight
        在 finally 块回收。

        English
        --------
        Engine internal: call each ``Slot.enter`` in Order; any raising
        ``SentinelBlockedError`` short-circuits and releases already-
        collected leases.

        **in_flight bookkeeping**: +1 on entry, -1 on exit (success or
        failure). The BLOCKED path's Outcome is constructed here, and
        ``__aexit__`` will NOT call ``_finalize_entry`` (Python does
        not call ``__aexit__`` when ``__aenter__`` raises).

        M1.3 builds on M1.2: full fail-safe three-strategy landing
        (FAIL_CLOSED / FAIL_OPEN / FAIL_FAST), and in_flight is
        decremented in the finally block even on the BLOCKED path.
        """
        # Bind context for downstream code that calls current_context()
        token = bind_current_context(context)
        self._ctx._context_token = token
        self._ctx.in_flight += 1
        try:
            for slot in self._chain.frozen_slots():
                try:
                    sub_lease = slot.enter(
                        resource=resource, context=context, args=args
                    )
                except SentinelError as e:
                    # SentinelBlockedError: 短路 + 释放已收 lease
                    self._ctx.last_error = e
                    await lease.release_all()
                    self._ctx.last_outcome = Outcome(
                        resource=resource,
                        kind=OutcomeKind.BLOCKED,
                        error=e,
                        elapsed_ns=0,
                        trace_id=context.trace_id,
                    )
                    raise
                except BaseException as e:
                    # Slot 内部非 Sentinel 异常 — fail_safe 处理
                    self._ctx._handle_slot_failure(slot, e, fail_safe=self._ctx.fail_safe)
                    if self._ctx.fail_safe is FailSafe.FAIL_CLOSED:
                        await lease.release_all()
                        raise
                    elif self._ctx.fail_safe is FailSafe.FAIL_OPEN:
                        # 记录 last_error 但继续;lease 不发(假装 Slot 放行)
                        # 因为我们没拿到 lease,所以 noop
                        continue
                    else:  # FAIL_FAST
                        await lease.release_all()
                        self._ctx.state = EngineState.FAILED
                        raise
                else:
                    lease.push(slot.order, sub_lease)
        except BaseException:
            # in_flight -1 + contextvars reset;即使 BLOCKED / FAIL_FAST
            # 路径,本方法退出后 __aexit__ 不会被调用,必须自己清理
            self._ctx.in_flight -= 1
            if self._ctx._context_token is not None:
                reset_current_context(self._ctx._context_token)  # type: ignore[arg-type]
                self._ctx._context_token = None
            raise

    async def _finalize_entry(
        self,
        *,
        entry_lease: EntryLease,
        resource: Resource,
        context: SentinelContext,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """中文
        ----
        Engine 内部: 逆序释放 lease,构造 Outcome,通知 Slot。

        M1.2 占位(M1.3 增加 CancelledError / observers / metrics 路径)。

        English
        --------
        Engine internal: reversely release leases, build Outcome,
        notify Slots.

        M1.2 placeholder (M1.3 adds CancelledError / observers /
        metrics paths).
        """
        start_ns = time.time_ns()  # rough; M1.3 will instrument properly
        await entry_lease.release_all()
        elapsed_ns = time.time_ns() - start_ns
        # Determine Outcome kind
        if exc is not None and isinstance(exc, asyncio.CancelledError):
            kind = OutcomeKind.CANCELLED
            error: BaseException | None = exc
            result = None
        elif exc is not None:
            kind = OutcomeKind.FAILED
            error = exc
            result = None
        else:
            # Was it blocked? Check last_outcome
            if (
                self._ctx.last_outcome is not None
                and self._ctx.last_outcome.resource is resource
                and self._ctx.last_outcome.kind is OutcomeKind.BLOCKED
            ):
                # Already set during _run_slot_chain_enter; keep
                self._ctx.last_outcome = self._ctx.last_outcome  # no-op
                # Notify slots of completion
                for slot in self._chain.frozen_slots():
                    with suppress(BaseException):
                        slot.on_entry_complete(self._ctx.last_outcome)
                # Reset context
                if self._ctx._context_token is not None:
                    reset_current_context(self._ctx._context_token)  # type: ignore[arg-type]
                    self._ctx._context_token = None
                self._ctx.in_flight -= 1
                return
            kind = OutcomeKind.SUCCEEDED
            error = None
            result = None
        outcome = Outcome(
            resource=resource,
            kind=kind,
            error=error,
            result=result,
            elapsed_ns=elapsed_ns,
            trace_id=context.trace_id,
        )
        self._ctx.last_outcome = outcome
        # Notify slots
        for slot in self._chain.frozen_slots():
            with suppress(BaseException):
                slot.on_entry_complete(outcome)
        # Reset context
        if self._ctx._context_token is not None:
            reset_current_context(self._ctx._context_token)  # type: ignore[arg-type]
            self._ctx._context_token = None
        self._ctx.in_flight -= 1


# Patch the _EngineContext to add the helper for slot failure handling
def _handle_slot_failure(
    self, slot: Slot, exc: BaseException, *, fail_safe: FailSafe  # noqa: ANN001
) -> None:
    """中文
    ----
    根据 ``fail_safe`` 策略处理 Slot 内部非 Sentinel 异常。

    - FAIL_CLOSED: 记录 ``last_error``,调用方抛出(已 ``raise``)
    - FAIL_OPEN: 记录 ``last_error``,调用方继续(假装放行)
    - FAIL_FAST: 切到 FAILED,Engine 不可再用

    English
    --------
    Handle non-Sentinel Slot exceptions per ``fail_safe`` strategy.

    - FAIL_CLOSED: record ``last_error``; caller raises.
    - FAIL_OPEN: record ``last_error``; caller continues (as if admit).
    - FAIL_FAST: transition to FAILED; Engine is unusable.
    """
    self.last_error = exc


_EngineContext._handle_slot_failure = _handle_slot_failure  # type: ignore[attr-defined]


__all__ = ["SentinelEngine", "FailSafe", "OutcomeObserver"]
