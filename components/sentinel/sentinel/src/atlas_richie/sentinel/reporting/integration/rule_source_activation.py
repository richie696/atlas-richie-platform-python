"""Atlas Richie Sentinel — RuleSourceActivation → ReportingEvent (M6.5.3).

中文
----
M6.1.0b frozen ``RuleSourceActivation`` fact (C 层私有) →
``RULE_SOURCE_ACTIVATED`` ``ReportingEvent`` (DRAFT, frozen 后字段
值不变) → ``AgentReporter.emit()`` 投递.

转换规则:

- ``source_id`` / ``previous_source_id`` / ``reason`` /
  ``priority`` → ReportingEvent 字段 (kind = ``rule_source_activated``)
- ``epoch`` / ``revision`` / ``checksum`` → version triplet (frozen
  必填, 跟协议 §5.1 一致)
- 时间戳: 不带 (ReportingEvent 不含 timestamp, M6.5.7 envelope 提供
  ``captured_at``)

用法: 由 Reporter 内部 bus subscriber 调 (M6.1 ``_RuleSourceActivationBus``);
非公开 API.

English
--------
M6.1.0b frozen ``RuleSourceActivation`` fact (C-layer private) →
``RULE_SOURCE_ACTIVATED`` ``ReportingEvent`` (DRAFT, field values
unchanged after freeze) → ``AgentReporter.emit()`` submit.

Translation rules:

- ``source_id`` / ``previous_source_id`` / ``reason`` / ``priority``
  → ReportingEvent fields (kind = ``rule_source_activated``)
- ``epoch`` / ``revision`` / ``checksum`` → version triplet
  (frozen mandatory, per protocol §5.1)
- No timestamp (ReportingEvent has no timestamp; M6.5.7 envelope
  provides ``captured_at``)

Usage: called by Reporter internal bus subscriber (M6.1
``_RuleSourceActivationBus``); not a public API.
"""

from __future__ import annotations

from ...source._supervisor.activation import RuleSourceActivation
from .._identity import ReporterIdentity
from ..reporter import AgentReporter, ReportingEvent
from atlas_richie.contracts.reporting.v1 import ReportingEventKind


def activation_to_event(fact: RuleSourceActivation) -> ReportingEvent:
    """``RuleSourceActivation`` fact → ``ReportingEvent``.

    中文
    ----
    字段映射 (1:1):

    - ``source_id`` → ``source_id``
    - ``previous_source_id`` → ``previous_source_id``
    - ``reason`` → ``reason``
    - ``priority`` → ``priority``
    - ``epoch`` / ``revision`` / ``checksum`` → version triplet

    English
    --------
    Field mapping (1:1):

    - ``source_id`` → ``source_id``
    - ``previous_source_id`` → ``previous_source_id``
    - ``reason`` → ``reason``
    - ``priority`` → ``priority``
    - ``epoch`` / ``revision`` / ``checksum`` → version triplet
    """
    return ReportingEvent(
        kind=ReportingEventKind.RULE_SOURCE_ACTIVATED.value,
        source_id=fact.source_id,
        resource=None,
        rule_id=None,
        exec_result=None,
        failure_class=None,
        reason=fact.reason,
        previous_source_id=fact.previous_source_id,
        priority=None,
        health_class=None,
        reason_message=None,
        epoch=fact.version.epoch,
        revision=fact.version.revision,
        # M6.1 RuleVersion.checksum 是 64 hex (无 "sha256:" 前缀),
        # wire 协议 §5.1 要求 "sha256:" + 64 hex; reporter 端
        # 构造 RuleSourceActivationFact 时统一加前缀.
        checksum=fact.version.checksum,
    )


def install_activation_subscriber(
    reporter: AgentReporter,
    bus: Any,
) -> None:
    """订阅 ``_RuleSourceActivationBus``, 把 fact 转 ReportingEvent 后 emit.

    中文
    ----
    1.0 内部 helper: Reporter 用户不需要直接调 (默认 integration
    路径). 测试用.

    English
    --------
    1.0 internal helper: Reporter users don't call directly (default
    integration path). For tests.
    """
    def _on_activation(fact: RuleSourceActivation) -> None:
        event = activation_to_event(fact)
        try:
            reporter.emit(event)
        except Exception:
            # integration 异常隔离, 跟 M6.1.0d 决策一致 (observer
            # 异常不拖垮 publish)
            pass

    bus.subscribe(_on_activation)


__all__: list[str] = []
