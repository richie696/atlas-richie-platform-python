"""Atlas Richie Agent Reporting Protocol V1 — draft transport error_code StrEnum (11 值).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` §6 + ``上报协议-02-transport-v1.md`` §6.

V1 协议 BUG 收口 (richie696 2026-09-13) 新增 2 个错误码:
- ``ENVELOPE_TOO_LARGE`` (413): 任一 ingress envelope 超过 16 KiB
- ``BATCH_TOO_LARGE`` (413): batch 超过 64 KiB

The error-code registry belongs to the pending transport draft, not the frozen
inner event-envelope schema. It needs transport-owner sign-off before becoming a
cross-language compatibility commitment.
"""

from __future__ import annotations

from enum import StrEnum


class ReportingErrorCode(StrEnum):
    """Agent Reporting Protocol V1 — 11 draft transport error codes (§6)."""

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
