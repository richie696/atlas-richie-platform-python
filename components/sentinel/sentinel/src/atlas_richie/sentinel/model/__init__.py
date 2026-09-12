"""Sentinel 领域模型。

中文
----
集中 re-export 资源 / 上下文 / 参数 / outcome / lease / 枚举 6 类模型。
M1.1 范围;M1.2+ 的 Engine / Slot 在此基础上构建。

English
--------
Domain model: centralised re-export of the 6 model files.
M1.1 scope; M1.2+ Engine / Slot builds on top."""

from __future__ import annotations

from .argument import InvocationArguments
from .context import (
    SentinelContext,
    TraceId,
    bind_current_context,
    current_context,
    reset_current_context,
)
from .decision import NoopSlotLease, SlotLease
from .enums import BlockReason, EngineState, RuleMatchKind
from .outcome import Outcome, OutcomeKind
from .resource import Resource, ResourceKind, TrafficType

__all__ = [
    # resource
    "Resource",
    "ResourceKind",
    "TrafficType",
    # context
    "SentinelContext",
    "TraceId",
    "bind_current_context",
    "current_context",
    "reset_current_context",
    # argument
    "InvocationArguments",
    # outcome
    "Outcome",
    "OutcomeKind",
    # decision / lease
    "SlotLease",
    "NoopSlotLease",
    # enums
    "BlockReason",
    "RuleMatchKind",
    "EngineState",
]
