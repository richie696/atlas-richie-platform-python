"""`atlas-richie-sentinel-core` — Sentinel rule engine core (R-SENTINEL-1).

中文
----
Sentinel 家族的**规则引擎层**(Layer 2)。提供:

- `Resource` — 受保护资源的命名 + 类型抽象(对位 Java
  `com.alibaba.csp.sentinel.Entry` resource 名)
- `Context` / `Entry` — 请求上下文 + 入口生命周期(每个
  `with Entry(resource)` 自动经过 slot chain)
- `Node` / `NodeTree` — 节点树(每 resource 1 节点,统计用)
- `Slot` Protocol + `SlotChain` — 职责链,内置
  `NodeSelectorSlot` / `ClusterBuilderSlot` /
  `StatisticSlot` / `FlowSlot` / `DegradeSlot` /
  `SystemSlot` / `ParamFlowSlot` / `AuthoritySlot`
- `RuleManager` — 规则加载(从 file / nacos / redis 源)
- `SlidingWindow` — 滑动窗口统计(对位 Java LeapArray)

**与 primitives 层关系**:
- `DegradeRule` 内部用 `sentinel_primitives.CircuitBreaker`
- `FlowRule.concurrency` 用 `sentinel_primitives.Bulkhead`
- `FlowRule.qps` 用 `sentinel_primitives.TokenBucket`

**与 rules 层关系**:
- `sentinel-rules` wheel 提供 5 类 rule 详细配置
- core 只提供通用 rule 框架

English
--------
Sentinel family Layer 2 — rule engine core. Provides
Resource / Context / Entry / Slot / SlotChain / RuleManager
/ sliding window statistics. Mirrors Java
`com.alibaba.csp.sentinel.slotchain` package.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in R-SENTINEL-1.
    # "Resource",
    # "ResourceType",
    # "Context",
    # "Entry",
    # "Node",
    # "NodeTree",
    # "Slot",
    # "SlotChain",
    # "NodeSelectorSlot",
    # "ClusterBuilderSlot",
    # "StatisticSlot",
    # "FlowSlot",
    # "DegradeSlot",
    # "SystemSlot",
    # "ParamFlowSlot",
    # "AuthoritySlot",
    # "Rule",
    # "RuleManager",
    # "SlidingWindow",
    # "LeapArray",
]
