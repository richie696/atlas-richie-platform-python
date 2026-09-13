"""Atlas Richie Agent Reporting Protocol V1 — per-kind payload frozen dataclasses.

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` §5. 3 个 payload:
- ``RuleSourceActivatedPayload`` (RULE_SOURCE_ACTIVATED)
- ``RuleSourceHealthPayload`` (RULE_SOURCE_STALE / _DEGRADED)
- ``RuleExecPayload`` (RULE_APPLIED / _BLOCKED / _FAILED)

DRAFT, 待 5-owner sign-off + 跨语言合同测试通过后冻结.
V1.x spec revision 允许加 optional field; 改语义走 V2 major + ADR.
"""

from __future__ import annotations

from dataclasses import dataclass

# source_id / rule_id 长度上限 (协议 §5.1 / §5.3)
SOURCE_ID_MAX_LEN = 256
RULE_ID_MAX_LEN = 256

# reason_message 脱敏 reason 上限 (协议 §5.2)
REASON_MESSAGE_MAX_LEN = 64

# rule_version_checksum 格式: ``sha256:`` + 64 hex chars (协议 §5.1)
RULE_VERSION_CHECKSUM_PREFIX = "sha256:"
RULE_VERSION_CHECKSUM_HEX_LEN = 64


@dataclass(frozen=True, slots=True)
class RuleSourceActivatedPayload:
    """``RULE_SOURCE_ACTIVATED`` payload (协议 §5.1)."""

    source_id: str
    rule_version_epoch: int
    rule_version_revision: int
    rule_version_checksum: str


@dataclass(frozen=True, slots=True)
class RuleSourceHealthPayload:
    """``RULE_SOURCE_STALE`` / ``RULE_SOURCE_DEGRADED`` payload (协议 §5.2).

    3 个 ``rule_version_*`` 字段**成组可选**: 同时出现或同时省略.
    首次加载失败等无有效快照场景中, 3 字段全部省略.
    """

    source_id: str
    health_class: str  # HealthClass value
    reason_class: str  # ReasonClass value
    # 成组可选: 存在时全部 3 字段必填
    rule_version_epoch: int | None = None
    rule_version_revision: int | None = None
    rule_version_checksum: str | None = None
    # 可选: 脱敏 reason, ≤ 64 字节
    reason_message: str | None = None


@dataclass(frozen=True, slots=True)
class RuleExecPayload:
    """``RULE_APPLIED`` / ``RULE_BLOCKED`` / ``RULE_FAILED`` payload (协议 §5.3)."""

    source_id: str
    rule_id: str
    rule_version_epoch: int
    rule_version_revision: int
    rule_version_checksum: str
    exec_result: str  # ExecResult value
    # 当且仅当 exec_result=FAILED 时为 ReasonClass 枚举值; 其余结果必须 None
    failure_class: str | None = None


__all__ = [
    "REASON_MESSAGE_MAX_LEN",
    "RULE_ID_MAX_LEN",
    "RULE_VERSION_CHECKSUM_HEX_LEN",
    "RULE_VERSION_CHECKSUM_PREFIX",
    "RuleExecPayload",
    "RuleSourceActivatedPayload",
    "RuleSourceHealthPayload",
    "SOURCE_ID_MAX_LEN",
]
