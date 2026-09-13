# MIGRATION-M6 — 1.0 → 1.x (M6.1) 迁移指南

| Field | Value |
| ----- | ----- |
| Document | `MIGRATION-M6.md` |
| Status | **M6.1.0c — 与 `R-SENTINEL-M6.1.0b-api-delta.md` v3 同步, 待用户复核** |
| Date | 2026-09-13 |
| Pre-req | M6.1.0b API delta 5 owner 签字 |
| Cross-ref | `R-SENTINEL-M6.1.0b-api-delta.md` (决策 1-5) / `docs/rule_source_activation.md` v3 / `PLANNING.md` §M6.1.0a / `DESIGN.md` §10.3 L1040-1089 |

> 中文
> ----
> 本文档是 M6.1 (1.x 阶段) 多源仲裁路径的迁移指南, 由 `R-SENTINEL-M6.1.0b-api-delta.md`
> v3 决策 1-5 决定。**核心承诺**: 1.0 公共面 (单源 `RuleSource.start(repository)` 路径)
> 在 1.x 全程保留, 零代码改动可用, **不**自动获多源 / failover 能力。
>
> English
> --------
> This document is the migration guide for the M6.1 (1.x phase) multi-source
> arbitration path, decided by `R-SENTINEL-M6.1.0b-api-delta.md` v3 decisions
> 1-5. **Core promise**: 1.0 public surface (single-source `RuleSource.start(repository)`
> path) is preserved unchanged for the entire 1.x phase, with zero code changes
> required; **does not** automatically gain multi-source / failover capability.

---

## 0. 30 秒决策树 (30-second decision tree)

> 问: 我现在 1.0 代码**是否**只使用单个 `RuleSource` (典型情况: 一个 `FileRuleSource`)?
>
> 答:
> - **是** → **零代码改动**, 1.0 路径继续工作, 直接跳到 §1.A.
> - **否, 我现在 1.0 就有多个 RuleSource 在同时跑** → §1.B, 1.x 阶段必须升级.
> - **我是 extension / 二次开发作者** → §1.C.

> English
> --------
> Q: Does my current 1.0 code use **only one** `RuleSource` (typical case: a
> single `FileRuleSource`)?
>
> A:
> - **Yes** → **zero code changes**, 1.0 path keeps working, jump to §1.A.
> - **No, I already run multiple RuleSources in 1.0** → §1.B, must upgrade in 1.x.
> - **I am an extension / secondary developer** → §1.C.

---

## 1. 三类用户迁移路径 (Three user migration paths)

### 1.A. 1.0 单源用户 (1.0 single-source user) — 零代码改动

**典型用户画像**:
- 主包 1.0 用 `FileRuleSource(path=...)` 加载 JSON / YAML 规则文件
- 或自己写了一个 1.0 形态的 `RuleSource` 实现 (3 个方法: `start(repository)` /
  `stop()` / `latest()`)
- 业务代码只调 `SentinelEngine.entry(...)` 做准入决策, 不接触 Source

**1.x 行为**:
- 代码**完全不变**: `RuleSource.start(repository)` 继续工作
- `FileRuleSource` 内部被实现为 `LegacyRuleSource` (1.0 契约保持)
- 1.0 公共符号 `RuleSource` 保留为 `LegacyRuleSource` 的 type alias, 不破坏 import
- **不**自动获多源 / failover / activation fact; 这些是 M6.1+ 新能力, 需主动升级

**何时升级到新路径**:
- 需要**多源** (e.g. Nacos + 本地 fallback) → 升级到 §1.C 路径
- 需要**failover** (active Source stale 后自动切到次高优先级 ready Source) → 升级到 §1.C 路径
- 需要**active Source 切换可观测** (内部 `RuleSourceActivation` fact 走 Reporter
  通道) → 升级到 §1.C 路径, 并配合 M6.5.7 envelope 冻结

**代码示例 (1.0 路径, 1.x 仍可用)**:

