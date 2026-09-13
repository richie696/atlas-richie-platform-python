"""Atlas Richie Sentinel — Agent Reporting V1 public API (M6.5.1-6).

中文
----
``atlas_richie.sentinel.reporting`` 1.0 公开 API 表面, 严格 5 个
public 符号 (跟 Mavis 治理 + 主包 0 3rd-party 决策一致):

- :class:`AgentReporter` — 主类, 1.0 兼容入口
- :class:`AgentReporterConfig` — frozen slots dataclass
- :class:`ReporterIdentity` — frozen slots: instance_id + startup_epoch
- :class:`ReportingEvent` — frozen slots dataclass (per-event 投递单元)
- :class:`OverflowPolicy` — StrEnum 3 选 1 显式策略

7 个 Reporter 错误类 (``ReporterConnectionError`` /
``ReporterAuthError`` / ``ReporterProtocolError`` /
``ReporterAckTimeoutError`` / ``ReporterOverflowError`` /
``ReporterSendTimeoutError`` / ``ReporterLeaseError``) 全部继承
主包根 ``SentinelError`` (主包 M1.1 决策, 保证主包 0 3rd-party
依赖).

**不**导出 (Mavis 治理 default-deny):

- ❌ ``Client`` / ``CollectorClient`` / ``AgentReporterClient``
- ❌ ``HealthEvent`` / ``RuleExecEvent`` 任何 per-kind payload 公开类
- ❌ ``*_Factory`` / ``*_Builder`` GoF 模式 (内部实现 OK)
- ❌ 任何 ``_supervisor`` / ``outbox`` / ``transport`` / ``event_builder`` /
  ``auth`` 内部模块
- ❌ 任何 3rd-party 依赖

English
--------
``atlas_richie.sentinel.reporting`` 1.0 public API surface, strictly
5 public symbols (per Mavis governance + main-package 0 3rd-party
decision):

- :class:`AgentReporter` — main class, 1.0 compatible entry
- :class:`AgentReporterConfig` — frozen slots dataclass
- :class:`ReporterIdentity` — frozen slots: instance_id + startup_epoch
- :class:`ReportingEvent` — frozen slots dataclass (per-event submission)
- :class:`OverflowPolicy` — StrEnum 3-of-3 explicit policy

7 Reporter error classes all inherit main-package root
``SentinelError`` (main-package M1.1 decision, ensures main wheel
has zero 3rd-party dependencies).

**Not** exported (Mavis governance default-deny):

- ❌ ``Client`` / ``CollectorClient`` / ``AgentReporterClient``
- ❌ ``HealthEvent`` / ``RuleExecEvent`` any per-kind payload public class
- ❌ ``*_Factory`` / ``*_Builder`` GoF patterns (internal OK)
- ❌ any ``_supervisor`` / ``outbox`` / ``transport`` / ``event_builder`` /
  ``auth`` internal module
- ❌ any 3rd-party dependency
"""

from __future__ import annotations

from ._identity import ReporterIdentity
from .config import AgentReporterConfig, OverflowPolicy
from .errors import (
    ReporterAckTimeoutError,
    ReporterAuthError,
    ReporterConnectionError,
    ReporterError,
    ReporterLeaseError,
    ReporterOverflowError,
    ReporterProtocolError,
    ReporterSendTimeoutError,
)
from .reporter import AgentReporter, ReportingEvent


__all__ = [
    # 5 个核心 public 类 / 枚举
    "AgentReporter",
    "AgentReporterConfig",
    "OverflowPolicy",
    "ReporterIdentity",
    "ReportingEvent",
    # 7 个 Reporter 错误类 (全部继承 SentinelError, 用户可 except SentinelError 统一兜底)
    "ReporterError",
    "ReporterConnectionError",
    "ReporterAuthError",
    "ReporterProtocolError",
    "ReporterAckTimeoutError",
    "ReporterOverflowError",
    "ReporterSendTimeoutError",
    "ReporterLeaseError",
]
