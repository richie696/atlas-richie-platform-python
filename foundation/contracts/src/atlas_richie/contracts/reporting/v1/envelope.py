"""Atlas Richie Agent Reporting Protocol V1 — envelope frozen dataclass.

1:1 镜像 ``docs/protocols/AGENT_REPORTING_PROTOCOL.md`` §2. 8 必填字段:

- protocol_version
- event_kind
- event_payload (per-kind frozen object)
- instance_id
- startup_epoch
- sequence
- captured_at (Reporter 本地 UTC, 仅诊断)
- received_at (Collector 写入, 唯一服务端权威)

V1 frozen. 任何变更走 V1.1 minor + ADR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .event_kind import ReportingEventKind


@dataclass(frozen=True, slots=True)
class ReportingEnvelope:
    """Agent Reporting Protocol V1 — envelope (8 必填字段).

    字段定义见 ``docs/protocols/AGENT_REPORTING_PROTOCOL.md`` §2.2.
    """

    protocol_version: str
    event_kind: ReportingEventKind
    event_payload: dict[str, Any]
    instance_id: str
    startup_epoch: int
    sequence: int
    captured_at: str  # ISO 8601 UTC microsecond, Reporter 本地 UTC (诊断)
    received_at: str  # ISO 8601 UTC microsecond, Collector 写入 (服务端权威)


__all__ = ["ReportingEnvelope"]
