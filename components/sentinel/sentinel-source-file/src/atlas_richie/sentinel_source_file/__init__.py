"""`atlas-richie-sentinel-source-file` — file-based rule source (R-SENTINEL-2).

中文
----
Sentinel 家族的**规则源 — 文件**。从 YAML / JSON 文件加载
所有 5 类 rule,支持 `watchfiles` 监听文件变更热重载(无需
重启进程)。

**配置文件格式**(YAML):
```yaml
flow:
  - resource: order:create
    grade: qps
    count: 100
    controlBehavior: reject
  - resource: order:query
    grade: thread
    count: 50
degrade:
  - resource: pay:charge
    grade: rt
    count: 200     # ms
    timeWindow: 10 # s
    minRequestAmount: 10
    slowRatioThreshold: 0.5
system:
  - highestSystemLoad: 4.0
    highestCpuUsage: 0.8
    qps: 300
    avgRt: 100
    maxThread: 200
```

**与 core 关系**:
- 实现 `RuleManager.load()` 接口
- 调用方:`Sentinel.load_rules("file:///etc/sentinel/rules.yaml")`

English
--------
Sentinel family rule source — file-based. Loads 5 rule
types from YAML / JSON files with hot-reload via
`watchfiles`. Mirrors Java sentinel-datasource-file.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in R-SENTINEL-2.
    # "FileRuleSource",
    # "RuleFileFormat",
    # "RuleFileWatcher",
]
