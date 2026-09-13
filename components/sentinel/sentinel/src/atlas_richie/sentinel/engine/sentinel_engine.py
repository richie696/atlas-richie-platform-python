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
from typing import TYPE_CHECKING, TypeAlias

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

if TYPE_CHECKING:
    from ..rules.repository import RuleRepository
    from ..source._supervisor.binding import _RuleSourceBinding
    from ..source._supervisor.supervisor import RuleSourceSupervisor
    from ..source.rule_source import (
        LegacyRuleSource,
        RuleSourceAssembly,
    )


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
    # NOTE: ``_context_token`` previously lived here, but that caused a
    # bug under concurrent entries: each entry's asyncio.Task has its
    # own contextvars.Context, so a shared per-engine token was
    # clobbered by the second entry. The token is now stored on
    # ``EntryLease`` (per-entry); see ``engine.entry`` -> ``EntryRequest``.
    # This field is kept as a sentinel for backward grep; do not rely
    # on it. Will be removed in a follow-up cleanup.


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
        # M6.1.0d-1: rule source mode tracking (mutually exclusive).
        # _has_legacy == True means install_legacy_source was used;
        # _has_assembled == True means assemble_sources was used.
        # Both cannot be True (multimode_conflict).
        self._has_legacy: bool = False
        self._has_assembled: bool = False
        # _legacy_source: keep a reference for aclose() to call
        # source.stop() (1.0 行为). _supervisor: keep a reference for
        # aclose() to await supervisor.aclose().
        self._legacy_source: "LegacyRuleSource | None" = None
        self._supervised_repository: "RuleRepository | None" = None
        self._supervisor: "RuleSourceSupervisor | None" = None

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
        # M6.1.0d-1: close attached Supervisor / legacy source before
        # the SHUTDOWN transition so observers can rely on
        # ``state is SHUTDOWN`` → all sources closed.
        await self._close_attached_sources()
        # Transition to SHUTDOWN regardless of whether in-flight drained
        async with self._state_lock:
            self._ctx.state = EngineState.SHUTDOWN

    async def aclose(self) -> None:
        """中文
        ----
        ``close()`` 的别名;匹配 Python async close 协议
        (e.g. 配合 ``async with engine:`` 之后的清理)。

        **M6.1.0d-1 增强**: 如果 Engine 持有 Supervisor (经
        ``assemble_sources``) 或 legacy source (经
        ``install_legacy_source``), 在状态转 SHUTDOWN 前先关闭它们:

        - Supervisor: ``await supervisor.aclose()`` 等待所有 source
          task 关闭 (decision 2, ``rule_source_activation.md`` §5.2)
        - Legacy source: ``source.stop()`` (1.0 行为, 同步)
        - **不**关闭 ``RuleRepository`` (Repository 是被动容器)

        English
        --------
        Alias of ``close()``; matches Python's async close protocol
        (e.g. for use after ``async with engine:`` block exit).

        **M6.1.0d-1 enhancement**: if the Engine holds a Supervisor
        (via ``assemble_sources``) or a legacy source (via
        ``install_legacy_source``), close them before transitioning to
        SHUTDOWN:

        - Supervisor: ``await supervisor.aclose()`` waits for all
          source tasks to close (decision 2,
          ``rule_source_activation.md`` §5.2).
        - Legacy source: ``source.stop()`` (1.0 behavior, sync).
        - **Does not** close the ``RuleRepository`` (passive container).
        """
        await self.close()

    async def _close_attached_sources(self) -> None:
        """中文
        ----
        M6.1.0d-1 内部: ``close()`` 期间关闭 Supervisor 与 legacy
        source。Repository **不**关闭 (被动容器)。

        调用者: ``close()`` 在 in-flight drain 完成 + 状态转 SHUTDOWN
        前调本方法。

        English
        --------
        M6.1.0d-1 internal: close Supervisor + legacy source during
        ``close()``. Repository is **not** closed (passive container).

        Caller: ``close()`` invokes this after in-flight drain and
        before SHUTDOWN transition.
        """
        # 1. Supervisor 优先 (如果存在)
        if self._supervisor is not None:
            try:
                await self._supervisor.aclose()
            except BaseException:
                # aclose 失败被 Supervisor 内部 swallow, 这里再包一层保险
                pass
        # 2. Legacy source 关闭 (1.0 行为, 同步 stop)
        if self._legacy_source is not None:
            try:
                self._legacy_source.stop()
            except BaseException:
                # 1.0 source.stop() 自身应幂等; 万一抛错 swallow
                pass

    # ------------------------------------------------------------------
    # Rule source assembly (M6.1.0d-1) — assemble_sources + install_legacy_source
    # ------------------------------------------------------------------

    async def assemble_sources(
        self,
        assemblies: "Sequence[RuleSourceAssembly]",
        *,
        repository: "RuleRepository",
    ) -> None:
        """中文
        ----
        多源仲裁入口; 仅接受 :class:`SnapshotRuleSource`。

        **互斥约束**: 调用前 Engine 必须未通过 ``install_legacy_source``
        安装任何 Legacy 1.0 Source; 违反抛
        ``SentinelConfigurationError("multimode_conflict")``。

        **lifecycle gate**: 必须在 ``READY`` 状态 (即
        ``__aenter__`` 完成后); 在 ``CREATED`` / ``SHUTTING_DOWN`` /
        ``SHUTDOWN`` / ``FAILED`` 状态抛 ``SentinelLifecycleError``。

        **重复调用**: 第二次调用抛 ``SentinelConfigurationError``;
        若要替换 active source, 等 M6.1+ future ADR 显式允许
        (M6.1.0d-1 阶段**不**支持"重新装配")。

        **``repository`` 必填**: ``repository=None`` 抛
        ``SentinelConfigurationError("repository_required")``;
        default-deny 拒绝所有权不明的可选参数 (决策 5)。

        流程:

        1. 校验 lifecycle + 互斥 + repository
        2. 把 ``assemblies`` 转换为私有 ``_RuleSourceBinding`` 列表
           (priority 唯一性由 Supervisor.__init__ 内部校验, 重复抛
           ``SentinelConfigurationError("duplicate_priority")``)
        3. 构造 :class:`RuleSourceSupervisor` 并 ``await supervisor.start()``
        4. 持有 supervisor 引用, 供 ``aclose()`` 关闭

        English
        --------
        Multi-source arbitration entry; only accepts
        :class:`SnapshotRuleSource`.

        **Mutual exclusion**: the Engine must not already hold a 1.0
        legacy Source installed via ``install_legacy_source``;
        violation raises
        ``SentinelConfigurationError("multimode_conflict")``.

        **Lifecycle gate**: must be in ``READY`` state (i.e. after
        ``__aenter__``); ``CREATED`` / ``SHUTTING_DOWN`` / ``SHUTDOWN``
        / ``FAILED`` raises ``SentinelLifecycleError``.

        **Repeated calls**: a second call raises
        ``SentinelConfigurationError``; replacing the active source
        awaits a future M6.1+ ADR (M6.1.0d-1 does **not** support
        "reassembly").

        **``repository`` required**: ``repository=None`` raises
        ``SentinelConfigurationError("repository_required")``;
        default-deny rejects ambiguous-ownership optional parameters
        (decision 5).

        Flow:

        1. Validate lifecycle + mutual exclusion + repository.
        2. Convert ``assemblies`` to private ``_RuleSourceBinding``
           list (priority uniqueness is validated by
           ``Supervisor.__init__``; duplicate raises
           ``SentinelConfigurationError("duplicate_priority")``).
        3. Build :class:`RuleSourceSupervisor` and ``await
           supervisor.start()``.
        4. Hold the supervisor reference for ``aclose()`` to close.
        """
        # 1. lifecycle gate
        if self._ctx.state is not EngineState.READY:
            raise SentinelLifecycleError(
                f"assemble_sources() only allowed in READY state "
                f"(current: {self._ctx.state.value})",
                from_state=self._ctx.state.value,
                to_state="assemble_sources",
                component="engine",
            )
        # 2. 互斥: 已有 legacy 源
        if self._has_legacy:
            raise SentinelConfigurationError(
                "Cannot assemble_sources() after install_legacy_source() "
                "(multimode_conflict: legacy 1.0 source already installed)",
                reason="multimode_conflict",
            )
        # 3. 重复调用
        if self._has_assembled:
            raise SentinelConfigurationError(
                "assemble_sources() called twice on the same engine "
                "(M6.1.0d-1 does not support reassembly; close engine "
                "and create a new one)",
                reason="already_assembled",
            )
        # 4. repository 必填
        if repository is None:
            raise SentinelConfigurationError(
                "assemble_sources() requires a non-None repository "
                "(default-deny: ownership must be explicit)",
                field="repository",
                reason="repository_required",
            )
        # 5. 校验 assemblies 列表
        if not assemblies:
            raise SentinelConfigurationError(
                "assemble_sources() requires at least one assembly",
                field="assemblies",
                reason="empty_assemblies",
            )
        # 6. 转换为 _RuleSourceBinding
        bindings: list["_RuleSourceBinding"] = []
        for a in assemblies:
            bindings.append(
                _rule_source_binding_from_assembly(a)
            )
        # 7. 构造 Supervisor (内部校验 priority 唯一 / 非负)
        from ..source._supervisor.supervisor import RuleSourceSupervisor
        supervisor = RuleSourceSupervisor(
            bindings=bindings,
            repository=repository,
        )
        # 8. 启动 (在 Supervisor.__init__ 中 priority 唯一性已校验;
        #    失败抛 SentinelConfigurationError, 此处 _has_assembled 还未设)
        await supervisor.start()
        # 9. 提交状态 (set last, so partial failure leaves Engine clean)
        self._supervisor = supervisor
        self._supervised_repository = repository
        self._has_assembled = True

    def install_legacy_source(
        self,
        source: "LegacyRuleSource",
        *,
        repository: "RuleRepository",
    ) -> None:
        """中文
        ----
        1.0 兼容入口; 不经 Supervisor; 等同 1.0 行为。

        **互斥约束**: 调用前 Engine 必须未通过 ``assemble_sources()``
        安装任何 SnapshotRuleSource; 违反抛
        ``SentinelConfigurationError("multimode_conflict")``。

        **lifecycle gate**: 必须在 ``CREATED`` 状态 (1.0 用户典型用法
        是: ``engine = SentinelEngine()`` → ``install_legacy_source``
        → ``async with engine:``); 在 ``READY`` / ``SHUTTING_DOWN`` /
        ``SHUTDOWN`` / ``FAILED`` 状态抛 ``SentinelLifecycleError``。

        **``repository`` 必填**: ``repository=None`` 抛
        ``SentinelConfigurationError("repository_required")``;
        default-deny 拒绝所有权不明的可选参数 (决策 5)。

        行为:

        1. 校验 lifecycle + 互斥 + repository
        2. ``source.start(repository)`` (1.0 直连 ``RuleRepository.apply
           _snapshot``)
        3. 持有 ``source`` 引用, 供 ``aclose()`` 关闭 (``source.stop()``)

        **不**经 Supervisor, **不**支持多源仲裁, **不**发 activation
        fact; 1.x 全程保留 1.0 行为锁定。

        English
        --------
        1.0 compatibility entry; bypasses the Supervisor; equivalent to
        1.0 behavior.

        **Mutual exclusion**: the Engine must not already hold a
        ``SnapshotRuleSource`` installed via ``assemble_sources()``;
        violation raises
        ``SentinelConfigurationError("multimode_conflict")``.

        **Lifecycle gate**: must be in ``CREATED`` state (1.0 users
        typically do: ``engine = SentinelEngine()`` →
        ``install_legacy_source`` → ``async with engine:``); ``READY`` /
        ``SHUTTING_DOWN`` / ``SHUTDOWN`` / ``FAILED`` raises
        ``SentinelLifecycleError``.

        **``repository`` required**: ``repository=None`` raises
        ``SentinelConfigurationError("repository_required")``;
        default-deny rejects ambiguous-ownership optional parameters
        (decision 5).

        Behavior:

        1. Validate lifecycle + mutual exclusion + repository.
        2. ``source.start(repository)`` (1.0 direct call to
           ``RuleRepository.apply_snapshot``).
        3. Hold a reference to ``source`` for ``aclose()`` to call
           ``source.stop()``.

        **Bypasses** the Supervisor, **does not** support multi-source
        arbitration, **does not** emit activation facts; 1.x preserves
        1.0 behavior lock.
        """
        # 1. lifecycle gate: CREATED only
        if self._ctx.state is not EngineState.CREATED:
            raise SentinelLifecycleError(
                f"install_legacy_source() only allowed in CREATED state "
                f"(current: {self._ctx.state.value})",
                from_state=self._ctx.state.value,
                to_state="install_legacy_source",
                component="engine",
            )
        # 2. 互斥: 已有 SnapshotRuleSource
        if self._has_assembled:
            raise SentinelConfigurationError(
                "Cannot install_legacy_source() after assemble_sources() "
                "(multimode_conflict: multi-source assembly already installed)",
                reason="multimode_conflict",
            )
        # 3. 重复调用
        if self._has_legacy:
            raise SentinelConfigurationError(
                "install_legacy_source() called twice on the same engine "
                "(M6.1.0d-1 does not support multiple legacy sources)",
                reason="legacy_already_installed",
            )
        # 4. repository 必填
        if repository is None:
            raise SentinelConfigurationError(
                "install_legacy_source() requires a non-None repository "
                "(default-deny: ownership must be explicit)",
                field="repository",
                reason="repository_required",
            )
        # 5. source 必填
        if source is None:
            raise SentinelConfigurationError(
                "install_legacy_source() requires a non-None source",
                field="source",
                reason="source_required",
            )
        # 6. 1.0 行为: source.start(repository) 直连
        source.start(repository)
        # 7. 提交状态
        self._legacy_source = source
        self._supervised_repository = repository
        self._has_legacy = True

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
        # Store the per-entry token on the lease (NOT on the engine) so
        # concurrent entries in different asyncio.Tasks do not clobber
        # each other's tokens.
        lease._context_token = token
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
            if lease._context_token is not None:
                reset_current_context(lease._context_token)
                lease._context_token = None
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
        # Surface any release error to engine.last_error for observability
        # (release errors are swallowed by EntryLease; we re-raise them
        # to last_error so a downstream metric / health check can see them).
        rel_err = entry_lease.last_release_error()
        if rel_err is not None:
            self._ctx.last_error = rel_err
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
                # Reset per-entry context (token lives on the lease)
                if entry_lease._context_token is not None:
                    reset_current_context(entry_lease._context_token)
                    entry_lease._context_token = None
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
        # Reset per-entry context (token lives on the lease)
        if entry_lease._context_token is not None:
            reset_current_context(entry_lease._context_token)
            entry_lease._context_token = None
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


