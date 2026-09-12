"""Sentinel rules 子包(M1.5)。

中文
----
集中 re-export RuleVersion / RuleSnapshot / RuleIndex / RuleRepository
/ ResourceSelector。M2 才实现具体的 FlowRule / DegradeRule /
ParamFlowRule / AuthorityRule / SystemRule 等 5 类规则 dataclass。

English
--------
``rules/`` re-exports RuleVersion / RuleSnapshot / RuleIndex /
RuleRepository / ResourceSelector. M2 implements the concrete
FlowRule / DegradeRule / ParamFlowRule / AuthorityRule / SystemRule
dataclasses."""

from __future__ import annotations

from .index import IndexedRule, RuleIndex
from .repository import EventSubscriber, RuleRepository
from .selector import ResourceSelector, SelectorKind
from .snapshot import RuleSnapshot, RuleSnapshotAppliedEvent, RuleVersion

__all__ = [
    "RuleVersion",
    "RuleSnapshot",
    "RuleSnapshotAppliedEvent",
    "ResourceSelector",
    "SelectorKind",
    "IndexedRule",
    "RuleIndex",
    "RuleRepository",
    "EventSubscriber",
]
