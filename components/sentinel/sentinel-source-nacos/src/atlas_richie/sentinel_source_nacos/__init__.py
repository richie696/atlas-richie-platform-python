"""`atlas-richie-sentinel-source-nacos` — Nacos-based rule source (M6.1).

中文
----
Sentinel 家族的**规则源 — Nacos** (M6.1)。从 Nacos 配置中心加载 5 类
rule,使用 long-poll 拉取变更;实现新契约 :class:`SnapshotRuleSource`,
经主包 :class:`SentinelEngine` 的 ``assemble_sources`` 入口接入多源仲裁。

1:1 对位 Java `sentinel-datasource-nacos`;5 个 rule data-id 约定:

- `<namespace>-flow-rules.json`
- `<namespace>-degrade-rules.json`
- `<namespace>-param-flow-rules.json`
- `<namespace>-system-rules.json`
- `<namespace>-authority-rules.json`

**当前状态 (M6.1)**:

- M6.1.1 ✅ wheel scaffold (`atlas_richie.sentinel_source_nacos` package +
  pyproject + workspace + zero-3rd-party 主包 不变)
- M6.1.2 ⏳ NacosRuleSourceConfig frozen dataclass
- M6.1.3 ⏳ 首次读取 → codec → publish → subscribe 生命周期
- M6.1.4 ⏳ 错误分类 (断线 / 鉴权 / 配置删除 / 空配置 / 重复回调 / 乱序 /
  坏规则) + last-known-good + 有界指数退避
- M6.1.5 ⏳ 显式管理订阅 + 幂等 aclose()
- M6.1.6 ⏳ contract suite + Nacos-specific tests

**依赖隔离 (M6.1.1 硬约束)**:

- 仅本 wheel 声明 `nacos-sdk-python>=2.0,<3.0` 依赖
- 主包 / ASGI / HTTPX / Dashboard 依赖图**不**变 (主包仍零 3rd-party)
- `rg "nacos"` 主包源码验证不命中 (extension isolation)

English
--------
Sentinel family rule source — Nacos-based (M6.1). Loads 5 rule types
from Nacos config center with long-poll refresh; implements the new
:class:`SnapshotRuleSource` contract, plugged in via main package's
``assemble_sources`` entry.

1:1 mirror of Java `sentinel-datasource-nacos`; 5 rule data-id
conventions listed above.

**Dependency isolation (M6.1.1 hard constraint)**:

- Only this wheel declares `nacos-sdk-python>=2.0,<3.0`
- Main package / ASGI / HTTPX / Dashboard dependency graph **unchanged**
  (main package remains zero 3rd-party)
- `rg "nacos"` on main package source proves isolation
"""

from __future__ import annotations

from .config import (
    NacosAuth,
    NacosRuleSourceConfig,
    NacosSourceError,
    NacosSourceState,
    NacosTLS,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # M6.1.2 (done): 不可变 config + 值对象 + 状态 / 错误 enum
    "NacosAuth",
    "NacosTLS",
    "NacosRuleSourceConfig",
    "NacosSourceState",
    "NacosSourceError",
    # Populated by M6.1.3 - M6.1.5:
    # "NacosRuleSource",
    # "NacosSourceMetricSnapshot",  # 公开 metric DTO (operator observability)
]
