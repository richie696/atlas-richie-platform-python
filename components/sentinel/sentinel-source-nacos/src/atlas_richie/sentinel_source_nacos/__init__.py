"""`atlas-richie-sentinel-source-nacos` — Nacos-based rule source (M6.1).

中文
----
Sentinel 家族的**规则源 — Nacos** (M6.1)。从 Nacos 配置中心加载 5 类
rule,使用 polling 拉取变更;实现新契约 :class:`SnapshotRuleSource`,
经主包 :class:`SentinelEngine` 的 ``assemble_sources`` 入口接入多源仲裁。

1:1 对位 Java `sentinel-datasource-nacos`;5 个 rule data-id 约定:

- `<data_id_prefix>-flow-rules.json`
- `<data_id_prefix>-degrade-rules.json`
- `<data_id_prefix>-param-flow-rules.json`
- `<data_id_prefix>-system-rules.json`
- `<data_id_prefix>-authority-rules.json`

完整 data-id 由 :meth:`NacosRuleSourceConfig.data_id_for` 生成。

**当前状态 (M6.1)**:

- M6.1.1 ✅ wheel scaffold (`atlas_richie.sentinel_source_nacos` package +
  pyproject + workspace + zero-3rd-party 主包 不变)
- M6.1.2 ✅ 不可变 `NacosRuleSourceConfig` + `NacosAuth` + `NacosTLS` +
  `NacosSourceState` (StrEnum) + `NacosSourceError` (StrEnum)
- M6.1.3 ✅ 5 类 rule data-id → :class:`RuleSnapshot` 解码
  (:func:`decode_rule_snapshot`) + 首次读取 → yield 生命周期
- M6.1.4 ✅ 5 类错误分类 (AUTH / NOT_FOUND / EMPTY / DECODE / NETWORK) +
  状态机 (CONNECTING / READY / STALE / DISCONNECTED / CLOSED) +
  有界指数退避 + last-known-good
- M6.1.5 ✅ polling 生命周期 + 幂等 aclose() + 脱敏
- M6.1.6 ✅ contract suite + Nacos-specific tests

**依赖隔离 (M6.1.1 硬约束)**:

- 仅本 wheel 声明 `nacos-sdk-python>=3.0,<4.0` 依赖
- 主包 / ASGI / HTTPX / Dashboard 依赖图**不**变 (主包仍零 3rd-party)
- `rg "nacos"` 主包源码验证不命中 (extension isolation)

**C 层物理隔离 (M6.1.0 P0 决策 1)**:

- 本 extension **不** import 主包 `atlas_richie.sentinel.source._supervisor.*`
- 测试断言: `forbidden module prefix = "atlas_richie.sentinel.source._supervisor"`

English
--------
Sentinel family rule source — Nacos-based (M6.1). Loads 5 rule types
from Nacos config center with polling refresh; implements the new
:class:`SnapshotRuleSource` contract, plugged in via main package's
``assemble_sources`` entry.

1:1 mirror of Java `sentinel-datasource-nacos`; 5 rule data-id
conventions listed above (full data-id via
:meth:`NacosRuleSourceConfig.data_id_for`).

**Dependency isolation (M6.1.1 hard constraint)**:

- Only this wheel declares `nacos-sdk-python>=3.0,<4.0`
- Main package / ASGI / HTTPX / Dashboard dependency graph **unchanged**
  (main package remains zero 3rd-party)
- `rg "nacos"` on main package source proves isolation

**C-layer isolation (M6.1.0 P0 decision 1)**:

- This extension does **not** import main-package
  `atlas_richie.sentinel.source._supervisor.*`
- Test enforces: `forbidden module prefix = "atlas_richie.sentinel.source._supervisor"`
"""

from __future__ import annotations

from .codec import NacosCodecError, NacosDecodeError
from .config import (
    NacosAuth,
    NacosRuleSourceConfig,
    NacosSourceError,
    NacosSourceState,
    NacosTLS,
)
from .source import NacosRuleSource

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # M6.1.2 (done): 不可变 config + 值对象 + 状态 / 错误 enum
    "NacosAuth",
    "NacosTLS",
    "NacosRuleSourceConfig",
    "NacosSourceState",
    "NacosSourceError",
    # M6.1.3 (done): 5 类 rule data-id → RuleSnapshot 解码
    "NacosCodecError",
    "NacosDecodeError",
    # M6.1.3 - M6.1.5 (done): 完整生命周期 + 错误分类 + aclose
    "NacosRuleSource",
]
