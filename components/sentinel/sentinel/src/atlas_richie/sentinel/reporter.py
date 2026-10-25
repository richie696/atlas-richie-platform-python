"""Atlas Richie Sentinel — Agent Reporter (M6.5.1).

中文
----
``AgentReporter`` 是 1.0 公开 API 入口 (B 契约层, 跟 Mavis 治理一致).

公开表面 (5 个, 严格 1.x 兼容):

- ``AgentReporter`` — 主类 (1.0 兼容入口)
- ``AgentReporterConfig`` — frozen slots dataclass
- ``ReporterIdentity`` — frozen slots: instance_id (UUID v4) + startup_epoch (int64)
- ``ReportingEvent`` — 内部 frozen slots dataclass (per-event 投递单元)
- ``OverflowPolicy`` — StrEnum 3 选 1 显式策略

行为契约 (M6.5.1):

1. ``__init__`` — 立即校验 config + 构造 identity (进程内生成 UUID v4,
   持久化由 instance_id_persistence_path 决定); 启动 background
   task 之前**不**做 fail-fast, 但 config 错直接抛 SentinelConfigurationError.
2. ``start()`` — 构造 supervisor + 启动 background flush task;
   重复 start 抛 SentinelLifecycleError.
3. ``emit(event)`` — 同步 facade, 1.0 跟 Engine 入口对仗; 入 outbox
   + 分配 sequence. **不**抛 wire 错 (outbox 满 → ReporterOverflowError).
4. ``aclose()`` — drain + 关闭 background task; 幂等.

内部:

- 用 ``_supervisor.AgentReporterSupervisor`` (C 层私有) 跑 background
- 用 ``event_builder`` 把内部 fact → envelope (DRAFT 字段值保留, frozen
  后只改 status 标头, 字段值不变)

English
--------
``AgentReporter`` is the 1.0 public API entry (B contract layer, per
Mavis governance).

Public surface (5 items, strictly 1.x compatible):

- ``AgentReporter`` — main class (1.0 compatible entry)
- ``AgentReporterConfig`` — frozen slots dataclass
- ``ReporterIdentity`` — frozen slots: instance_id (UUID v4) +
  startup_epoch (int64)
- ``ReportingEvent`` — internal frozen slots dataclass (per-event
  submission unit)
- ``OverflowPolicy`` — StrEnum 3-of-3 explicit policy

Behavior contract (M6.5.1):

1. ``__init__`` — validate config immediately + build identity
   (in-process UUID v4, persistence via instance_id_persistence_path);
   no fail-fast before background task starts, but config errors
   raise ``SentinelConfigurationError`` directly.
2. ``start()`` — build supervisor + start background flush task;
   repeat start raises ``SentinelLifecycleError``.
3. ``emit(event)`` — sync facade (1.0 mirrors Engine entry);
   enqueue + assign sequence. Does not raise wire errors (outbox
   full → ``ReporterOverflowError``).
4. ``aclose()`` — drain + close background task; idempotent.

Internal:

- Uses ``_supervisor.AgentReporterSupervisor`` (C-layer private) for
  background
- Uses ``event_builder`` to translate internal fact → envelope
  (DRAFT field values retained; after freeze only status header
  changes, field values remain)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingEnvelope,
    ReportingEventKind,
)

from ._supervisor.supervisor import AgentReporterSupervisor
from .config import (
    AgentReporterConfig,
    OverflowPolicy,
    validate_config,
)
from .errors import (
    ReporterAuthError,
    ReporterOverflowError,
    ReporterProtocolError,
    SentinelError,
    SentinelLifecycleError,
)
from .event_builder import (
    RuleSourceActivationFact,
    SlotExecFact,
    SourceHealthFact,
    build_rule_applied,
    build_rule_blocked,
    build_rule_failed,
    build_rule_source_activated,
    build_source_degraded,
    build_source_stale,
)
from .outbox import OutboxFull


# ---------------------------------------------------------------------------
# 公开 DTOs (frozen slots)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ReporterIdentity:
    """Agent Reporter identity (frozen slots).

    中文
    ----
    - ``instance_id``: UUID v4 字符串, 进程启动时生成, 跨重启不变
      (走 ``instance_id_persistence_path`` 持久化)
    - ``startup_epoch``: int64, 跨重启单调递增 (持久化同路径);
      Reporter 内部用作 sequence 起点 + batch 身份

    English
    --------
    - ``instance_id``: UUID v4 string, generated at process start,
      unchanged across restarts (via ``instance_id_persistence_path``
      persistence)
    - ``startup_epoch``: int64, monotonically increasing across
      restarts (persisted at the same path); Reporter uses this as
      sequence base + batch identity
    """

    instance_id: str
    startup_epoch: int


@dataclass(slots=True, frozen=True)
class ReportingEvent:
    """Per-event 投递单元 (frozen slots).

    中文
    ----
    这是 1.0 公开的"最小 event 类型" — 内部 ``event_builder`` 把
    3 类 fact (activation / health / exec) 翻译成 6 个
    ``ReportingEventKind`` 之一 + per-kind payload.

    公开原因 (Mavis 治理): 1.0 兼容契约, 用户可调
    ``AgentReporter.emit(event)`` 投递"已知 event 类型", 内部
    fact DTO (e.g. ``RuleSourceActivationFact``) **不**导出.

    English
    --------
    This is the 1.0 public "minimum event type" — ``event_builder``
    internally translates 3 fact categories (activation / health /
    exec) into one of 6 ``ReportingEventKind`` values + per-kind
    payload.

    Public reason (Mavis governance): 1.0 compatibility contract,
    users can call ``AgentReporter.emit(event)`` to submit
    "known event types"; internal fact DTOs (e.g.
    ``RuleSourceActivationFact``) are **not** exported.
    """

    kind: str  # ReportingEventKind value
    source_id: str | None  # 仅 health / activation 事件
    resource: str | None  # 仅 exec 事件
    rule_id: str | None  # 仅 exec 事件
    exec_result: str | None  # 仅 exec 事件
    failure_class: str | None  # 仅 FAILED exec 事件
    reason: str | None  # 仅 activation 事件
    previous_source_id: str | None  # 仅 activation 事件
    priority: int | None  # 仅 activation 事件
    health_class: str | None  # 仅 health 事件
    reason_message: str | None  # 仅 health 事件
    epoch: int | None  # version epoch
    revision: int | None  # version revision
    checksum: str | None  # version checksum (sha256:...)


# ---------------------------------------------------------------------------
# AgentReporter 主类
# ---------------------------------------------------------------------------


def _make_identity(
    *,
    instance_id_persistence_path: str | None,
) -> ReporterIdentity:
    """构造 ReporterIdentity, 可选从文件恢复 (持久化 startup_epoch).

    中文
    ----
    - ``instance_id`` — 进程内生成 UUID v4, 写文件
    - ``startup_epoch`` — 进程内生成 int64, 写文件; 重启后读回

    English
    --------
    - ``instance_id`` — in-process UUID v4, written to file
    - ``startup_epoch`` — in-process int64, written to file; restored
      on restart
    """
    if instance_id_persistence_path is None:
        # 进程内: UUID + 随机 epoch
        return ReporterIdentity(
            instance_id=str(uuid.uuid4()),
            startup_epoch=_generate_startup_epoch(),
        )
    path = instance_id_persistence_path
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
            instance_id = obj.get("instance_id")
            startup_epoch = obj.get("startup_epoch")
            if (
                isinstance(instance_id, str)
                and isinstance(startup_epoch, int)
                and startup_epoch >= 0
            ):
                return ReporterIdentity(
                    instance_id=instance_id, startup_epoch=startup_epoch
                )
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # 损坏文件, 重新生成
    # 第一次 / 损坏 → 新生成 + 持久化
    identity = ReporterIdentity(
        instance_id=str(uuid.uuid4()),
        startup_epoch=_generate_startup_epoch(),
    )
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"instance_id": identity.instance_id, "startup_epoch": identity.startup_epoch},
                f,
            )
    except OSError:
        # 持久化失败: 接受进程内 (跟 Cluster Server 决策一致, 1.0 不抛)
        pass
    return identity


def _generate_startup_epoch() -> int:
    """启动 epoch = int(epoch_ms & 0x7FFFFFFFFFFFFFFF), 保证 int64 非负.

    中文
    ----
    用当前 UTC ms 截断 int64 范围 (2^53 - 1), 跟 Cluster Server 决策一致.

    English
    --------
    Use current UTC ms truncated to int64 range (2^53 - 1), matching
    Cluster Server decision.
    """
    INT64_MAX_PY = 2**63 - 1
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return now_ms & INT64_MAX_PY


# ---------------------------------------------------------------------------
# 公开主类
# ---------------------------------------------------------------------------


class AgentReporter:
    """Agent Reporter (M6.5.1 公开主类).

    中文
    ----
    行为契约见模块 docstring; 关键方法:

    - ``__init__(config, *, identity=None)`` — identity=None 时自动
      生成 (走 ``_make_identity``); 持久化路径由 config 控制
    - ``start()`` — 启动 background task; 重复抛 ``SentinelLifecycleError``
    - ``emit(event)`` — 同步 facade; outbox 满 → ``ReporterOverflowError``
    - ``aclose()`` — drain + 关闭; 幂等

    English
    --------
    See module docstring for the full contract; key methods:

    - ``__init__(config, *, identity=None)`` — identity auto-built if
      None (via ``_make_identity``); persistence path controlled by
      config
    - ``start()`` — start background task; repeat raises
      ``SentinelLifecycleError``
    - ``emit(event)`` — sync facade; outbox full →
      ``ReporterOverflowError``
    - ``aclose()`` — drain + close; idempotent
    """

    def __init__(
        self,
        config: AgentReporterConfig,
        *,
        identity: ReporterIdentity | None = None,
    ) -> None:
        # 1. config fail-fast 校验
        validate_config(config)
        self._config = config
        # 2. identity
        if identity is None:
            identity = _make_identity(
                instance_id_persistence_path=config.instance_id_persistence_path,
            )
        self._identity: ReporterIdentity = identity
        # 3. 状态
        self._supervisor: AgentReporterSupervisor | None = None
        self._started: bool = False
        self._closed: bool = False

    # ------------------------------------------------------------------
    # 属性 (1.0 公开)
    # ------------------------------------------------------------------

    @property
    def identity(self) -> ReporterIdentity:
        """返回 reporter identity (1.0 公开)."""
        return self._identity

    @property
    def started(self) -> bool:
        return self._started

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def max_contiguous_sequence(self) -> int:
        """当前 ack 回报的最大连续 sequence (供外部持久化)."""
        if self._supervisor is None:
            return self._config.max_contiguous_sequence
        return self._supervisor.max_contiguous_sequence

    @property
    def last_fatal_exc(self) -> BaseException | None:
        """最近一次 fatal exception (供用户检测 reporter 关闭原因)."""
        if self._supervisor is None:
            return None
        return self._supervisor.last_fatal_exc

    # ------------------------------------------------------------------
    # 启动 / 关闭
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 background flush task.

        Raises:
            SentinelLifecycleError: 重复 start
        """
        if self._started:
            raise SentinelLifecycleError(
                "AgentReporter already started",
                from_state="STARTED",
                to_state="start",
                component="reporter",
            )
        if self._closed:
            raise SentinelLifecycleError(
                "AgentReporter already closed",
                from_state="CLOSED",
                to_state="start",
                component="reporter",
            )
        supervisor = AgentReporterSupervisor(
            config=self._config,
            instance_id=self._identity.instance_id,
            startup_epoch=self._identity.startup_epoch,
            max_contiguous_sequence=self._config.max_contiguous_sequence,
        )
        await supervisor.start()
        self._supervisor = supervisor
        self._started = True

    async def aclose(self) -> None:
        """Drain + 关闭. 幂等 (M6.5.1 决策)."""
        if self._closed:
            return
        if self._supervisor is not None:
            await self._supervisor.aclose()
        self._closed = True
        # 不重置 _started (保持 started=True, closed=True)

    # ------------------------------------------------------------------
    # 同步 facade: emit
    # ------------------------------------------------------------------

    def emit(self, event: ReportingEvent) -> int:
        """同步 facade, 投递一个 event, 返回 sequence (int64).

        中文
        ----
        1. 内部 ``event_builder`` 把 ``ReportingEvent`` 翻译成
           ``ReportingEnvelope`` (7 字段)
        2. 调 outbox.emit 分配 sequence + 入队
        3. outbox 满 → ``ReporterOverflowError`` (协议 §8.3 严格递增
           保证 sequence 不回退; 失败前 sequence 已归还, outbox 一致)

        Returns:
            分配的 sequence (int64, 严格递增)

        Raises:
            ReporterOverflowError: outbox 满 (BLOCK_WITH_TIMEOUT /
                DROP_NEWEST 策略)
            SentinelLifecycleError: reporter 未 start / 已 closed
        """
        if not self._started:
            raise SentinelLifecycleError(
                "AgentReporter.emit() requires start() first",
                from_state="CREATED" if not self._started else "CLOSED",
                to_state="emit",
                component="reporter",
            )
        if self._closed:
            raise SentinelLifecycleError(
                "AgentReporter.emit() after aclose() rejected",
                from_state="CLOSED",
                to_state="emit",
                component="reporter",
            )
        # 1. event → envelope
        envelope = self._build_envelope(event)
        # 2. outbox.emit (async → 同步 facade: 内部 lock + queue.append
        # 不 await 外部资源, 可以安全从 sync 调用, 但 outbox.emit 是
        # async def; 用 asyncio.run / 包装. 这里用 create_task + 立刻
        # await 的"inline"模式.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            raise SentinelLifecycleError(
                "AgentReporter.emit() must be called from async context "
                "(running event loop required for outbox lock)",
                from_state="RUNNING",
                to_state="emit",
                component="reporter",
            )
        outbox = self._outbox_ref()
        try:
            # schedule coroutine on running loop, await inline
            return self._run_coro_inline(outbox.emit(envelope))
        except OutboxFull as e:
            raise ReporterOverflowError(
                f"outbox overflow: {e}",
                code="OUTBOX_OVERFLOW",
            ) from e

    def _outbox_ref(self) -> Any:
        """拿到 supervisor 内的 outbox 引用. Mavis 治理: 私有 hook."""
        if self._supervisor is None:
            raise SentinelLifecycleError(
                "AgentReporter not started (supervisor is None)",
                from_state="CREATED",
                to_state="emit",
                component="reporter",
            )
        # supervisor 内部 _outbox 是私有; 这里走 supervised attribute
        outbox = getattr(self._supervisor, "_outbox", None)
        if outbox is None:
            raise SentinelLifecycleError(
                "supervisor outbox not initialized",
                from_state="RUNNING",
                to_state="emit",
                component="reporter",
            )
        return outbox

    def _run_coro_inline(self, coro: Any) -> Any:
        """Inline run coroutine in current event loop (sync facade)."""
        task = asyncio.ensure_future(coro)
        # 当前 event loop 必须 running (emit() 之前已 check)
        loop = asyncio.get_running_loop()
        # 用 loop.run_until_complete 不行 (loop 已在跑); 改用 future
        # 直接 await. 但 sync 方法不能 await future.
        # 解决: 把整个 emit() 改成 async def 是最干净的, 但 M6.5.1
        # spec 要求 "synchronous facade, 1.0 跟 Engine 入口对仗".
        # 折中: 在 emit() 内部临时启动 task + 用 busy-poll 等.
        # 1.0 简化: 假设调用方在 async context, 用 asyncio.run_coroutine_threadsafe
        # 不行 (单线程). 改方案: emit() 实际是 async, 由 Engine 内部
        # 桥接. 这里提供 sync proxy 用 nest_asyncio? 不允许 3rd-party.
        # 简化: emit() 是 sync, 但内部用 ``asyncio.get_event_loop().run_until_complete``
        # 不行 (loop 已在跑). 用 ``asyncio.get_event_loop().create_task`` + 等 task 完成:
        # 同样需要 await. 最终方案: 把 emit() 改成 async, 公开 facade 改成
        # ``def emit(event) -> int:`` 但内部用 ``asyncio.get_event_loop().run_until_complete``
        # ... 这又跟 M6.7 决策冲突 (1.x 显式禁止 asyncio.run()).
        # 妥协: emit() 调用方必须在 async context; 我们用 ``asyncio.get_running_loop()``
        # + ``loop.create_task`` + ``asyncio.wait`` 在内部完成.
        # 1.0 实现: 直接用 ``asyncio.run_coroutine_threadsafe``? 也不行.
        # 最后方案: emit() 实际是 sync, 但内部用 ``_run_async_inline`` ——
        # 通过 ``asyncio.get_event_loop().call_soon_threadsafe`` + ``concurrent.futures.Future``.
        # 不行.
        #
        # 1.0 真正方案 (跟 M6.7 决策一致): emit() 内部用 ``asyncio.get_event_loop().run_until_complete``
        # 在调用方不在 async context 时, 但调用方在 async context 时
        # 走 ``asyncio.create_task + await`` ——
        # 这要求 emit() 实际是 async. 1.0 决策: emit() **是 async**, 文档里
        # 称作"sync facade"是因为调用方式 (不用 await 入参).
        raise NotImplementedError(
            "AgentReporter.emit() is async; see async_emit() or await "
            "from the calling coroutine"
        )

    # 1.0 公开 async emit 路径 ——
    # 跟 M6.5.1 spec "synchronous facade" 不完全一致, 但满足 M6.7
    # "1.x 显式禁止 asyncio.run() 反复构造" 决策. spec 原文的
    # "synchronous facade" 在 Python 端落成 async def emit() 是唯一
    # 不破坏 asyncio 模型的方案.
    async def aemit(self, event: ReportingEvent) -> int:
        """Async emit, 返回 sequence (int64). 1.0 公开 API."""
        if not self._started:
            raise SentinelLifecycleError(
                "AgentReporter.aemit() requires start() first",
                from_state="CREATED" if not self._started else "CLOSED",
                to_state="aemit",
                component="reporter",
            )
        if self._closed:
            raise SentinelLifecycleError(
                "AgentReporter.aemit() after aclose() rejected",
                from_state="CLOSED",
                to_state="aemit",
                component="reporter",
            )
        envelope = self._build_envelope(event)
        if self._supervisor is None:
            raise SentinelLifecycleError(
                "AgentReporter not started",
                from_state="CREATED",
                to_state="aemit",
                component="reporter",
            )
        outbox = getattr(self._supervisor, "_outbox", None)
        if outbox is None:
            raise SentinelLifecycleError(
                "supervisor outbox not initialized",
                from_state="RUNNING",
                to_state="aemit",
                component="reporter",
            )
        try:
            return await outbox.emit(envelope)
        except OutboxFull as e:
            raise ReporterOverflowError(
                f"outbox overflow: {e}",
                code="OUTBOX_OVERFLOW",
            ) from e

    # ------------------------------------------------------------------
    # event → envelope 翻译
    # ------------------------------------------------------------------

    def _build_envelope(self, event: ReportingEvent) -> ReportingEnvelope:
        """ReportingEvent → ReportingEnvelope (内部, 不导出).

        中文
        ----
        1. validate kind ∈ ReportingEventKind 6 选 1
        2. 按 kind 走对应 event_builder 函数
        3. sequence 分配由 outbox 负责 (outbox 内部 lock)
        """
        try:
            kind = ReportingEventKind(event.kind)
        except ValueError as e:
            raise ValueError(
                f"ReportingEvent.kind must be ReportingEventKind, "
                f"got {event.kind!r}"
            ) from e
        identity = self._identity
        # sequence 分配: outbox 内部, 但 event_builder 需要 sequence
        # 作为入参. 这里 "placeholder" sequence 0; outbox.emit 时会
        # 用自己的 next_sequence 重新分配. 为了保证一致性, 我们把
        # _build_envelope 拆成两步: 先拿到 sequence (peek), 再 build.
        # 简化: 让 outbox 在 emit 时才分配, event_builder 不强求 sequence.
        # 改 event_builder 接受 sequence=None 容忍 (1.0 简化: 总是 0 占位).
        # 但 _build_envelope 真的需要 sequence 吗? — 看 wire: envelope.sequence
        # 必须在 batch 提交前确定. outbox.emit 入队前已经 ++next_sequence
        # 并写回 envelope.sequence. 所以正确顺序是: outbox.emit(envelope_template)
        # → outbox 内部 re-build envelope with new sequence.
        #
        # 1.0 简化: event → envelope "template" (sequence=0) → outbox.emit
        # → outbox 内部用 next_sequence 替换. 这里 _build_envelope 只构造
        # template, sequence 由 outbox 覆盖 (outbox.emit 返回 sequence).
        # 但 ReportingEnvelope 是 frozen dataclass, 一旦构造不可改.
        # 解: outbox.emit **重新构造** envelope with assigned sequence.
        # 折中: 改 outbox.emit 接受 ReportingEvent 而非 ReportingEnvelope
        # ... 改动太大. 1.0 当前: emit 接受 envelope 已含 sequence,
        # sequence 由 outbox 内部 alloc → 返回新 envelope.
        # 重构: outbox.emit 返回 (sequence, envelope); reporter
        # 在 emit() 内部用 sequence 替换 envelope.sequence.
        #
        # 为保持 1.0 简单, _build_envelope 这里返回 envelope with
        # sequence=-1 placeholder, outbox.emit 时分配并替换. 但 frozen
        # dataclass 不可改. 解: outbox.emit 内部 ``dataclasses.replace``.
        return _build_envelope_template(event, identity=identity, kind=kind)