# ---------------------------------------------------------------------------
# M6.1.0d-1: assembly DTO -> C-layer private binding conversion
# ---------------------------------------------------------------------------


def _rule_source_binding_from_assembly(
    assembly: "RuleSourceAssembly",
) -> "_RuleSourceBinding":
    """中文
    ----
    Engine 内部: 把公开 immutable assembly DTO 转换为 C 层私有
    ``_RuleSourceBinding``。

    - ``source_id`` 从 ``assembly.source.source_id`` 取
      (配置时 stable 字符串; rule_source_activation.md §7)
    - ``priority`` 与 ``failover_after`` 直接透传
      (``RuleSourceAssembly.__post_init__`` 已校验 ≥ 0)

    不做 priority 唯一性校验 — 那是 ``RuleSourceSupervisor.__init__``
    内部职责 (重复 = 公共契约违反, 抛
    ``SentinelConfigurationError("duplicate_priority")``)。

    English
    --------
    Engine internal: convert public immutable assembly DTO to the
    C-layer private ``_RuleSourceBinding``.

    - ``source_id`` is read from ``assembly.source.source_id``
      (user-supplied stable string; rule_source_activation.md §7).
    - ``priority`` and ``failover_after`` are passed through
      (``RuleSourceAssembly.__post_init__`` already validated ≥ 0).

    Priority uniqueness is **not** validated here — that is the
    responsibility of ``RuleSourceSupervisor.__init__`` (duplicate =
    public contract violation; raises
    ``SentinelConfigurationError("duplicate_priority")``).
    """
    from ..source._supervisor.binding import _RuleSourceBinding
    return _RuleSourceBinding(
        source_id=assembly.source.source_id,
        source=assembly.source,
        priority=assembly.priority,
        failover_after=assembly.failover_after,
    )


__all__ = ["SentinelEngine", "FailSafe", "OutcomeObserver"]
