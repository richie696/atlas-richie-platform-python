"""C 层私有: ``RuleSourceSupervisor`` 多源仲裁 (M6.1.0d-1)。

中文
----
**禁止外部 import** (DESIGN §10.3 L1081-1089 / API delta v3 决策 1)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import RuleSourceSupervisor  # noqa

``RuleSourceSupervisor`` 是 M6.1 主包**唯一**理解 source priority 的对象
(DESIGN §10.3 L1065-1070)。Engine 公开装配入口
``SentinelEngine.assemble_sources()`` 把 ``Sequence[RuleSourceAssembly]``
校验后转换为 ``Sequence[_RuleSourceBinding]`` 注入本 Supervisor。

**职责**:

1. 启动每个 ``SnapshotRuleSource.snapshots()`` 异步迭代器为后台 task
2. 跟踪每个 source 的 ready / stale 状态
3. 选举当前 active (最高 priority 的 ready source)
4. 通过 ``RuleRepository.apply_snapshot`` apply active snapshot
5. 在 active 实际变更时 emit ``RuleSourceActivation`` (3 条件 AND)
6. active stale 时, 等待 ``failover_after`` 窗口才切到次高 priority
   ready source
7. ``aclose()`` 关闭所有 source task + 各 source 的 ``aclose()``;
   **不**关闭 repository (Repository 是被动容器)

**不**职责:

- 跨语言 wire 投影 (M6.5.7 envelope 范围)
- 规则正文校验 (``RuleRepository`` 负责)
- 跨进程传输 (``M6.5.1`` 父协议 transport 范围)

**实现要点**:

- 内部 lock (asyncio.Lock) 保护 ``_active_source_id`` 与 ``_runtimes`` 切换
- 每个 source task 独立运行; snapshot yield 触发 ``_maybe_switch_active``
- initial election 在 ``start()`` 末尾用 ``asyncio.Event`` 同步
- observer 异常隔离由 ``_RuleSourceActivationBus`` 保证 (本模块不重复)
- 不持有 ``RuleRepository`` 长期引用外的额外资源

English
--------
**Do not import from outside** (DESIGN §10.3 L1081-1089 / API delta v3
decision 1)::

    # DO NOT (extension / user code)
    from atlas_richie.sentinel.source._supervisor import RuleSourceSupervisor  # noqa

``RuleSourceSupervisor`` is the **only** object in the M6.1 main wheel
that understands source priority (DESIGN §10.3 L1065-1070). The Engine
public entry ``SentinelEngine.assemble_sources()`` validates the
``Sequence[RuleSourceAssembly]`` and converts it into a
``Sequence[_RuleSourceBinding]`` that is injected here.

**Responsibilities**:

1. Launch each ``SnapshotRuleSource.snapshots()`` async iterator as a
   background task.
2. Track each source's ready / stale state.
3. Elect the current active (highest priority ready source).
4. Apply the active snapshot via ``RuleRepository.apply_snapshot``.
5. Emit ``RuleSourceActivation`` on actual active change (3-condition AND).
6. On active stale, wait the ``failover_after`` window before switching
   to the next-highest priority ready source.
7. ``aclose()`` closes all source tasks + each source's ``aclose()``;
   **does not** close the repository (passive container).

**Not** responsible for:

- Cross-language wire projection (M6.5.7 envelope scope).
- Rule body validation (handled by ``RuleRepository``).
- Cross-process transport (M6.5.1 父协议 transport scope).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from ...errors import SentinelConfigurationError
from .activation import RuleSourceActivation
from .binding import _RuleSourceBinding
from .observer import _RuleSourceActivationBus

if TYPE_CHECKING:
    from ...rules.repository import RuleRepository
    from ...rules.snapshot import RuleSnapshot


class _SourceState:
    """中文
    ----
    Per-source runtime 状态 (C 层私有)。

    ``state`` 转移::

        pending  ──[first snapshot applied]──▶  ready
        ready    ──[task exception]──────────▶  stale
        ready    ──[iterator ends]───────────▶  stale
        ready    ──[aclose]──────────────────▶  closed
        stale    ──[aclose]──────────────────▶  closed

    English
    --------
    Per-source runtime state (C-layer private).

    ``state`` transitions::

        pending  ──[first snapshot applied]──▶  ready
        ready    ──[task exception]──────────▶  stale
        ready    ──[iterator ends]───────────▶  stale
        ready    ──[aclose]──────────────────▶  closed
        stale    ──[aclose]──────────────────▶  closed
    """

    PENDING = "pending"
    READY = "ready"
    STALE = "stale"
    CLOSED = "closed"


class _SourceRuntime:
    """中文
    ----
    C 层私有: 一个 binding 的运行时状态 + 后台 task 引用。

    English
    --------
    C-layer private: one binding's runtime state + background task
    reference.
    """

    __slots__ = (
        "binding",
        "task",
        "state",
        "last_snap",
        "stale_at_monotonic",
        "error",
    )

    def __init__(self, binding: _RuleSourceBinding) -> None:
        self.binding = binding
        self.task: asyncio.Task | None = None
        self.state: str = _SourceState.PENDING
        self.last_snap: "RuleSnapshot | None" = None
        self.stale_at_monotonic: float | None = None
        self.error: BaseException | None = None


class RuleSourceSupervisor:
    """中文
    ----
    C 层私有: 多源仲裁 + active 选择 + activation fact emit。

    **生命周期**:

    1. ``__init__`` 同步校验 bindings (priority 唯一 / 非负 /
       ``failover_after`` 非负)
    2. ``start()`` 启动所有 source task, 等待首个 ready, 选举 initial
       active, emit ``RuleSourceActivation(reason="initial")`` (若有)
    3. 运行中: source snapshot yield 触发 ``_maybe_switch_active``;
       source stale 触发 failover 检查
    4. ``aclose()`` 幂等关闭: 取消 task, 等待 task 退出, 调各 source
       ``aclose()``; **不**关闭 repository

    English
    --------
    C-layer private: multi-source arbitration + active selection +
    activation fact emission.

    **Lifecycle**:

    1. ``__init__`` validates bindings synchronously (priority unique /
       non-negative / ``failover_after`` non-negative).
    2. ``start()`` starts all source tasks, awaits first ready, elects
       initial active, emits ``RuleSourceActivation(reason="initial")``
       (if any).
    3. Runtime: source snapshot yield triggers
       ``_maybe_switch_active``; source going stale triggers failover
       check.
    4. ``aclose()`` idempotent close: cancel tasks, wait for them to
       exit, call each source's ``aclose()``; **does not** close the
       repository.
    """

    def __init__(
        self,
        bindings: "list[_RuleSourceBinding]",
        repository: "RuleRepository",
        bus: "_RuleSourceActivationBus | None" = None,
    ) -> None:
        if not bindings:
            raise SentinelConfigurationError(
                "RuleSourceSupervisor: at least one binding is required",
                reason="empty_bindings",
            )
        # 1. priority 唯一性 + 非负 + failover_after 非负
        seen_priorities: dict[int, str] = {}
        for b in bindings:
            if b.priority < 0:
                raise SentinelConfigurationError(
                    f"RuleSourceSupervisor: priority must be >= 0 "
                    f"(source_id={b.source_id!r}, priority={b.priority})",
                    field="priority",
                    reason="negative_priority",
                )
            if b.failover_after.total_seconds() < 0:
                raise SentinelConfigurationError(
                    f"RuleSourceSupervisor: failover_after must be >= 0 "
                    f"(source_id={b.source_id!r}, failover_after="
                    f"{b.failover_after})",
                    field="failover_after",
                    reason="negative_failover_after",
                )
            if b.priority in seen_priorities:
                raise SentinelConfigurationError(
                    f"RuleSourceSupervisor: duplicate priority "
                    f"{b.priority} (source_ids={seen_priorities[b.priority]!r}, "
                    f"{b.source_id!r})",
                    field="priority",
                    reason="duplicate_priority",
                )
            seen_priorities[b.priority] = b.source_id
        # 2. 状态
        self._bindings: list[_RuleSourceBinding] = list(bindings)
        self._by_id: dict[str, _RuleSourceBinding] = {b.source_id: b for b in bindings}
        self._runtimes: dict[str, _SourceRuntime] = {
            b.source_id: _SourceRuntime(b) for b in bindings
        }
        # 3. repository 持有引用 (调用 apply_snapshot; 不关闭)
        self._repository = repository
        # 4. bus (默认新建; 测试可注入)
        self._bus: _RuleSourceActivationBus = bus or _RuleSourceActivationBus()
        # 5. 内部状态
        self._active_source_id: str | None = None
        self._active_lock = asyncio.Lock()
        self._initial_event = asyncio.Event()
        self._closed: bool = False
        self._start_completed: bool = False
        # 6. 启动超时 (避免 source 完全没 ready 时 hang)
        self._initial_timeout_sec: float = 10.0

    # ------------------------------------------------------------------
    # Public (C-layer) entry points — all called by SentinelEngine only.
    # ------------------------------------------------------------------

    @property
    def bus(self) -> _RuleSourceActivationBus:
        """中文
        ----
        内部 bus 引用 (C 层测试 / future metrics 用)。

        English
        --------
        Internal bus reference (for C-layer tests / future metrics).
        """
        return self._bus

    @property
    def active_source_id(self) -> str | None:
        """中文
        ----
        当前 active source id; 未选出时为 ``None``。

        English
        --------
        Current active source id; ``None`` before any active elected.
        """
        return self._active_source_id

    @property
    def is_closed(self) -> bool:
        """中文
        ----
        ``aclose()`` 是否已经调用过 (幂等检查)。

        English
        --------
        Whether ``aclose()`` has been called (idempotency check).
        """
        return self._closed

    def get_state(self, source_id: str) -> str:
        """中文
        ----
        查询某 source 的当前状态 (C 层测试用)。

        English
        --------
        Query a source's current state (for C-layer tests).
        """
        runtime = self._runtimes.get(source_id)
        if runtime is None:
            raise KeyError(f"unknown source_id: {source_id!r}")
        return runtime.state

    async def start(self) -> None:
        """中文
        ----
        启动所有 source task, 等待首个 ready, 选举 initial active。

        1. 校验 ``_closed`` (重复 start 抛错)
        2. 为每个 binding 启动 ``_consume`` 后台 task
        3. 等待 ``_initial_event`` (任一 source 进入 ready 时 set)
           或 ``_initial_timeout_sec`` 超时
        4. 选举: 若 active 仍为 ``None``, 按 priority 降序选首个
           ready source 作为 initial active, emit
           ``RuleSourceActivation(reason="initial")``
        5. 选举后 ``start()`` 立即返回, 后台 task 继续运行

        English
        --------
        Start all source tasks, wait for first ready, elect initial
        active.

        1. Assert not ``_closed`` (double-start raises).
        2. Launch ``_consume`` background task per binding.
        3. Wait on ``_initial_event`` (set when any source enters ready)
           or ``_initial_timeout_sec`` timeout.
        4. Elect: if active is still ``None``, pick the highest priority
           ready source as initial active, emit
           ``RuleSourceActivation(reason="initial")``.
        5. Return after election; background tasks continue.
        """
        if self._closed:
            raise SentinelConfigurationError(
                "RuleSourceSupervisor.start() called after aclose()",
                reason="supervisor_closed",
            )
        # 1. 启动所有 task
        for b in self._bindings:
            runtime = self._runtimes[b.source_id]
            runtime.task = asyncio.create_task(
                self._consume(runtime),
                name=f"sentinel-source-{b.source_id}",
            )
        # 2. 等待首个 ready (或超时)
        try:
            await asyncio.wait_for(
                self._initial_event.wait(),
                timeout=self._initial_timeout_sec,
            )
        except asyncio.TimeoutError:
            # 没有任何 source 进入 ready; 不选举, 留给后续 _consume 自己 emit
            pass
        # 3. 选举 initial active (若 _consume 还没设上)
        await self._elect_initial_active()
        # 4. 标记 start() 完成; 之后 _consume 遇到 current=None 会自行激活
        self._start_completed = True

    async def aclose(self) -> None:
        """中文
        ----
        幂等关闭: 取消 task, 等待 task 退出, 调各 source ``aclose()``。

        **不**关闭 ``RuleRepository`` (Repository 是被动容器)。

        English
        --------
        Idempotent close: cancel tasks, wait for tasks to exit, call
        each source's ``aclose()``.

        **Does not** close ``RuleRepository`` (passive container).
        """
        if self._closed:
            return
        self._closed = True
        # 1. 收集所有 task
        tasks: list[asyncio.Task] = [
            r.task for r in self._runtimes.values() if r.task is not None
        ]
        # 2. 取消
        for t in tasks:
            t.cancel()
        # 3. 等待 task 退出
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, BaseException):
                # CancelledError 是预期; 其它异常已被 _consume 记录
                pass
        # 4. 调各 source 的 aclose(); 各自异常隔离
        for b in self._bindings:
            try:
                await b.source.aclose()
            except BaseException:
                # 异常隔离: 单 source aclose 失败不影响其它 source
                pass
        # 5. 标记 runtime state
        for runtime in self._runtimes.values():
            runtime.state = _SourceState.CLOSED

    # ------------------------------------------------------------------
    # Internal: per-source consume loop
    # ------------------------------------------------------------------

    async def _consume(self, runtime: _SourceRuntime) -> None:
        """中文
        ----
        单 source 消费循环: 迭代 ``snapshots()``, apply 到 repository,
        触发 active 切换。

        Stale 判定 (rule_source_activation.md §1.1 / DESIGN §10.3) 只在
        异常 / 长时间没 yield 时发生; **iterator 自然结束不触发 stale**
        (这是 source 实现细节, 不是 stale 信号)。Source 标 READY 后
        保持 READY 直到 aclose。

        ``CancelledError`` 是关闭路径, 保留原 state (由 aclose 统一标
        closed)。

        English
        --------
        Per-source consume loop: iterate ``snapshots()``, apply to
        repository, trigger active switch.

        Stale determination (rule_source_activation.md §1.1 / DESIGN
        §10.3) only fires on exception / long-no-yield; **natural
        iterator end does NOT trigger stale** (this is a source
        implementation detail, not a stale signal). A source marked
        READY stays READY until aclose.

        ``CancelledError`` is the close path; original state is
        preserved (aclose unifies to closed).
        """
        binding = runtime.binding
        try:
            async for snap in binding.source.snapshots():
                if self._closed:
                    return
                # 1. apply 到 repository
                applied = self._repository.apply_snapshot(snap)
                if not applied:
                    # Repository 拒绝 (e.g. older version / checksum
                    # collision); 不更新 ready 状态
                    continue
                # 2. 更新 runtime state
                was_ready = runtime.state == _SourceState.READY
                runtime.state = _SourceState.READY
                runtime.last_snap = snap
                runtime.stale_at_monotonic = None
                if not was_ready:
                    # 首次 ready: set initial event
                    self._initial_event.set()
                # 3. 尝试切 active
                await self._maybe_switch_active(runtime, snap)
            # 4. 迭代器自然结束: 不触发 stale, 不 emit (spec 明确
            #    "iterator 结束" 不在 stale 触发条件中)。Last-yielded
            #    snapshot 保持 READY, last-known-good 由 Repository
            #    保留。
        except asyncio.CancelledError:
            # 关闭路径: 保留原 state (由 aclose 统一标记为 closed)
            raise
        except BaseException as e:  # noqa: BLE001 — record + mark stale
            runtime.state = _SourceState.STALE
            runtime.stale_at_monotonic = time.monotonic()
            runtime.error = e
            await self._maybe_switch_active(runtime, runtime.last_snap)

    # ------------------------------------------------------------------
    # Internal: active selection
    # ------------------------------------------------------------------

    async def _elect_initial_active(self) -> None:
        """中文
        ----
        Initial 选举: 若 active 仍为 ``None``, 按 priority 降序选首个
        ready source, emit ``reason="initial"``。

        已经在 ``_consume`` 内被设为 active 的, 这里跳过 (例如 start()
        完成前某 source 已经 yield 第一个 snapshot, _maybe_switch_active
        会用 ``initial`` 路径 emit, 但 start() 路径由本方法兜底)。

        English
        --------
        Initial election: if active is still ``None``, pick the highest
        priority ready source, emit ``reason="initial"``.

        Sources already promoted to active inside ``_consume`` (e.g. a
        source yielded its first snapshot before ``start()`` finished)
        are skipped — ``_maybe_switch_active`` already emitted with
        ``initial`` reason. ``start()``'s path is a fallback.
        """
        async with self._active_lock:
            if self._active_source_id is not None:
                return
            # 按 priority 降序选首个 ready
            sorted_bindings = sorted(
                self._bindings, key=lambda b: -b.priority
            )
            for b in sorted_bindings:
                runtime = self._runtimes[b.source_id]
                if (
                    runtime.state == _SourceState.READY
                    and runtime.last_snap is not None
                ):
                    self._active_source_id = b.source_id
                    self._bus.publish(
                        RuleSourceActivation(
                            previous_source_id=None,
                            source_id=b.source_id,
                            version=runtime.last_snap.version,
                            reason="initial",
                        )
                    )
                    return

    async def _maybe_switch_active(
        self, runtime: _SourceRuntime, snap: "RuleSnapshot | None"
    ) -> None:
        """中文
        ----
        决定是否要把 ``runtime`` 提升为 active。

        **3 条件 AND** (rule_source_activation.md §2):

        1. ``runtime.state == READY`` 且 ``snap`` 非空 (Repository 已
           接受, 业务校验通过)
        2. ``runtime.binding.priority`` 严格大于当前 active 的 priority
           (``manual_replace``); 或当前 active 已 stale 且 failover
           窗口已过 (``failover``)
        3. 实际 source_id 变更 (避免 "active 同 source 新 snapshot" 误
           emit)

        English
        --------
        Decide whether to promote ``runtime`` to active.

        **3-condition AND** (rule_source_activation.md §2):

        1. ``runtime.state == READY`` and ``snap`` is not None
           (Repository accepted, business validation passed).
        2. ``runtime.binding.priority`` strictly greater than current
           active's priority (``manual_replace``); or current active is
           stale and the failover window has elapsed (``failover``).
        3. Actual source_id change (avoid emitting on "active same
           source new snapshot").
        """
        if snap is None or runtime.state != _SourceState.READY:
            return
        async with self._active_lock:
            current = self._active_source_id
            binding = runtime.binding
            if current is None:
                # 没有 active。start() 完成前由 start() 兜底选举
                # (最高 priority ready source); start() 完成后, source
                # 才进入 ready 状态, 我们再选举 (e.g. delay 启动的
                # source 在 start() 之后才 yield first snap)。
                if not self._start_completed:
                    return
                # 选举 highest priority ready
                sorted_bindings = sorted(
                    self._bindings, key=lambda b: -b.priority
                )
                for b in sorted_bindings:
                    rt = self._runtimes[b.source_id]
                    if (
                        rt.state == _SourceState.READY
                        and rt.last_snap is not None
                    ):
                        self._active_source_id = b.source_id
                        self._bus.publish(
                            RuleSourceActivation(
                                previous_source_id=None,
                                source_id=b.source_id,
                                version=rt.last_snap.version,
                                reason="initial",
                            )
                        )
                        return
                return
            if current == binding.source_id:
                # active 没变, 不 emit (同 source 新 snapshot / checksum
                # 刷新 — 这些走 M6.5.7 envelope health event)
                return
            current_binding = self._by_id[current]
            current_runtime = self._runtimes[current]
            # 必须 priority 严格更高才切
            if binding.priority <= current_binding.priority:
                return
            # 决定 reason
            if current_runtime.state == _SourceState.STALE:
                # failover: 必须等 failover_after 窗口
                if current_runtime.stale_at_monotonic is None:
                    return  # 不应发生 (stale 必有 stale_at)
                elapsed = time.monotonic() - current_runtime.stale_at_monotonic
                window = current_binding.failover_after.total_seconds()
                if elapsed < window:
                    # 仍在容错窗口, 不切
                    return
                reason = "failover"
            else:
                # current 仍 ready, 这就是 manual_replace (高优先级
                # source 抢断; M6.1 阶段通过 _consume 自然产生)
                reason = "manual_replace"
            # 3 条件全部满足, emit
            previous = self._active_source_id
            self._active_source_id = binding.source_id
            self._bus.publish(
                RuleSourceActivation(
                    previous_source_id=previous,
                    source_id=binding.source_id,
                    version=snap.version,
                    reason=reason,
                )
            )


__all__: list[str] = []