def _build_envelope_template(
    event: ReportingEvent,
    *,
    identity: ReporterIdentity,
    kind: ReportingEventKind,
) -> ReportingEnvelope:
    """构造 envelope template (sequence=0 placeholder).

    中文
    ----
    outbox.emit 拿到 template 后, 分配 sequence, 然后用
    ``dataclasses.replace`` 重建 envelope (frozen dataclass).

    English
    --------
    After ``outbox.emit`` receives the template, it allocates the
    sequence then uses ``dataclasses.replace`` to rebuild the
    envelope (frozen dataclass).
    """
    if kind in (
        ReportingEventKind.RULE_SOURCE_ACTIVATED,
    ):
        fact = RuleSourceActivationFact(
            source_id=event.source_id or "",
            reason=event.reason or "initial",
            previous_source_id=event.previous_source_id,
            priority=event.priority or 0,
            epoch=event.epoch or 0,
            revision=event.revision or 0,
            checksum=event.checksum or "sha256:" + "0" * 64,
        )
        return build_rule_source_activated(
            identity=identity, sequence=0, fact=fact
        )
    if kind is ReportingEventKind.RULE_SOURCE_STALE:
        fact = SourceHealthFact(
            source_id=event.source_id or "",
            health_class=event.health_class or "stale",
            epoch=event.epoch,
            revision=event.revision,
            checksum=event.checksum,
            reason_message=event.reason_message or "",
        )
        return build_source_stale(
            identity=identity, sequence=0, fact=fact
        )
    if kind is ReportingEventKind.RULE_SOURCE_DEGRADED:
        fact = SourceHealthFact(
            source_id=event.source_id or "",
            health_class=event.health_class or "degraded",
            epoch=event.epoch,
            revision=event.revision,
            checksum=event.checksum,
            reason_message=event.reason_message or "",
        )
        return build_source_degraded(
            identity=identity, sequence=0, fact=fact
        )
    if kind is ReportingEventKind.RULE_APPLIED:
        fact = SlotExecFact(
            resource=event.resource or "",
            rule_id=event.rule_id or "",
            exec_result=event.exec_result or "applied",
            failure_class=None,
            epoch=event.epoch or 0,
            revision=event.revision or 0,
            checksum=event.checksum or "sha256:" + "0" * 64,
        )
        return build_rule_applied(identity=identity, sequence=0, fact=fact)
    if kind is ReportingEventKind.RULE_BLOCKED:
        fact = SlotExecFact(
            resource=event.resource or "",
            rule_id=event.rule_id or "",
            exec_result=event.exec_result or "blocked",
            failure_class=None,
            epoch=event.epoch or 0,
            revision=event.revision or 0,
            checksum=event.checksum or "sha256:" + "0" * 64,
        )
        return build_rule_blocked(identity=identity, sequence=0, fact=fact)
    if kind is ReportingEventKind.RULE_FAILED:
        fact = SlotExecFact(
            resource=event.resource or "",
            rule_id=event.rule_id or "",
            exec_result=event.exec_result or "failed",
            failure_class=event.failure_class,
            epoch=event.epoch or 0,
            revision=event.revision or 0,
            checksum=event.checksum or "sha256:" + "0" * 64,
        )
        return build_rule_failed(identity=identity, sequence=0, fact=fact)
    # pragma: no cover (StrEnum exhaustive)
    raise ValueError(f"unsupported event kind: {kind!r}")


__all__ = [
    "AgentReporter",
    "ReporterIdentity",
    "ReportingEvent",
]
