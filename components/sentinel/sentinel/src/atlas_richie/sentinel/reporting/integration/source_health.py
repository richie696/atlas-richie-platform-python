"""Atlas Richie Sentinel — Source health → ReportingEvent (M6.5.3).

中文
----
Rule source health 变化 (从 ``RuleSourceSupervisor`` polling) →
``RULE_SOURCE_STALE`` / ``RULE_SOURCE_DEGRADED`` ``ReportingEvent``.

转换规则:

- ``source_id`` → ReportingEvent.source_id
- ``health_class`` (str enum: healthy / stale / degraded) → kind
  + health_class
- ``epoch`` / ``revision`` / ``checksum`` → version triplet, **成组可选**
  (协议 §5.2): 首次加载失败 / 无 last-known-good 场景, 3 字段全部
  省略 (ReportingEvent 用 ``None`` 表示)
- ``reason_message`` → reason_message (≤ 64 chars, 协议 REASON_MESSAGE_MAX_LEN)

English
--------
Rule source health change (from ``RuleSourceSupervisor`` polling)
→ ``RULE_SOURCE_STALE`` / ``RULE_SOURCE_DEGRADED`` ``ReportingEvent``.

Translation rules:

- ``source_id`` → ReportingEvent.source_id
- ``health_class`` (str enum: healthy / stale / degraded) → kind +
  health_class
- ``epoch`` / ``revision`` / ``checksum`` → version triplet,
  **group-optional** (protocol §5.2): first-load-failure / no-
  last-known-good scenario, all 3 fields omitted (ReportingEvent
  uses ``None`` to indicate)
- ``reason_message`` → reason_message (≤ 64 chars, protocol
  REASON_MESSAGE_MAX_LEN)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .._identity import ReporterIdentity
from ..reporter import AgentReporter, ReportingEvent
from atlas_richie.contracts.reporting.v1 import ReportingEventKind


@dataclass(slots=True, frozen=True)
class SourceHealthChange:
    """内部 source health 变化 fact (integration 层).

    中文
    ----
    ``health_class`` ∈ ``{"healthy", "stale", "degraded"}`` (V1 frozen
    enum 字符串, 跟协议 §5.2 一致). version triplet 3 字段成组可选.

    English
    --------
    ``health_class`` ∈ ``{"healthy", "stale", "degraded"}`` (V1 frozen
    enum string, per protocol §5.2). version triplet 3 fields group-
    optional.
    """

    source_id: str
    health_class: str
    epoch: int | None
    revision: int | None
    checksum: str | None
    reason_message: str


def _kind_from_health_class(health_class: str) -> str:
    """健康事件 kind 映射.

    中文
    ----
    - ``stale`` → ``RULE_SOURCE_STALE``
    - ``degraded`` → ``RULE_SOURCE_DEGRADED``
    - ``healthy`` → 不发 (健康状态是默认, 不发 event, 减少 noise)
    """
    if health_class == "stale":
        return ReportingEventKind.RULE_SOURCE_STALE.value
    if health_class == "degraded":
        return ReportingEventKind.RULE_SOURCE_DEGRADED.value
    if health_class == "healthy":
        raise ValueError(
            "healthy is default state; no event to emit (避免 noise)"
        )
    raise ValueError(
        f"health_class must be one of {{stale, degraded, healthy}}, "
        f"got {health_class!r}"
    )


def health_change_to_event(change: SourceHealthChange) -> ReportingEvent:
    """``SourceHealthChange`` → ``ReportingEvent``."""
    return ReportingEvent(
        kind=_kind_from_health_class(change.health_class),
        source_id=change.source_id,
        resource=None,
        rule_id=None,
        exec_result=None,
        failure_class=None,
        reason=None,
        previous_source_id=None,
        priority=None,
        health_class=change.health_class,
        reason_message=change.reason_message,
        epoch=change.epoch,
        revision=change.revision,
        checksum=change.checksum,
    )


def install_source_health_subscriber(
    reporter: AgentReporter,
    on_health_change: Any,
) -> None:
    """订阅 source health 变化 callback, 转 ReportingEvent 后 emit.

    中文
    ----
    1.0 内部 helper: ``on_health_change`` 是 ``Callable[[SourceHealthChange], None]``,
    由调用方 (e.g. RuleSourceSupervisor) 在 health 变化时调.

    English
    --------
    1.0 internal helper: ``on_health_change`` is
    ``Callable[[SourceHealthChange], None]``, called by the caller
    (e.g. RuleSourceSupervisor) on health change.
    """
    def _on_change(change: SourceHealthChange) -> None:
        try:
            event = health_change_to_event(change)
        except ValueError:
            return  # healthy / 未知 → 跳过
        try:
            reporter.emit(event)
        except Exception:
            pass

    on_health_change(_on_change)


__all__: list[str] = []
