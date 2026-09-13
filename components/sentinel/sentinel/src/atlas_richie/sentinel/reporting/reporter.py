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
   持久化由 instance_id_persistence_path 决定); config 错直接抛
   ``SentinelConfigurationError``.
2. ``start()`` — 构造 supervisor + 启动 background flush task;
   重复 start 抛 ``SentinelLifecycleError``.
3. ``emit(event)`` — **同步** facade, 1.0 跟 Engine 入口对仗; 入 outbox
   + 分配 sequence. **不**抛 wire 错 (outbox 满 → ``ReporterOverflowError``).
4. ``aclose()`` — drain + 关闭 background task; 幂等.

内部:

- 用 ``_supervisor.AgentReporterSupervisor`` (C 层私有) 跑 background
- 用 ``event_builder`` 把内部 fact → envelope (FROZEN 2026-09-13 字段
  值, frozen 后只改 status 标头, 字段值不变)

**emit() 同步 + 跨线程禁 + 复用 event loop 禁** (M6.7 决策) 三方约束
下的实施: outbox 是 sync (``threading.Lock``), ``emit()`` 直接调
outbox.emit; background flush task 在 reporter 启动时持有 event loop
引用, transport 走 async.

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
   config errors raise ``SentinelConfigurationError``.
2. ``start()`` — build supervisor + start background flush task;
   repeat start raises ``SentinelLifecycleError``.
3. ``emit(event)`` — **sync** facade (1.0 mirrors Engine entry);
   enqueue + assign sequence. Does not raise wire errors (outbox
   full → ``ReporterOverflowError``).
4. ``aclose()`` — drain + close background task; idempotent.

Internal:

- Uses ``_supervisor.AgentReporterSupervisor`` (C-layer private) for
  background
- Uses ``event_builder`` to translate internal fact → envelope
  (FROZEN 2026-09-13 field values; after freeze only status header
  changes, field values remain)

**emit() sync + no cross-thread + no event-loop reuse** (M6.7
decision) are three constraints; the implementation uses sync
outbox (``threading.Lock``), ``emit()`` directly calls
``outbox.emit``; the background flush task holds an event loop
reference at start time, transport is async.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ExecResult,
    HealthClass,
    ReasonClass,
    ReportingEnvelope,
    ReportingEventKind,
)

from ..errors import SentinelLifecycleError
from ._identity import ReporterIdentity
from ._supervisor.supervisor import AgentReporterSupervisor
from .config import (
    AgentReporterConfig,
    OverflowPolicy,
    validate_config,
)
from .errors import ReporterOverflowError
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
class ReportingEvent:
    """Per-event 投递单元 (frozen slots).

    中文
    ----
    1.0 公开的"最小 event 类型" — 内部 ``event_builder`` 把 3 类 fact
    (activation / health / exec) 翻译成 6 个 ``ReportingEventKind``
    之一 + per-kind payload.

    字段含义:

    - ``kind`` (ReportingEventKind value): 必填, 6 选 1
    - ``source_id``: 仅 health / activation 事件
    - ``resource`` / ``rule_id`` / ``exec_result`` / ``failure_class``:
      仅 exec 事件
    - ``reason`` / ``previous_source_id`` / ``priority``: 仅 activation 事件
    - ``health_class`` / ``reason_message``: 仅 health 事件
    - ``epoch`` / ``revision`` / ``checksum``: 通用 version triplet

    公开原因 (Mavis 治理): 1.0 兼容契约, 用户可调
    ``AgentReporter.emit(event)`` 投递"已知 event 类型", 内部
    fact DTO (e.g. ``RuleSourceActivationFact``) **不**导出.

    English
    --------
    1.0 public "minimum event type" — ``event_builder`` internally
    translates 3 fact categories (activation / health / exec) into
    one of 6 ``ReportingEventKind`` values + per-kind payload.

    Field meanings:

    - ``kind`` (ReportingEventKind value): required, one of 6
    - ``source_id``: only health / activation events
    - ``resource`` / ``rule_id`` / ``exec_result`` / ``failure_class``:
      only exec events
    - ``reason`` / ``previous_source_id`` / ``priority``: only activation
    - ``health_class`` / ``reason_message``: only health
    - ``epoch`` / ``revision`` / ``checksum``: universal version triplet
    """

    kind: str
    source_id: str | None
    resource: str | None
    rule_id: str | None
    exec_result: str | None
    failure_class: str | None
    reason: str | None
    previous_source_id: str | None
    priority: int | None
    health_class: str | None
    reason_message: str | None
    epoch: int | None
    revision: int | None
    checksum: str | None


# ---------------------------------------------------------------------------
# Identity 工厂
# ---------------------------------------------------------------------------


