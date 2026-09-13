"""Atlas Richie Agent Reporting Protocol V1 — event_kind 枚举 (frozen).

1:1 镜像 ``docs/protocols/AGENT_REPORTING_PROTOCOL.md`` §3. V1 frozen,
6 个允许值. 任何新增走 V1.1 minor + ADR.
"""

from __future__ import annotations

from enum import StrEnum


class ReportingEventKind(StrEnum):
    """Agent Reporting Protocol V1 — 6 event_kind (frozen).

    协议: ``atlas-richie.reporting/v1``.
    配套设计文档: ``docs/M6.5.7-ENVELOPE-FREEZE.md``.
    """

    RULE_SOURCE_ACTIVATED = "RULE_SOURCE_ACTIVATED"
    RULE_SOURCE_STALE = "RULE_SOURCE_STALE"
    RULE_SOURCE_DEGRADED = "RULE_SOURCE_DEGRADED"
    RULE_APPLIED = "RULE_APPLIED"
    RULE_BLOCKED = "RULE_BLOCKED"
    RULE_FAILED = "RULE_FAILED"


__all__ = ["ReportingEventKind"]
