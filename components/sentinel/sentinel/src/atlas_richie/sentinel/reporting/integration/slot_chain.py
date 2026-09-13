"""Atlas Richie Sentinel — Slot chain → ReportingEvent (M6.5.4).

中文
----
Slot chain 单次执行结果 (M2 outcomes) → ``RULE_APPLIED`` /
``RULE_BLOCKED`` / ``RULE_FAILED`` ``ReportingEvent``.

转换规则 (协议 §5.3):

- ``OutcomeKind.SUCCEEDED`` → ``rule_applied`` (failure_class=None)
- ``OutcomeKind.BLOCKED`` → ``rule_blocked`` (failure_class=None)
- ``OutcomeKind.FAILED`` → ``rule_failed`` (failure_class 必填,
  ReasonClass 7 值之一)
- ``OutcomeKind.CANCELLED`` → 不发 (cancel 是 Engine 状态, 不是
  业务失败; 1.0 暂不报, 减少 noise)
- ``OutcomeKind.ADMITTED`` → 不发 (中间态, 不算终态)

**M6.5.4 实施原则**: 不在 Slot / Engine 内部 emit (避免 Slot 协议
污染). 1.0 由 integration 层订阅 Engine 退出事件, 调
``AgentReporter.emit()`` 投递. 实际订阅: 用户在 ``SentinelEngine``
外部桥接 (e.g. Aspect / decorator), integration 提供
``outcome_to_event`` 翻译.

**不**导出 ``__all__`` (C 层私有).

English
--------
Slot chain single-execution result (M2 outcomes) →
``RULE_APPLIED`` / ``RULE_BLOCKED`` / ``RULE_FAILED`` ``ReportingEvent``.

Translation rules (protocol §5.3):

- ``OutcomeKind.SUCCEEDED`` → ``rule_applied`` (failure_class=None)
- ``OutcomeKind.BLOCKED`` → ``rule_blocked`` (failure_class=None)
- ``OutcomeKind.FAILED`` → ``rule_failed`` (failure_class required,
  one of 7 ReasonClass values)
- ``OutcomeKind.CANCELLED`` → not emitted (cancel is Engine state,
  not business failure; 1.0 doesn't report, to reduce noise)
- ``OutcomeKind.ADMITTED`` → not emitted (intermediate state, not
  terminal)

M6.5.4 implementation principle: do not emit from inside Slot /
Engine (to avoid Slot protocol pollution). 1.0 integration subscribes
to Engine exit events; ``outcome_to_event`` provided by integration.

Not in ``__all__`` (C-layer private).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...model.outcome import Outcome, OutcomeKind
from ...rules.snapshot import RuleSnapshot
from .._identity import ReporterIdentity
from ..reporter import AgentReporter, ReportingEvent
from atlas_richie.contracts.reporting.v1 import ReportingEventKind, ExecResult, ReasonClass


# ReasonClass 7 值 (协议 §5.3 frozen)
_REASON_CLASS_MAP: dict[str, str] = {
    # 跟主包 BlockReason + 业务失败原因 1:1 映射. 1.0 简化: 只覆盖
    # 主包 BlockReason 7 值的子集 (BlockReason 6 + CircuitOpen); 这里
    # ReasonClass 7 值: timeout / rule_error / dependency / resource /
    # auth / degraded / unknown.
    "FLOW": "flow",
    "PARAM_FLOW": "param_flow",
    "SYSTEM": "system",
    "DEGRADE": "degraded",
    "AUTHORITY": "auth",
    "POOL_FULL": "resource",
    "CIRCUIT_OPEN": "degraded",
}


def _map_block_reason_to_reason_class(reason: str) -> str:
    """主包 BlockReason (6 值 + CIRCUIT_OPEN) → 协议 ReasonClass (7 值).

    中文
    ----
    1.0 简化映射: 1:1 + circuit_open → degraded. ``unknown`` 用于
    兜底 (主包识别不出 reason 时).

    English
    --------
    1.0 simplified mapping: 1:1 + circuit_open → degraded. ``unknown``
    for fallback (when main package cannot identify the reason).
    """
    return _REASON_CLASS_MAP.get(reason, "unknown")


@dataclass(slots=True, frozen=True)
class SlotExecResult:
    """内部 slot exec 终态 (integration 层).

    中文
    ----
    跟 ``Outcome`` 不同: 1.0 简化, 只取 emitting 必要的字段, 避免
    integration 层过度耦合主包 ``Outcome`` 内部结构.

    English
    --------
    Differs from ``Outcome``: 1.0 simplification, takes only fields
    needed for emitting; avoids over-coupling integration layer to
    main package ``Outcome`` internals.
    """

    resource: str
    rule_id: str
    outcome_kind: str  # OutcomeKind value
    block_reason: str | None  # 仅 BLOCKED
    error_message: str | None  # 仅 FAILED
    snapshot: RuleSnapshot  # version triplet source


def _build_exec_event(result: SlotExecResult) -> ReportingEvent | None:
    """``SlotExecResult`` → ``ReportingEvent`` 或 None (未映射).

    中文
    ----
    ``source_id`` 用 ``snapshot.source_id`` (来自 M6.1 source,
    1.0 简化: Resource.name 也作为辅助; wire §5.3 必填 source_id).
    """
    snap = result.snapshot
    source_id = snap.source_id or result.resource
    if result.outcome_kind == OutcomeKind.SUCCEEDED.value:
        return ReportingEvent(
            kind=ReportingEventKind.RULE_APPLIED.value,
            source_id=source_id,
            resource=result.resource,
            rule_id=result.rule_id,
            exec_result=ExecResult.APPLIED.value,
            failure_class=None,
            reason=None,
            previous_source_id=None,
            priority=None,
            health_class=None,
            reason_message=None,
            epoch=snap.version.epoch,
            revision=snap.version.revision,
            checksum=snap.version.checksum,
        )
    if result.outcome_kind == OutcomeKind.BLOCKED.value:
        return ReportingEvent(
            kind=ReportingEventKind.RULE_BLOCKED.value,
            source_id=source_id,
            resource=result.resource,
            rule_id=result.rule_id,
            exec_result=ExecResult.BLOCKED.value,
            failure_class=None,
            reason=result.block_reason,
            previous_source_id=None,
            priority=None,
            health_class=None,
            reason_message=None,
            epoch=snap.version.epoch,
            revision=snap.version.revision,
            checksum=snap.version.checksum,
        )
    if result.outcome_kind == OutcomeKind.FAILED.value:
        return ReportingEvent(
            kind=ReportingEventKind.RULE_FAILED.value,
            source_id=source_id,
            resource=result.resource,
            rule_id=result.rule_id,
            exec_result=ExecResult.FAILED.value,
            failure_class=_classify_failure(result),
            reason=None,
            previous_source_id=None,
            priority=None,
            health_class=None,
            reason_message=result.error_message,
            epoch=snap.version.epoch,
            revision=snap.version.revision,
            checksum=snap.version.checksum,
        )
    # ADMITTED (中间态) / CANCELLED → 不发
    return None


def _classify_failure(result: SlotExecResult) -> str:
    """失败分类 → ReasonClass (7 冻结值, 协议 §5.4).

    中文
    ----
    1.0 简化: 关键字启发式匹配 error_message 推断 ReasonClass.
    ReasonClass 冻结枚举 (7 值, V1 不可扩展).
    """
    if result.error_message:
        # 简单启发式: 关键字匹配
        msg = result.error_message.lower()
        if "timeout" in msg:
            return ReasonClass.NETWORK_TIMEOUT.value
        if "auth" in msg or "permission" in msg:
            return ReasonClass.AUTH_FAILED.value
        if "resource" in msg or "pool" in msg:
            return ReasonClass.STATE_INVALID.value
        if "degrade" in msg or "circuit" in msg:
            return ReasonClass.STATE_INVALID.value
        if "dependency" in msg or "downstream" in msg:
            return ReasonClass.NETWORK_UNAVAILABLE.value
        if "rule" in msg:
            return ReasonClass.DECODE_FAILED.value
    return ReasonClass.UNKNOWN.value


def outcome_to_event(outcome: Outcome, snapshot: RuleSnapshot) -> ReportingEvent | None:
    """``Outcome`` + ``RuleSnapshot`` → ``ReportingEvent`` 或 None.

    中文
    ----
    1.0 公开 helper: 给 Engine entry 退出时的 callback 桥接用.
    返回 None 表示 outcome 不映射到 reporting event (ADMITTED /
    CANCELLED).

    English
    --------
    1.0 public helper: for Engine entry-exit callback bridging.
    Returns None when the outcome is not mapped to a reporting
    event (ADMITTED / CANCELLED).
    """
    # 简化: resource / rule_id 1.0 暂未在 Outcome 暴露, 用
    # "unknown" 占位 (DRAFT 阶段, frozen 后 V2 考虑扩展 Outcome)
    error = getattr(outcome, "error", None)
    error_args = getattr(error, "args", None) or ("",)
    error_message = error_args[0] if error is not None and error_args else None
    result = SlotExecResult(
        resource=str(getattr(outcome, "resource", None) or "unknown"),
        rule_id="unknown",  # 1.0 简化: Outcome 没暴露 rule_id
        outcome_kind=outcome.kind.value,
        block_reason=str(
            getattr(getattr(outcome, "error", None), "block_reason", None) or ""
        ) or None,
        error_message=error_message,
        snapshot=snapshot,
    )
    return _build_exec_event(result)


def install_slot_chain_subscriber(
    reporter: AgentReporter,
    on_entry_complete: Any,
) -> None:
    """订阅 Engine entry 完成 callback, 把 outcome 转 ReportingEvent 后 emit.

    中文
    ----
    1.0 内部 helper: ``on_entry_complete`` 是
    ``Callable[[Outcome, RuleSnapshot], None]``, 由调用方 (e.g.
    业务代码 / Engine exit hook) 在 entry 退出时调.

    English
    --------
    1.0 internal helper: ``on_entry_complete`` is
    ``Callable[[Outcome, RuleSnapshot], None]``, called by the
    caller (e.g. business code / Engine exit hook) on entry exit.
    """
    def _on_complete(outcome: Outcome, snapshot: RuleSnapshot) -> None:
        try:
            event = outcome_to_event(outcome, snapshot)
        except Exception:
            return
        if event is None:
            return
        try:
            reporter.emit(event)
        except Exception:
            pass

    on_entry_complete(_on_complete)


__all__: list[str] = []
