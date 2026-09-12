"""`atlas-richie-sentinel-rules` — the 5 Sentinel rule types (R-SENTINEL-3 + 4).

中文
----
Sentinel 家族的**规则类型层**(Layer 2.5 / M3-M4)。1:1 对位
Java Sentinel 5 大规则:

- `FlowRule` — 流控(QPS / 并发线程数 / 预热 / 排队等待)
- `DegradeRule` — 降级熔断(慢调用比例 / 异常比例 / 异常数)
- `ParamFlowRule` — 热点参数(按 header / query / cookie
  维度差异化限流)
- `SystemRule` — 系统自适应(CPU / Load / 入口 QPS /
  平均 RT / 并发)
- `AuthorityRule` — 黑白名单(按来源 header 识别)

**为什么 5 个 rule 合并到 1 个 wheel**:
- 共享基础类型(`Rule` / `RuleManager` / 阈值基类)
- 5 个独立 wheel 反而增加管理成本而不增剪裁灵活性
- 1.0 GA 后保持稳定,任何变更走同一个 semver

**与 core 关系**:
- core 提供通用 Rule / RuleManager 框架
- rules 包把 5 个具体 rule 类型填进框架

English
--------
Sentinel family Layer 2.5 — the 5 rule types. 1:1
functional parity with Java Sentinel rule types.
Bundled into a single wheel because they share base
types; splitting would inflate management cost
without increasing installable flexibility.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in R-SENTINEL-3 (Flow/Degrade) + R-SENTINEL-4 (ParamFlow/System/Authority).
    # "FlowRule",
    # "FlowRuleController",
    # "DegradeRule",
    # "ParamFlowRule",
    # "ParamFlowItem",
    # "SystemRule",
    # "AuthorityRule",
    # "RuleType",
    # "Grade",
    # "ControlBehavior",
]
