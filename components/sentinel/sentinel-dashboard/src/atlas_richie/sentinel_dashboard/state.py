"""Dashboard 共享状态 (注入到 routes).

中文
----
通过 ``request.state.dashboard`` 在 middleware 注入, 避免全局变量.
所有 route 共享同一份状态, 但状态本身 immutable dataclass, 实际
可变字段 (audit log) 单独管理.

设计原因: 单独成模块避免 routes 跟 app 的循环导入.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DashboardState:
    engine: Any  # SentinelEngine
    metric_registry: Any  # MetricRegistry
    rule_repository: Any  # RuleRepository
    rule_source: Any  # RuleSource | None
    degrade_slot: Any  # DegradeSlot | None
    host: str
    port: int
    allow_admin: bool
    admin_token: str
    audit_log: list  # 共享 list, 最多 1000 条