```python
# 1.0 写法, 1.x 阶段**不**需要改
# 注: atlas_richie.sentinel 主包只导出 __version__ (PEP 562),
# 公共面走子模块 import (与 QUICK_START / EXTENSION_GUIDE / RULE_REFERENCE 一致)
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.source.rule_source import (
    FileRuleSource, RuleSource,  # 1.0 公共符号, 1.x 保留为 LegacyRuleSource alias
)

async def main() -> None:
    engine = SentinelEngine(...)
    repository = RuleRepository()
    source = FileRuleSource(path="/etc/sentinel/rules.json", poll_interval=3.0)
    source.start(repository)  # 1.0 形态, 直连 repository, 不经 Supervisor
    async with engine:
        await engine.entry("acquire_flow", resource="order:create")
    # engine / repository / source 都不需要 .close() (Repository 被动)
    # source.stop() 由用户决定
```

> English: 1.0 single-source users keep their existing code unchanged. `RuleSource`
> is preserved as a 1.x type alias of `LegacyRuleSource`. `FileRuleSource` remains
> a 1.0 implementation. Multi-source / failover / activation are opt-in via the
> new `assemble_sources()` entry point (see §1.C).

### 1.B. 1.0 多源用户 (1.0 multi-source user) — 必须升级

**典型用户画像 (罕见)**:
- 1.0 阶段**已**用某种"非官方"方式跑多个 `RuleSource` (e.g. 自己写一个 wrapper
  按优先级轮询, 或多次手动调 `repository.apply_snapshot`)

**1.x 行为**:
- **必须**升级到 `SnapshotRuleSource` + `assemble_sources()` 路径
- 1.x 不再支持"多个 `LegacyRuleSource` 拼装" (因为 `LegacyRuleSource` 不经 Supervisor)
- 用户**必须**:
  1. 把现有 `RuleSource` 实现改写为 `SnapshotRuleSource` 形态 (`snapshots() -> AsyncIterator[RuleSnapshot]`
     + `aclose()`)
  2. 显式声明每个 Source 的 `priority` (大值优先, 全局唯一) 和 `failover_after` (短抖动容错窗口)
  3. 调 `engine.assemble_sources([RuleSourceAssembly(source, priority, failover_after), ...], repository=repo)`

**代码示例 (升级后)**:

```python
# 1.x 新写法, 替代 1.0 的"非官方"多源 wrapper
from datetime import timedelta
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.source.rule_source import (
    RuleSourceAssembly, SnapshotRuleSource,
)

async def main() -> None:
    engine = SentinelEngine(...)
    repository = RuleRepository()
    nacos_src: SnapshotRuleSource = NacosRuleSource(...)  # 必须实现新契约
    local_src: SnapshotRuleSource = FileRuleSourceV2(...)  # 必须升级为新契约

    await engine.assemble_sources(
        [
            RuleSourceAssembly(
                source=nacos_src, priority=100, failover_after=timedelta(seconds=5),
            ),
            RuleSourceAssembly(
                source=local_src, priority=10, failover_after=timedelta(seconds=2),
            ),
        ],
        repository=repository,
    )
    async with engine:
        await engine.entry("acquire_flow", resource="order:create")
    # engine.aclose() 等 Supervisor 关闭所有 Source 任务后再返回
```

> English: 1.0 multi-source users (rare) must migrate their `RuleSource`
> implementations to `SnapshotRuleSource` (the new contract with
> `snapshots()` and `aclose()`), declare explicit `priority` and
> `failover_after`, and call `engine.assemble_sources()`. The 1.x phase
> does not support composing multiple `LegacyRuleSource` instances.

### 1.C. extension 二次开发作者 (extension / secondary developer)

**典型用户画像**:
- 在写 / 维护一个 `SnapshotRuleSource` 实现 (e.g. Nacos source, OpenSergo source,
  自定义 KV source)
- 或在维护 1.0 旧 `RuleSource` 实现 (e.g. 自己的 ETL pipeline 用 `start/stop/latest`)

