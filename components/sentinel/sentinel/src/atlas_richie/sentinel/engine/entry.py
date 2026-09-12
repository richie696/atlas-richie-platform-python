"""Sentinel Entry / EntryLease(M1.2)。

中文
----
``EntryRequest`` 是 Engine ``entry()`` 工厂方法的产物,实现 async
context manager;进入时调用 SlotChain 放行检查,退出时**逆序**释放所有
已 ``enter`` 的 Lease。``EntryLease`` 持有当前 entry 期间所有已发放
的 SlotLease,Engine 退出时调用 ``release_all()``。

设计要点:

- **async context manager** 是**唯一**公开 entry 形式(用户不能直接构造
  EntryRequest);失败路径用 ``try / except`` 走 Outcome 记录
- **Lease 收集**:每次 ``Slot.enter`` 返回的 Lease 收集到 ``self._leases``;
  任一 Slot 抛 ``SentinelBlockedError`` 即短路,Engine 进入 BLOCKED 分支
  并**逆序**释放已收集的 Lease
- **退出语义**:``__aexit__`` 必须**不**抛异常;释放过程的所有错误
  吞到 Engine.last_error,业务代码的 except 看到的总是干净的 Outcome

English
--------
Sentinel Entry / EntryLease (M1.2).

``EntryRequest`` is what ``Engine.entry()`` returns; it implements
the async context manager. On entry it runs the SlotChain admission
check, on exit it calls every collected ``SlotLease.release()`` in
**reverse** order. ``EntryLease`` holds all leases acquired during the
current entry; the Engine calls ``release_all()`` at exit.

Design points:

- **async context manager is the only** public entry form (users may
  not construct EntryRequest directly). Failure paths go through
  ``try / except`` and are recorded in Outcome.
- **Lease collection** — each ``Slot.enter`` return value is pushed
  to ``self._leases``; any Slot raising ``SentinelBlockedError``
  short-circuits, the Engine enters BLOCKED, and **reversely** releases
  collected leases.
- **Exit semantics** — ``__aexit__`` must **not** raise; any release
  failure is swallowed to Engine.last_error so user code's ``except``
  always sees a clean Outcome."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.decision import SlotLease
from ..model.enums import EngineState
from ..model.outcome import Outcome, OutcomeKind
from ..model.resource import Resource
from ..errors import SentinelError

if TYPE_CHECKING:
    from .sentinel_engine import SentinelEngine


# ---------------------------------------------------------------------------
# EntryLease — 持有所有 Slot 发放的 lease,逆序 release
# ---------------------------------------------------------------------------


@dataclass
class EntryLease:
    """中文
    ----
    一次 entry 期间收集的所有 ``SlotLease``(由 Engine 持有,业务代码不
    直接交互)。

    内部:

    - ``_leases`` — list of (order, lease) tuples;Engine 退出时按
      order 降序遍历 ``lease.release()``
    - ``_released`` — 幂等标记,防止重复 release
    - ``_release_errors`` — 释放过程抛出的异常(已 swallow),不外泄

    English
    --------
    All ``SlotLease``s collected during a single entry (held by the
    Engine; business code does not interact with it directly).

    Internal:

    - ``_leases`` — list of (order, lease) tuples; the Engine walks in
      order-descending at exit.
    - ``_released`` — idempotency flag; prevents double release.
    - ``_release_errors`` — exceptions raised during release (swallowed,
      not propagated).
    """

    _leases: list[tuple[int, SlotLease]] = field(default_factory=list)
    _released: bool = False
    _release_errors: list[BaseException] = field(default_factory=list)

    def push(self, order: int, lease: SlotLease) -> None:
        """中文
        ----
        追加一个 Slot 发放的 lease。Engine 在每个 Slot enter 成功后调用。

        English
        --------
        Push a lease returned by a Slot. Called by the Engine after
        each Slot ``enter`` success.
        """
        if self._released:
            # Entry 已经退出,不应该再 push;忽略但不抛
            return
        self._leases.append((order, lease))

    @property
    def leases(self) -> list[tuple[int, SlotLease]]:
        """中文
        ----
        当前已收集的 lease 列表(只读,测试 / 调试用)。

        English
        --------
        Currently collected leases (read-only; for tests / debug).
        """
        return list(self._leases)

    async def release_all(self) -> None:
        """中文
        ----
        **逆序**释放所有 lease。**幂等**:重复调用安全。

        任一 lease 释放抛错,**不**外泄,记录到 ``_release_errors``。

        English
        --------
        Release all leases in **reverse** order. **Idempotent**:
        safe to call multiple times.

        If any lease's ``release()`` raises, the exception is **not**
        propagated; it is recorded in ``_release_errors``.
        """
        if self._released:
            return
        self._released = True
        # Reverse: last-acquired (highest effective order) released first
        for _order, lease in reversed(self._leases):
            try:
                await lease.release()
            except BaseException as e:  # noqa: BLE001 — intentional swallow
                self._release_errors.append(e)


# ---------------------------------------------------------------------------
# EntryRequest — async context manager wrapping a single entry
# ---------------------------------------------------------------------------


class EntryRequest:
    """中文
    ----
    单次 entry 的 async 上下文管理器。**仅**由 ``SentinelEngine.entry()``
    构造;业务代码不能直接 ``EntryRequest(...)``。

    用法::

        async with engine.entry(Resource("orders-api")) as entry:
            result = await business_call()
            # 业务异常会被记录到 entry.outcome,统一化为 Outcome.FAILED

    ``__aenter__`` 阶段按 Order 调用所有 Slot 的 ``enter``;任何一个
    抛 ``SentinelBlockedError`` 即短路,Engine 构造 BLOCKED Outcome。
    ``__aexit__`` 阶段逆序释放所有 lease,记录 Outcome。

    English
    --------
    Async context manager for a single entry. **Only** constructed by
    ``SentinelEngine.entry()``; user code may not call ``EntryRequest(...)``
    directly.

    Usage::

        async with engine.entry(Resource("orders-api")) as entry:
            result = await business_call()
            # business exceptions are recorded in entry.outcome,
            # normalized to Outcome.FAILED.

    ``__aenter__`` calls every Slot's ``enter`` in Order; any raising
    ``SentinelBlockedError`` short-circuits, the Engine builds a
    BLOCKED Outcome. ``__aexit__`` reversely releases all leases and
    finalizes the Outcome."""

    def __init__(
        self,
        *,
        engine: "SentinelEngine",
        resource: Resource,
        args: InvocationArguments | None,
        context: SentinelContext,
    ) -> None:
        self._engine = engine
        self._resource = resource
        self._args = args
        self._context = context
        self._lease = EntryLease()
        self._outcome: Outcome | None = None
        self._entered: bool = False
        self._exited: bool = False

    @property
    def resource(self) -> Resource:
        return self._resource

    @property
    def context(self) -> SentinelContext:
        return self._context

    @property
    def outcome(self) -> Outcome | None:
        """中文
        ----
        退出后构造的 Outcome;``__aexit__`` 之前为 ``None``。

        English
        --------
        Outcome constructed at exit; ``None`` before ``__aexit__``.
        """
        return self._outcome

    async def __aenter__(self) -> "EntryRequest":
        if self._entered:
            return self
        self._entered = True
        # Engine entry phase: run SlotChain.enter, collect leases
        try:
            await self._engine._run_slot_chain_enter(
                resource=self._resource,
                context=self._context,
                args=self._args,
                lease=self._lease,
            )
        except SentinelError as e:
            # Slot 拒绝 / Engine lifecycle 错误:
            # Engine 内部已构造 BLOCKED outcome,直接挂到 entry 上后
            # 重抛 — 用户既可以 except FlowBlocked,也可以读 entry.outcome
            self._outcome = self._engine.last_outcome
            self._exited = True  # 防止 __aexit__ 重复 finalize
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._exited:
            return
        self._exited = True
        # Engine exit phase: build outcome, release leases, notify slots
        await self._engine._finalize_entry(
            entry_lease=self._lease,
            resource=self._resource,
            context=self._context,
            exc_type=exc_type,
            exc=exc,
            tb=tb,
        )
        self._outcome = self._engine.last_outcome
        # Don't suppress user exception; we only set self._outcome for
        # them to inspect. Let the original exc propagate naturally.


__all__ = ["EntryLease", "EntryRequest"]
