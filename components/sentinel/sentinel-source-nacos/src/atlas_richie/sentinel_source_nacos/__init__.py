"""`atlas-richie-sentinel-source-nacos` — Nacos-based rule source (M6+).

中文
----
Sentinel 家族的**规则源 — Nacos**(M6+)。从 Nacos 配置中心
加载 5 类 rule,使用 long-poll 拉取变更。1:1 对位 Java
`sentinel-datasource-nacos`,支持 5 个 rule data-id:

- `gateway-flow-rules.json`
- `gateway-degrade-rules.json`
- `gateway-param-flow-rules.json`
- `gateway-system-rules.json`
- `gateway-authority-rules.json`

**为什么 M6+ 才做**:
- Nacos 是 Java 生态强项(我们的用户主要 Java 出身)
- MVP 阶段 file 源 + dashboard push 规则够用
- M6+ 团队熟悉度提升 + 用户有 Nacos 部署后,这个 source 才有价值

English
--------
Sentinel family rule source — Nacos-based. Loads 5 rule
types from Nacos config center with long-poll refresh.
Mirrors Java sentinel-datasource-nacos. Scheduled for
M6+ since MVP can rely on file source + dashboard push.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Populated in M6+.
    # "NacosRuleSource",
    # "NacosConfig",
]
