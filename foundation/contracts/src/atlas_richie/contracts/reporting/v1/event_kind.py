"""Atlas Richie Agent Reporting Protocol V1 — event_kind 枚举 (Draft, 1:1 镜像).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` §4. V1 6 个
event_kind (DRAFT, 待 5-owner sign-off + 跨语言合同测试通过后冻结).
任何新增走 V2 major + 独立 ADR (V1.x spec revision **不**扩展枚举).

注意: V1 协议 BUG 收口 (richie696 2026-09-13) 改了 ingress envelope
为 7 字段 (无 `received_at`), 但 6 个 event_kind 仍保持不变.
"""

from __future__ import annotations

from enum import StrEnum


class ReportingEventKind(StrEnum):
    """Agent Reporting Protocol V1 — 6 event_kind (DRAFT, 待冻结)."""

    RULE_SOURCE_ACTIVATED = "RULE_SOURCE_ACTIVATED"
    RULE_SOURCE_STALE = "RULE_SOURCE_STALE"
    RULE_SOURCE_DEGRADED = "RULE_SOURCE_DEGRADED"
    RULE_APPLIED = "RULE_APPLIED"
    RULE_BLOCKED = "RULE_BLOCKED"
    RULE_FAILED = "RULE_FAILED"


# V1 兼容性矩阵 (协议 §4.2 + 9 兼容矩阵):
# - source-switch: RULE_SOURCE_ACTIVATED 走 source 切换, 必填 4 字段
# - health: RULE_SOURCE_STALE / _DEGRADED 走 health 事件, 必填 source_id
#   + health_class + reason_class; 3 个 rule_version_* 字段成组可选
#   (无 last-known-good 快照时全部省略)
# - biz-exec: RULE_APPLIED / _BLOCKED / _FAILED 走业务执行, 必填 source_id
#   + rule_id + exec_result; failure_class 仅 FAILED 必填
#
# health 事件**不得**替代 source-switch 事件. Source 切换总是走
# RULE_SOURCE_ACTIVATED.


# Health class 允许值 (协议 §5.2)
class HealthClass(StrEnum):
    """Health event — 3 允许值 (协议 §5.2)."""

    STALE = "STALE"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


# Reason class 冻结枚举 (协议 §5.4, 7 冻结值, V1 不可扩展)
class ReasonClass(StrEnum):
    """稳定错误分类, 7 冻结值 (协议 §5.4).

    仅 stable error class; **不得**写原始异常类型、消息或供应商错误码.
    新增走 V2 major + 独立 ADR.
    """

    EMPTY_DATA_ID = "EMPTY_DATA_ID"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"
    DECODE_FAILED = "DECODE_FAILED"
    STATE_INVALID = "STATE_INVALID"
    UNKNOWN = "UNKNOWN"


# Exec result 允许值 (协议 §5.3)
class ExecResult(StrEnum):
    """业务执行结果, 3 允许值 (协议 §5.3)."""

    APPLIED = "APPLIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


__all__ = [
    "ExecResult",
    "HealthClass",
    "ReasonClass",
    "ReportingEventKind",
]
