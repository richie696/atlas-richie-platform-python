"""Atlas Richie Agent Reporting Protocol V1 — payload frozen dataclasses.

1:1 镜像 ``docs/protocols/AGENT_REPORTING_PROTOCOL.md`` §4. 3 个 payload:
- RuleSourceActivatedPayload (RULE_SOURCE_ACTIVATED)
- RuleSourceHealthPayload (RULE_SOURCE_STALE / _DEGRADED)
- RuleExecPayload (RULE_APPLIED / _BLOCKED / _FAILED)

V1 frozen, 字段名/类型/必填属性不可改. 任何变更走 V1.1 minor + ADR.
"""

from __future__ import annotations

from dataclasses import dataclass

# source_id / rule_id 长度上限 (协议 §4.1 / §4.3)
SOURCE_ID_MAX_LEN = 256
RULE_ID_MAX_LEN = 256

# reason_message 脱敏 reason 上限 (协议 §4.2)
REASON_MESSAGE_MAX_LEN = 64

# health_class V1 允许值 (协议 §4.2)
HEALTH_CLASS_VALUES: frozenset[str] = frozenset({"STALE", "DEGRADED", "DISCONNECTED"})

# exec_result V1 允许值 (协议 §4.3)
EXEC_RESULT_VALUES: frozenset[str] = frozenset({"APPLIED", "BLOCKED", "FAILED"})


@dataclass(frozen=True, slots=True)
class RuleSourceActivatedPayload:
    """``RULE_SOURCE_ACTIVATED`` payload (协议 §4.1)."""

    source_id: str
    rule_version_epoch: int
    rule_version_revision: int
    rule_version_checksum: str


@dataclass(frozen=True, slots=True)
class RuleSourceHealthPayload:
    """``RULE_SOURCE_STALE`` / ``RULE_SOURCE_DEGRADED`` payload (协议 §4.2)."""

    source_id: str
    rule_version_epoch: int
    rule_version_revision: int
    rule_version_checksum: str
    health_class: str  # STALE / DEGRADED / DISCONNECTED
    reason_class: str  # stable error class
    reason_message: str = ""  # ≤ 64 bytes 脱敏 reason


@dataclass(frozen=True, slots=True)
class RuleExecPayload:
    """``RULE_APPLIED`` / ``RULE_BLOCKED`` / ``RULE_FAILED`` payload (协议 §4.3)."""

    source_id: str
    rule_id: str
    rule_version_epoch: int
    rule_version_revision: int
    rule_version_checksum: str
    exec_result: str  # APPLIED / BLOCKED / FAILED
    failure_class: str | None = None  # 仅 exec_result=FAILED 时必填


__all__ = [
    "EXEC_RESULT_VALUES",
    "HEALTH_CLASS_VALUES",
    "REASON_MESSAGE_MAX_LEN",
    "RULE_ID_MAX_LEN",
    "RuleExecPayload",
    "RuleSourceActivatedPayload",
    "RuleSourceHealthPayload",
    "SOURCE_ID_MAX_LEN",
]