**1.x 路径选择**:
- **新 extension** (Nacos / OpenSergo / 新 KV source) → **必须**实现 `SnapshotRuleSource`,
  使用 `assemble_sources()` 入口
- **已有 1.0 旧 extension** → 1.x 全程保留, 用户走 `install_legacy_source()` 入口
- **不允许** 1.0 旧 extension 假装"经 Supervisor 仲裁"; shim 路径会改变 1.0 行为,
  违反 1.0 锁定承诺

**代码示例 (新 SnapshotRuleSource 形态)**:

```python
# 路径: components/sentinel/sentinel-source-nacos/src/atlas_richie/sentinel_source_nacos/
# 主包**不**导入 Nacos SDK, 全部走 Port
from typing import AsyncIterator
from atlas_richie.sentinel.source.rule_source import SnapshotRuleSource
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot

class NacosRuleSource(SnapshotRuleSource):
    source_id: str  # 稳定字符串, 配置时声明, e.g. "nacos-prod"

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:  # type: ignore[override]
        """Yield complete validated RuleSnapshot; 失败不 yield, 保留 last-known-good."""
        if False:  # placeholder for type checker
            yield  # pragma: no cover
        ...

    async def aclose(self) -> None:
        """幂等关闭: 取消 listener, 停止重连, 关闭 SDK."""
        ...
```

> English: new extensions must implement `SnapshotRuleSource` and use
> `assemble_sources()`. Existing 1.0 legacy extensions are preserved
> unchanged and must use `install_legacy_source()`. Shim wrapping a
> 1.0 implementation as `SnapshotRuleSource` is forbidden because it
> silently changes behavior (no Supervisor arbitration, no failover).

---

## 2. 公开符号变化 (Public Symbol Delta)

来源: `R-SENTINEL-M6.1.0b-api-delta.md` §3, 完整列表见原文档。

### 2.1 新增 (Add)

| Symbol | 用途 |
| ------ | ---- |
| `SnapshotRuleSource` (Protocol) | 新契约 Port, `assemble_sources` 仅接受此类型 |
| `LegacyRuleSource` (Protocol) | 1.0 旧契约 Port (显式导出, **不**是私有 Port) |
| `RuleSourceAssembly` (frozen dataclass) | 公开 immutable assembly DTO |
| `SentinelEngine.assemble_sources()` | 多源仲裁入口; 接收 `Sequence[RuleSourceAssembly]`, 必填 `repository` |
| `SentinelEngine.install_legacy_source()` | 1.0 兼容入口; 接收 `LegacyRuleSource` + 必填 `repository` |

### 2.2 修改 (Change)

| Symbol | 变更 |
| ------ | ---- |
| `RuleSource` (1.0 公共符号) | **保留**, 改为 `LegacyRuleSource` 的 type alias |
| `FileRuleSource` (1.0 实现) | 内部实现改为 `LegacyRuleSource` 形态, 公共 API 不变 |

### 2.3 废弃 (Deprecate)

| Symbol | 弃用版本 | 计划删除 |
| ------ | -------- | -------- |
| `RuleSource.start(stop/latest)` 形态 | 1.x 末 (≥ 2 minor 或 6 个月, 以较晚者为准) | **不得早于 2.0**, 且需未来 ADR |

**关键澄清**: 1.x 全程**不**删除 `RuleSource` (alias → `LegacyRuleSource`),
1.x 全程**不**发出 deprecation warning (避免 1.0 用户 noise)。

### 2.4 删除 (Remove)

无。1.x 全程保留所有 1.0 公共符号 (1.0 API 锁定承诺)。

---

## 3. 互斥约束 (Multimode Mutex)

**`multimode_conflict`**:
- 同一 `SentinelEngine` 实例上, **`assemble_sources()` 与 `install_legacy_source()` 互斥**
- 调用任一入口后, 再调另一个入口抛 `SentinelConfigurationError("multimode_conflict")`
- 目的: 防止遗留 Legacy Source 绕过 Supervisor 改写多源仲裁结果

