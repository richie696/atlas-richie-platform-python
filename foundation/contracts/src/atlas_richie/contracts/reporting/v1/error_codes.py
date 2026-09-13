"""Atlas Richie Agent Reporting Protocol V1 — error_code StrEnum (11 冻结值, DRAFT).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` §6 + ``上报协议-02-transport-v1.md`` §6.

V1 协议 BUG 收口 (richie696 2026-09-13) 新增 2 个错误码:
- ``ENVELOPE_TOO_LARGE`` (413): 任一 ingress envelope 超过 16 KiB
- ``BATCH_TOO_LARGE`` (413): batch 超过 64 KiB

DRAFT, 待 5-owner sign-off + 跨语言合同测试通过后冻结. 新增走 V2 major + ADR.
"""

from __future__ import annotations

from enum import StrEnum


class ReportingErrorCode(StrEnum):
    """Agent Reporting Protocol V1 — 11 错误码 (DRAFT, 协议 §6)."""

    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    MALFORMED_ENVELOPE = "MALFORMED_ENVELOPE"
    UNKNOWN_EVENT_KIND = "UNKNOWN_EVENT_KIND"
    PAYLOAD_SCHEMA_MISMATCH = "PAYLOAD_SCHEMA_MISMATCH"
    INSTANCE_ID_EMPTY = "INSTANCE_ID_EMPTY"
    SEQUENCE_NOT_MONOTONIC = "SEQUENCE_NOT_MONOTONIC"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    STALE_EPOCH = "STALE_EPOCH"
    # V1 协议 BUG 收口新增 (richie696 2026-09-13):
    ENVELOPE_TOO_LARGE = "ENVELOPE_TOO_LARGE"
    BATCH_TOO_LARGE = "BATCH_TOO_LARGE"
    AUTH_FAILED = "AUTH_FAILED"


__all__ = ["ReportingErrorCode"]