def _generate_startup_epoch() -> int:
    """启动 epoch = int(epoch_ms & 0x7FFFFFFFFFFFFFFF), 保证 int64 非负.

    中文
    ----
    用当前 UTC ms 截断 int64 范围 (2^63 - 1). 简化 (跟 Cluster Server
    决策一致): 不做跨重启去重 — 同毫秒重启会产生相同 epoch, 概率
    可忽略 (重启 + 同毫秒 = OS 调度抖动, 极小).

    English
    --------
    Use current UTC ms truncated to int64 range (2^63 - 1).
    Simplified (per Cluster Server decision): no cross-restart
    dedup — same-ms restart produces same epoch, probability
    negligible (restart + same ms = OS scheduling jitter, very small).
    """
    INT64_MAX_PY = 2**63 - 1
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return now_ms & INT64_MAX_PY


def _make_identity(
    *,
    instance_id_persistence_path: str | None,
) -> ReporterIdentity:
    """构造 ReporterIdentity, 可选从文件恢复 (持久化 startup_epoch)."""
    if instance_id_persistence_path is None:
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
    identity = ReporterIdentity(
        instance_id=str(uuid.uuid4()),
        startup_epoch=_generate_startup_epoch(),
    )
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "instance_id": identity.instance_id,
                    "startup_epoch": identity.startup_epoch,
                },
                f,
            )
    except OSError:
        # 持久化失败: 接受进程内 (跟 Cluster Server 决策一致, 1.0 不抛)
        pass
    return identity


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
    - ``emit(event)`` — **同步** facade; outbox 满 → ``ReporterOverflowError``
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
            SentinelLifecycleError: 重复 start / 已 closed
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

    # ------------------------------------------------------------------
    # 同步 facade: emit
    # ------------------------------------------------------------------

    def emit(self, event: ReportingEvent) -> int:
        """同步 facade, 投递一个 event, 返回 sequence (int64).

        中文
        ----
        1. 内部 ``event_builder`` 把 ``ReportingEvent`` 翻译成
           ``ReportingEnvelope`` (7 字段, sequence=0 占位)
        2. outbox.emit 分配 sequence + 入队, 替换 envelope.sequence
           (``dataclasses.replace`` 因为 frozen dataclass)
        3. outbox 满 → ``ReporterOverflowError`` (协议 §8.3 严格递增
           保证 sequence 不回退; outbox 失败时 sequence 已回滚)

        Returns:
            分配的 sequence (int64, 严格递增)

        Raises:
            ReporterOverflowError: outbox 满 (BLOCK_WITH_TIMEOUT /
                DROP_NEWEST 策略)
            SentinelLifecycleError: reporter 未 start / 已 closed
            ValueError: event.kind 不在 6 个 ReportingEventKind
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
        # 1. event → envelope template
        kind = _validate_event_kind(event)
        envelope_template = _build_envelope_template(
            event, identity=self._identity, kind=kind
        )
        # 2. outbox.emit 分配 sequence + 入队
        outbox = self._get_outbox()
        try:
            seq = outbox.emit(envelope_template)
        except OutboxFull as e:
            raise ReporterOverflowError(
                f"outbox overflow: {e}",
                code="OUTBOX_OVERFLOW",
            ) from e
        return seq

    def _get_outbox(self) -> Any:
        """拿到 supervisor 内的 outbox 引用. Mavis 治理: 私有 hook."""
        if self._supervisor is None:
            raise SentinelLifecycleError(
                "AgentReporter not started (supervisor is None)",
                from_state="CREATED",
                to_state="emit",
                component="reporter",
            )
        outbox = getattr(self._supervisor, "_outbox", None)
        if outbox is None:
            raise SentinelLifecycleError(
                "supervisor outbox not initialized",
                from_state="RUNNING",
                to_state="emit",
                component="reporter",
            )
        return outbox


# ---------------------------------------------------------------------------
# 内部 helper: event 校验 + envelope template 构造
# ---------------------------------------------------------------------------


def _validate_event_kind(event: ReportingEvent) -> ReportingEventKind:
    """Validate event.kind, return ReportingEventKind enum."""
    try:
        return ReportingEventKind(event.kind)
    except ValueError as e:
        raise ValueError(
            f"ReportingEvent.kind must be ReportingEventKind, got {event.kind!r}"
        ) from e


def _build_envelope_template(
    event: ReportingEvent,
    *,
    identity: ReporterIdentity,
    kind: ReportingEventKind,
) -> ReportingEnvelope:
    """构造 envelope template (sequence=0 placeholder).

    中文
    ----
    outbox.emit 分配 sequence 后, envelope.sequence 由 outbox 内部
    替换 (因为 ReportingEnvelope 是 frozen dataclass, 必须用
    ``dataclasses.replace``). 当前实现: outbox.emit 接受 envelope
    + 分配 seq, 但不改 envelope; reporter 在调用方拿到 seq 后, 如
    果需要 envelope 重构造, 由 outbox 内部做 (1.0 简化: outbox.emit
    直接 append 原始 envelope, sequence 在 build_batch 时**保留**
    模板值 0, 由 outbox 在 _build_batch_locked 内 replace 一次).

    简化方案 (1.0): 模板 envelope sequence=0, outbox._buffered 中保留
    模板, build_batch 前 replace 全部 envelope.sequence.

    English
    --------
    After ``outbox.emit`` allocates the sequence, envelope.sequence
    is replaced (because ``ReportingEnvelope`` is frozen, must use
    ``dataclasses.replace``). 1.0 simplification: template envelope
    sequence=0, outbox._buffered keeps the template; before
    build_batch, replace all envelope.sequence.
    """
    if kind is ReportingEventKind.RULE_SOURCE_ACTIVATED:
        fact = RuleSourceActivationFact(
            source_id=event.source_id or "",
            epoch=event.epoch if event.epoch is not None else 0,
            revision=event.revision if event.revision is not None else 0,
            checksum=_normalize_checksum(event.checksum),
        )
        return build_rule_source_activated(
            identity=identity, sequence=0, fact=fact
        )
    if kind is ReportingEventKind.RULE_SOURCE_STALE:
        fact = SourceHealthFact(
            source_id=event.source_id or "",
            health_class=(event.health_class or HealthClass.STALE.value).upper(),
            reason_class=(event.failure_class or ReasonClass.UNKNOWN.value).upper(),
            epoch=event.epoch,
            revision=event.revision,
            checksum=_normalize_checksum_optional(event.checksum),
            reason_message=event.reason_message or "",
        )
        return build_source_stale(identity=identity, sequence=0, fact=fact)
    if kind is ReportingEventKind.RULE_SOURCE_DEGRADED:
        fact = SourceHealthFact(
            source_id=event.source_id or "",
            health_class=(event.health_class or HealthClass.DEGRADED.value).upper(),
            reason_class=(event.failure_class or ReasonClass.UNKNOWN.value).upper(),
            epoch=event.epoch,
            revision=event.revision,
            checksum=_normalize_checksum_optional(event.checksum),
            reason_message=event.reason_message or "",
        )
        return build_source_degraded(identity=identity, sequence=0, fact=fact)
    if kind is ReportingEventKind.RULE_APPLIED:
        fact = SlotExecFact(
            source_id=event.source_id or "",
            rule_id=event.rule_id or "",
            exec_result=event.exec_result or ExecResult.APPLIED.value,
            failure_class=None,
            epoch=event.epoch if event.epoch is not None else 0,
            revision=event.revision if event.revision is not None else 0,
            checksum=_normalize_checksum(event.checksum),
        )
        return build_rule_applied(identity=identity, sequence=0, fact=fact)
    if kind is ReportingEventKind.RULE_BLOCKED:
        fact = SlotExecFact(
            source_id=event.source_id or "",
            rule_id=event.rule_id or "",
            exec_result=event.exec_result or ExecResult.BLOCKED.value,
            failure_class=None,
            epoch=event.epoch if event.epoch is not None else 0,
            revision=event.revision if event.revision is not None else 0,
            checksum=_normalize_checksum(event.checksum),
        )
        return build_rule_blocked(identity=identity, sequence=0, fact=fact)
    if kind is ReportingEventKind.RULE_FAILED:
        fact = SlotExecFact(
            source_id=event.source_id or "",
            rule_id=event.rule_id or "",
            exec_result=event.exec_result or ExecResult.FAILED.value,
            failure_class=event.failure_class,
            epoch=event.epoch if event.epoch is not None else 0,
            revision=event.revision if event.revision is not None else 0,
            checksum=_normalize_checksum(event.checksum),
        )
        return build_rule_failed(identity=identity, sequence=0, fact=fact)
    # pragma: no cover (StrEnum exhaustive)
    raise ValueError(f"unsupported event kind: {kind!r}")


def _normalize_checksum(checksum: str | None) -> str:
    """归一化 checksum 为 wire 格式 ``sha256:`` + 64 hex (协议 §5.1)."""
    if not checksum:
        return "sha256:" + "0" * 64
    if checksum.startswith("sha256:"):
        return checksum
    return "sha256:" + checksum


def _normalize_checksum_optional(checksum: str | None) -> str | None:
    """归一化 checksum 为 wire 格式; None / 空 → None (成组可选, 协议 §5.2)."""
    if not checksum:
        return None
    if checksum.startswith("sha256:"):
        return checksum
    return "sha256:" + checksum


__all__ = [
    "AgentReporter",
    "OverflowPolicy",  # re-export from config
    "ReporterIdentity",
    "ReportingEvent",
]