```python
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.source.rule_source import (
    RuleSourceAssembly, SnapshotRuleSource, LegacyRuleSource,
)
from atlas_richie.sentinel.errors import SentinelConfigurationError

engine = SentinelEngine(...)

# 路径 1: 多源 (新)
await engine.assemble_sources([...], repository=repo)
engine.install_legacy_source(some_legacy, repository=repo)
# ↑ 抛 SentinelConfigurationError("multimode_conflict")

# 路径 2: 1.0 兼容 (旧)
engine.install_legacy_source(some_legacy, repository=repo)
await engine.assemble_sources([...], repository=repo)
# ↑ 抛 SentinelConfigurationError("multimode_conflict")
```

> English: `assemble_sources()` and `install_legacy_source()` are mutually
> exclusive on the same `SentinelEngine` instance. Violation raises
> `SentinelConfigurationError("multimode_conflict")` to prevent legacy
> sources from bypassing the Supervisor's arbitration.

---

## 4. `RuleRepository` 所有权 (Repository Ownership)

**核心事实**:
- `RuleRepository` **没有** `close()` / `aclose()` (被动容器, P1 #2 实锤)
- Repository 由用户在 `SentinelEngine` 启动**前**显式创建
- `SentinelEngine.aclose()` **不**关闭 Repository
- 真正有 lifecycle 的是 `Supervisor` + 各 `Source`; `SentinelEngine.aclose()` 必须
  **等** Supervisor 关闭所有 Source 任务后再返回

**用户责任**:
- 创建 Repository (assemble_sources 之前, 或 install_legacy_source 之前)
- 决定是否在进程退出前主动 dispose (绝大多数场景**不**主动 dispose, 让它随进程
  退出自然释放)
- 把 Repository 注入两个入口 (`assemble_sources(..., repository=repo)` /
  `install_legacy_source(source, *, repository=repo)`), **不**传 `None` (default-deny)

> English: `RuleRepository` is a passive container with no `close()` /
> `aclose()`. The user creates it before Engine startup and decides
> whether to dispose it before process exit. `SentinelEngine.aclose()`
> waits for the Supervisor to close all Source tasks but does **not**
> close the Repository.

---

## 5. 已知不可自动迁移的场景 (Known Non-Automatable Scenarios)

| 场景 | 原因 | 解决路径 |
| ---- | ---- | -------- |
| 1.0 多源 wrapper 内部依赖"最后回调获胜"语义 | Supervisor 用 priority + 显式 failover 取代隐式回调顺序 | 显式声明 priority 与 failover_after; 走 `assemble_sources()` |
| 1.0 extension 把 `start(repository)` 的副作用 (e.g. timeout) 写进业务决策 | 1.0 行为锁定, 包装会改变 | 保留 `install_legacy_source()` 1.0 路径, 不升级 |
| 1.0 用户用全局单例 / 模块级 Source | Supervisor 需要 per-Engine 绑定 | 把单例改造为显式传入 `assemble_sources()` |
| 1.0 extension 暴露了 Nacos SDK 类型给业务 | 1.0 边界本就禁止, M6.1+ 仍禁止 | 升级为 `SnapshotRuleSource`, SDK 类型在边界翻译为本地值对象 |
| 1.0 用户自己写了"手动 failover"轮询 | Supervisor 自动 failover, 重复逻辑需去除 | 升级到 `assemble_sources()`, 移除手写轮询 |

---

## 6. 1.x 阶段不可做的事 (Hard "DON'T" List)

1. **DON'T** 把 1.0 旧 `RuleSource` 实现包装成 `SnapshotRuleSource` (shim)
   - 原因: 旧 `start(repository)` 没有 Engine / Supervisor 引用, 没法挂载
     "经 Supervisor 仲裁"路径; shim 包装必然改变 1.0 行为
   - 替代: 保留 `LegacyRuleSource` 路径, 走 `install_legacy_source()`
2. **DON'T** 把 `repository=None` / `Optional[RuleRepository]` 当可选参数
   - 原因: 所有权不明, default-deny 拒绝
   - 替代: 强制传入 `repository=...` (必填)
3. **DON'T** 把 `Supervisor` / `_RuleSourceBinding` / `RuleSourceActivation` /
   `_RuleSourceActivationBus` 放进公开 `__all__`
   - 原因: C 层私有, extension 不可 import
4. **DON'T** 在 M6.1 阶段冻结跨语言 `event_kind` 字符串 / wire schema / 时间戳 /
   `event_name`
   - 原因: M6.5.7 envelope 任务统一冻结, 父协议 (M6.5.1) 不可独立冻结
5. **DON'T** 把"用户负责关闭 Repository" 当作承诺
   - 原因: Repository 无 `close/aclose`, 是不存在的生命周期
   - 替代: 真实关闭责任是 Supervisor + 各 Source, `SentinelEngine.aclose()` 等它们

---

## 7. 验证清单 (Validation Checklist)

升级完成后, 用户应自检:

- [ ] 1.0 单源用户: `python -c "from atlas_richie.sentinel.source.rule_source import RuleSource, LegacyRuleSource; assert RuleSource is LegacyRuleSource"` 通过
- [ ] 1.0 单源用户: 现有代码 `source.start(repository)` 不报错, 规则正常加载
- [ ] 1.0 多源用户: 升级后 `engine.assemble_sources([...], repository=repo)` 正常返回,
  `repository.latest_version` 在多次调后递增
- [ ] extension 作者: 公开 API 中**不**导入 `atlas_richie.sentinel.source._supervisor.*`
  (M6.1.0d-3 阶段补 ruff `no-private-import`; M6.1.0d-1 阶段由 contract test
  兜底: 启动 extension 时 import 反射测试)
- [ ] 互斥约束: `engine.assemble_sources(...)` 之后 `engine.install_legacy_source(...)`
  抛 `SentinelConfigurationError("multimode_conflict")`, 反之亦然
- [ ] 弃用警告: 1.x 阶段**不**出现 `DeprecationWarning` (1.0 公共符号保留无警告)

---

## 8. 退出条件 (Exit Criteria)

MIGRATION-M6.md 完成 (M6.1.0c) 的退出条件:

- [ ] §1.A 单源用户零代码改动有可执行示例 + 行为保证声明
- [ ] §1.B 多源用户升级路径有可执行示例 + 错误原因说明
- [ ] §1.C extension 作者新 / 旧路径分叉明确 + shim 禁令
- [ ] §2 公开符号变化与 API delta v3 §3 一致
- [ ] §3 互斥约束 `multimode_conflict` 有反例代码
- [ ] §4 Repository 所有权描述与 DESIGN §10.3 一致
- [ ] §5 不可自动迁移场景覆盖已知 5 类
- [ ] §6 不可做事清单覆盖 C/B 治理 + default-deny + envelope 推迟 5 类硬约束
- [ ] §7 验证清单 6 项可执行 (用户可在本地复现)

---

## 9. 关联文档 (Cross-references)

- `R-SENTINEL-M6.1.0b-api-delta.md` v3 (决策 1-5, 5 owner 签字)
- `docs/rule_source_activation.md` v3 (C 层 `RuleSourceActivation` fact + observer 异常隔离)
- `docs/process/PLANNING.md` §M6.1.0a (双 Port + 互斥) / §M6.5.7 (envelope 冻结)
- `docs/DESIGN.md` §10.3 L1040-1089 (Supervisor 设计) / §13.3.1 (Agent Reporting 边界)
- `docs/EXTENSION_GUIDE.md` (新 extension 写 `SnapshotRuleSource` 指引, 待更新)
- `docs/CHANGELOG.md` 1.0+ 段 (待 M6.1.0d-3 补充)

---

**M6.1.0c 产物 — 与 `R-SENTINEL-M6.1.0b-api-delta.md` v3 同步签字后冻结, 任何 §1/§2/§3/§6 与 API delta 不一致都视为文档 bug, 必须先回到 API delta 修复再回到 MIGRATION。**
