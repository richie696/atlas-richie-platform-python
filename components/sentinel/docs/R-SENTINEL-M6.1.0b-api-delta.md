# R-SENTINEL-M6.1.0b API Delta

| Field | Value |
| ----- | ----- |
| Author | Mavis |
| Status | **APPROVED v3 — 设计签字完成；实现与验证仍按 M6.1.0c / M6.1.0d 执行** |
| Date | 2026-09-13 |
| Pre-req | C/B 治理模型已固化 (DESIGN §10.3 L1040-1066 / PLANNING §M6.1.0) |
| Sign-off Required | 用户 (maintainer) + B 契约审查 owner + C 实现 owner + 测试 owner + 文档 owner (5 个全勾才可进 M6.1.0c) |

> 中文
> ----
> **v3 重大变更** (相对 v1 草稿):
> 1. P0 修复:拆为 `LegacyRuleSource` (1.0 旧契约) + `SnapshotRuleSource`
>    (新契约) 两个独立 Port; `assemble_sources` 仅接受新 Port;
>    `LegacyRuleSource` 路径**不**经 Supervisor、不 shim 包装, 1.0 行为不变;
>    两入口互斥, 违反抛 `SentinelConfigurationError("multimode_conflict")`。
> 2. P0 修复:`RULE_SOURCE_CHANGED` 协议常量 + 跨语言投影从 M6.1 范围
>    移除, 推迟到 **M6.5.7** (Agent Reporting 事件 envelope 冻结任务,
>    非 M6.5.1); M6.1 只冻结**内部 activation fact** (`RuleSourceActivation`
>    C 层 frozen dataclass), 详见 `docs/rule_source_activation.md`。
> 3. P0 修复:不再冻结任何时间戳 / 跨语言 wire 字段; 时间由 M6.5.7
>    拆为 `captured_at` (Reporter 本地 UTC, 诊断) + `received_at`
>    (Collector 服务端权威聚合时间) 冻结。
> 4. P0 修复:权威文档(DESIGN / PLANNING / API delta / activation spec)
>    全部统一到 v3 事实源, 不再引用已替代的 `RULE_SOURCE_CHANGED` 字符串
>    或旧 `_RuleSourceActivatedEvent` 事件类。
> 5. P1 修复:`Repository` 是被动容器, 无 `close/aclose`, 关闭责任
>    明确归属 Supervisor + Source (不是 Repository); 用户"负责关闭
>    Repository"承诺是不存在的生命周期, 删去。
> 6. P1 修复:`reason` 枚举从 4 个缩为 3 个 (`all_stale` 移 M6.5.7
>    health event, 不进 activation); `manual_replace` 仅在实际变更时
>    emit, 否则静默; observer 异常必须隔离, 不影响主链路。
> 7. P1 修复:`default-deny` 原则从"任何 optional 参数"收窄为
>    "影响所有权 / 权限 / 故障策略 / 资源上限 / 跨进程语义"。
> 8. P1 修复:弃用时钟唯一公式 — "首发后至少 2 个 minor 或 6 个月,
>    以较晚者为准"; 删除所有 v1/v2 草稿里的"6 个 minor"等冲突表述。
>
> English
> --------
> **v3 major changes** (relative to v2 draft):
> 1. P0 fix: split into `LegacyRuleSource` (1.0 old contract) +
>    `SnapshotRuleSource` (new contract) as two independent Ports;
>    `assemble_sources` only accepts the new Port; `LegacyRuleSource`
>    path **does not** pass through Supervisor, is **not** shim-wrapped,
>    and 1.0 behavior is preserved unchanged. The two entry points are
>    mutually exclusive; violation raises
>    `SentinelConfigurationError("multimode_conflict")`.
> 2. P0 fix: `RULE_SOURCE_CHANGED` protocol constant + cross-language
>    projection are removed from M6.1 scope and deferred to **M6.5.7**
>    (Agent Reporting event envelope freezing task, not M6.5.1);
>    M6.1 only freezes the **internal activation fact**
>    (`RuleSourceActivation` C-layer frozen dataclass), see
>    `docs/rule_source_activation.md`.
> 3. P0 fix: no timestamp / cross-language wire field is frozen in M6.1;
>    the two time fields are separated in M6.5.7 into `captured_at`
>    (Reporter-local UTC, diagnostic only) + `received_at` (Collector
>    server-authoritative aggregation time).
> 4. P0 fix: authoritative documents (DESIGN / PLANNING / API delta /
>    activation spec) are unified to the v3 source of truth; no more
>    references to the replaced `RULE_SOURCE_CHANGED` string or the
>    legacy `_RuleSourceActivatedEvent` class.
> 5. P1 fix: `Repository` is a passive container with no `close/aclose`;
>    close responsibility is explicitly Supervisor + Source (not
>    Repository); the "user closes Repository" promise was a
>    non-existent lifecycle, removed.
> 6. P1 fix: `reason` enum shrinks from 4 to 3 (`all_stale` moved to
>    M6.5.7 health event, not into activation); `manual_replace` only
>    emits on actual change, otherwise silent; observer exceptions
>    must be isolated and must not affect the main chain.
> 7. P1 fix: `default-deny` scope narrows from "any optional param" to
>    "affects ownership / permission / failure policy / resource cap /
>    cross-process semantics".
> 8. P1 fix: deprecation clock is **unified** to "≥2 minor versions OR
>    6 months after first public release, whichever is later"; all
>    conflicting "6 minor versions" wording in v1/v2 drafts is deleted.

---

## 0. 总览 (Summary)

**v2 → v3 修正**: 删除"1 公开方法" / "1 内部 Port"等含糊计数, 改为精确分类。

| 类型 | 数量 | 状态 |
| ---- | ---- | ---- |
| **新增 (Add) — 公开方法** | 2 | `SentinelEngine.assemble_sources` + `SentinelEngine.install_legacy_source` |
| **新增 (Add) — 公开 Port** | 1 | `SnapshotRuleSource` (新契约) |
| **新增 (Add) — 公开兼容性 Port** | 1 | `LegacyRuleSource` (1.0 旧契约, 显式导出) |
| **新增 (Add) — 公开 DTO** | 1 | `RuleSourceAssembly` (immutable) |
| **修改 (Change) — 公开 alias** | 1 | `RuleSource` (1.0) → alias 到 `LegacyRuleSource` |
| **修改 (Change) — 公开实现** | 1 | `FileRuleSource` 实现改为 `LegacyRuleSource` (行为不变) |
| **废弃 (Deprecate)** | 0 (1.x 阶段不 deprecate 任何 1.0 公共符号) |
| **删除 (Remove)** | 0 (1.x 全程保留 1.0 公共符号) |
| **推迟 (Defer)** | `event_name` 字符串 + 跨语言 wire schema | **M6.5.7** (Agent Reporting 事件 envelope, 非 M6.5.1) |

**总公开面新增: 6 项** (2 方法 + 2 Port + 1 DTO + 1 alias)。

**M6.1.0d-1 实施扩展 (本 delta 之外, 后续 ADR 需正式批准)**:
worker 实施 M6.1.0d-1 时根据 `rule_source_activation.md` §7 添加了 1 个
Protocol 字段, API delta v3 未明确列出, 需在 d-3 后**追加**本段:

- **`SnapshotRuleSource.source_id: str`** (非空稳定字符串, 配置时
  extension 显式声明, e.g. `"nacos-prod"`)
  - **理由 1**: `RuleSourceActivation` fact 的 `previous_source_id` /
    `source_id` 字段需要稳定 source_id 标识; 不可由 endpoint / path /
    token 自动构造 (避免 operator observability 失真)
  - **理由 2**: Supervisor 内部把 `source_id` 转写到
    `_RuleSourceBinding.source_id`, 保持 1.x 跨 extension 一致语义
  - **不允许** `""` / `None` / 自动生成 (e.g. `f"source-{i}"`); 若
    extension 真的需要匿名, 用 `source_id = "anonymous-{uuid4().hex[:8]}"` 显式声明
  - **未来 ADR**: 1.0 时期无 source_id 概念 (1.0 `RuleSource` 不带此字段),
    1.x 阶段冻结后**不**允许扩展自动生成 source_id 的便利 API (default-deny 收窄)

C 层实现 (`source._supervisor.RuleSourceSupervisor` /
`source._supervisor._RuleSourceBinding` /
`source._supervisor.activation.RuleSourceActivation` (frozen dataclass) /
`source._supervisor.observer._RuleSourceActivationBus` (内部 bus))
**不**在本 delta 范围, **不**进 `__all__`, **不**允许 extension import。

`LegacyRuleSource` 是**公开兼容性 Port** (不是"内部 Port"): 1.0 用户
需要继续 `isinstance(src, RuleSource)` 走单源兼容路径, 公开导出是必要
的。命名上 `Legacy*` 表达"旧契约", 不表达"私有"。

---

## 1. P0 修复点(2026-09-13 review 触发)

### 1.1 P0-#1: 旧 `RuleSource` 无法内部 shim 到新协议

**问题**:
- 当前 `RuleSource` Protocol 是 `start/stop/latest` (M3.2 实现, 见
  `source/rule_source.py` L72-79)
- FileRuleSource.start(repository) 直接 `repository.apply_snapshot(snap)`,
  自身没有 Engine / Supervisor 引用
- 结构化检查会不满足新 `snapshots/aclose` 协议; 旧 `start` 写 Repository
  的副作用无法被"内部包装"成新协议(因为没地方挂 Supervisor)

**修复**:
- 拆为两个独立 Port:
  - `LegacyRuleSource` Protocol (`start/stop/latest`, 1.0 形态) — 旧
  - `SnapshotRuleSource` Protocol (`snapshots/aclose`) — 新
- `SentinelEngine.assemble_sources()` 只接受 `SnapshotRuleSource` 实例
- `SentinelEngine` 提供独立入口 `install_legacy_source(LegacyRuleSource)`
  (B 审查通过) 接受旧 Port, 内部走**直接** `RuleRepository.apply_snapshot`
  (等同 1.0 行为), **不**经 Supervisor, **不**支持多源仲裁
- 旧单源用户**不升级**代码也能用, 但**不**获得多源 / failover 能力
- `FileRuleSource` 改造为 `LegacyRuleSource` 实现(签名不变, 1.0 用户零代码改动)

**为什么不是 shim**: 1.0 Source 实现 `start` 时**直接**调
`repository.apply_snapshot`, 没有 Engine / Supervisor 引用, 没法挂载新协议
的"经 Supervisor 仲裁"路径。改成 shim 必然让 1.0 用户付出"被包装行为变化"
的风险(例如 timeout / exception path), 违反 1.0 锁定承诺。

### 1.2 P0-#2: `RULE_SOURCE_CHANGED` 协议冻结时机不对

**问题**:
- 我之前的 v1 把 `RULE_SOURCE_CHANGED` 当作 Agent Reporting 的子协议
- 但 Agent Reporting 父协议 (M6.5.1) 与事件 envelope 任务 (M6.5.7)
  当时都未冻结
- v1 引用了 `subscribe_rule_source_changes` hook + `event_name` 字符串,
  全部依赖未冻结的父协议

**修复**:
- M6.1 范围**只**冻结**内部 Python activation fact** (`RuleSourceActivation`
  frozen dataclass), C 层私有, 不进 `__all__`
- 跨语言 wire projection / 字符串 `event_name` / 跨进程 transport /
  envelope 全部**推迟到 M6.5.7** (Agent Reporting 事件 envelope 冻结任务)
- 新文件: `docs/rule_source_activation.md` (替代 `docs/protocols/RULE_SOURCE_PROTOCOL.md`)
- §10.3 同步移除 `RULE_SOURCE_CHANGED` 协议常量声明

### 1.3 P0-#3: 时间与版本字段不是跨语言安全

**问题**:
- `time.time_ns()` 是 wall clock, 跨进程 / 跨语言不可比
- monotonic clock 也不跨进程可比
- `RuleVersion` 是 Python 类型, `epoch: int` 没与 source-owned epoch 语义对齐

**修复**:
- M6.1 阶段**不**在任何 activation fact 字段中包含时间戳
- 时间由 M6.5.7 envelope 拆为两个字段冻结: `captured_at` (Reporter 本地
  UTC, 仅诊断) + `received_at` (Collector 服务端权威, RFC 3339); 二者
  分开, 无单一 `capture_time`
- `RuleVersion` 在 M6.1 阶段**仅**以 Python 引用方式出现在 fact 中
  (M6.5.7 envelope 冻结时再定 wire schema)
- `epoch` wire 类型在 M6.5.7 envelope 与 `RuleSnapshot.version` 字段同步冻结

---

## 2. 决策表 (Decisions)

### 决策 1 — 私有 vs 公开 API 二元边界

**结论**:
- 公开面: `SentinelEngine.assemble_sources` 方法 + `RuleSourceAssembly` DTO
  + `SnapshotRuleSource` Port + `LegacyRuleSource` Port (兼容)
- 私有面: `source._supervisor.RuleSourceSupervisor` /
  `source._supervisor._RuleSourceBinding` /
  `source._supervisor.activation.RuleSourceActivation` (frozen dataclass) /
  `source._supervisor.observer._RuleSourceActivationBus` (内部 bus)
- extension 只能 `import` 公开符号 (ruff `no-private-import` + CI 验证)

### 决策 2 — Repository 是被动容器, 无生命周期

**结论**:
- `RuleRepository` **没有** `close()` / `aclose()` (P1 #2 实锤)
- Repository 由用户在 Engine 启动**前**显式创建
- Engine 在 `__aenter__` 期间持有 Repository 引用, **不**创建新 Repository
- `SentinelEngine.aclose()` **不**关闭 Repository; 用户自己决定是否保留
  (绝大多数场景下不主动关闭, 让它随进程退出自然释放)
- 真正有 lifecycle 的是 Supervisor + 各 Source; `SentinelEngine.aclose()`
  必须**等** Supervisor 关闭所有 Source 任务后再返回 (用户决定)

**理由**: 决策 1 锁定"用户负责关闭 Repository" 是不存在的承诺; 真实
责任是 Supervisor 关闭 Source task, 且 `aclose()` 必须等待。

### 决策 3 — 两个独立 Port (不 shim, 不改名)

**结论**:
- 新 Port: `SnapshotRuleSource` Protocol
  - `def snapshots(self) -> AsyncIterator[RuleSnapshot]`
  - `async def aclose(self) -> None`
- 旧 Port: `LegacyRuleSource` Protocol (1.0 `RuleSource` 改名, 不删)
  - `def start(self, repository: RuleRepository) -> None`
  - `def stop(self) -> None`
  - `def latest(self) -> RuleSnapshot | None`
- 1.0 公共符号 `RuleSource` 保留为 `LegacyRuleSource` 的 alias, 首发
  后至少 2 个 minor 版本或 6 个月 (以较晚者为准) 考虑 deprecate 警告
- `assemble_sources()` 只接受 `SnapshotRuleSource`
- `SentinelEngine` 另提供 `install_legacy_source(LegacyRuleSource, *,
  repository: RuleRepository)` 接受旧 Port, **不**经 Supervisor, 等同
  1.0 行为

**理由** (同 §1.1 P0 #1): shim 路径会改变 1.0 行为, 违反 1.0 锁定。

**Deprecation 触发时机** (v3 唯一公式): "首发后至少 2 个 minor 版本或
6 个月, **以较晚者为准**"。本 v3 文档不再保留任何其它弃用时钟表述。

### 决策 4 — 内部 activation fact 替代协议常量 (M6.1 范围收窄)

**结论**:
- 内部 fact: `RuleSourceActivation(previous_source_id, source_id,
  version, reason)` frozen dataclass
  - `version` 引用 Python `RuleVersion` (M0 公共)
  - `reason: Literal["initial", "failover", "manual_replace"]` (3 个, 固定)
  - **不**含时间戳 (M6.5.7 envelope 提供)
- 内部 observer: `subscribe_activations(observer)` 接受 Python
  `RuleSourceActivation` 回调 (C 层私有, extension 不允许订阅)
- **不**冻结任何跨语言 wire schema
- **不**冻结任何 `event_name` 字符串常量
- 跨进程 / 跨语言 / extension 订阅 = M6.5.7 事件 envelope 范围, **不在 M6.1**

详见 `docs/rule_source_activation.md` 完整 spec。

### 决策 5 — default-deny 原则 (范围收窄)

**结论** (v2 收窄):
- 任何"为用户方便"的新增 **optional 参数** 必须由 ADR 显式签字
  **当且仅当**它影响以下任一项:
  - 资源所有权 (谁创建 / 注入 / 关闭)
  - 权限 / 安全边界
  - 故障策略 (fail-closed / fail-open / local-fallback)
  - 资源上限 (并发 / 内存 / 配额)
  - 跨进程语义 (token / report / clock authority)
- 普通明确语义的 optional 参数 (timeout / 分页 / retry 次数 / 日志级别)
  **不**需要逐项 ADR; 走常规 API review

**理由** (P1 #5 修正): v1 把"任何 optional 参数"全包太宽, 阻碍
细粒度 API 设计且不增加审查价值。锁定到 5 类高影响参数,
timeout / 分页等不强制走 ADR。

---

## 3. 公开符号变化清单 (Public Symbol Delta)

### 3.1 新增 (Add)

```python
# atlas_richie/sentinel/source/ports.py (NEW module)
class SnapshotRuleSource(Protocol):
    """新契约 Port; assemble_sources 仅接受此类型。"""
    def snapshots(self) -> AsyncIterator[RuleSnapshot]: ...
    async def aclose(self) -> None: ...

class LegacyRuleSource(Protocol):
    """1.0 形态; 1.x 全程保留, 走 install_legacy_source。"""
    def start(self, repository: RuleRepository) -> None: ...
    def stop(self) -> None: ...
    def latest(self) -> RuleSnapshot | None: ...

# atlas_richie/sentinel/source/assembly.py (NEW module)
@dataclass(frozen=True, slots=True)
class RuleSourceAssembly:
    """公开 immutable assembly DTO; 不是 binding。"""
    source: SnapshotRuleSource
    priority: int             # 全局唯一, 大值优先
    failover_after: timedelta  # 短抖动容错窗口
    def __post_init__(self) -> None:
        # 不触发生命周期调用; 重入校验是 contract test 职责
        if self.priority < 0: raise ValueError(...)
        if self.failover_after < timedelta(0): raise ValueError(...)

# atlas_richie/sentinel/engine/sentinel_engine.py
class SentinelEngine:
    async def assemble_sources(
        self,
        assemblies: Sequence[RuleSourceAssembly],
        *,
        repository: RuleRepository,
    ) -> None:
        """多源仲裁入口; 仅接受 SnapshotRuleSource。
        repository 必填; lifecycle gate; idempotent。

        **互斥约束**: 调用前 Engine 必须未持有任何 Legacy 1.0 Source
        (i.e. ``install_legacy_source`` 之后调此方法抛
        ``SentinelConfigurationError("multimode_conflict")``,
        反之亦然)。防止遗留 Source 绕过 Supervisor 改写多源仲裁结果。
        """
        ...

    def install_legacy_source(
        self,
        source: LegacyRuleSource,
        *,
        repository: RuleRepository,
    ) -> None:
        """1.0 兼容入口; 不经 Supervisor; 等同 1.0 行为;
        不支持多源仲裁和 failover。

        **互斥约束**: 调用前 Engine 必须未通过 ``assemble_sources``
        安装任何 SnapshotRuleSource, 反之亦然; 违反抛
        ``SentinelConfigurationError("multimode_conflict")``。
        """
        ...
```

### 3.2 修改 (Change)

```python
# atlas_richie/sentinel/source/rule_source.py
# 旧 RuleSource 改名为 LegacyRuleSource, 保留 alias 兼容 1.0 公共面
RuleSource = LegacyRuleSource  # type alias (1.0 兼容)

# __all__ 增加:
__all__ = [
    "RuleSource",          # alias, 不破坏 1.0 import
    "LegacyRuleSource",    # 新显式名
    "SnapshotRuleSource",  # 新 Port
    "FileRuleSource",      # 实现改 LegacyRuleSource
    "RuleSourceAssembly",  # 公开 DTO
]
```

### 3.3 废弃 (Deprecate)

| Symbol | 弃用版本 | 计划删除 |
| ------ | -------- | -------- |
| `RuleSource.start(stop/latest)` 形态 | 1.x 末 (≥ 2 minor 或 6 个月, 以较晚者为准) | **不得早于 2.0**, 且需未来 ADR (v3 已明确 1.x 全程保留旧符号) |

**不**删除: 1.x 全程保留 `RuleSource` (alias → `LegacyRuleSource`),
所有 1.0 公共面不变。

### 3.4 删除 (Remove)

无。1.x 全程保留所有 1.0 公共符号 (1.0 API 锁定承诺)。

---

## 4. C 层私有实现 (不在 B delta 范围)

C 层实现 (`source._supervisor.RuleSourceSupervisor` /
`source._supervisor._RuleSourceBinding` /
`source._supervisor.activation.RuleSourceActivation` (frozen dataclass) /
`source._supervisor.observer._RuleSourceActivationBus` (内部 bus))
**不**在本 delta 范围, **不**进 `__all__`, **不**经 B 审查。详见
`docs/rule_source_activation.md` C 层 shape 定义。

---

## 5. 测试 / 验收 / 迁移

### 5.1 必须新增的测试

- `tests/test_sen_snapshots_source.py` — `SnapshotRuleSource` 协议
  contract test (替换 `tests/test_sen_rule_source.py` 中 `latest+start` 部分)
- `tests/test_sen_legacy_source_compat.py` — `LegacyRuleSource` /
  `RuleSource` (alias) 兼容测试
- `tests/test_sen_assemble_sources.py` — `assemble_sources` 契约测试
  (priority 唯一 / lifecycle gate / idempotent / repository 必填 /
  activation fact emit 条件)
- `tests/test_sen_install_legacy_source.py` — 1.0 兼容入口测试
  (等同 1.0 行为 / 不经 Supervisor / 不发 activation fact)
- `tests/test_sen_rule_source_activation.py` — C 层 activation fact
  (3 条件 AND / reason 枚举固定 / 不含时间戳)

### 5.2 必须更新的测试

- `tests/test_sen_rule_source.py` — 现有 25 个测试**全部**走新 contract
  (latest → snapshots, start → aclose); 保留用例不删,改 fixture 即可
- `tests/test_sen_core.py` — 验证 `assemble_sources` 不破坏 Engine 6 状态机
- `tests/test_sen_retry_cb_compose.py` — 验证 Supervisor shim 走多源时
  不影响 Retry/CB 组合语义

### 5.3 必须更新的文档

- `docs/RULE_REFERENCE.md` — `RuleSource` 章节新增 `SnapshotRuleSource` /
  `LegacyRuleSource` / `RuleSourceAssembly` 描述; 旧 `RuleSource`
  标 alias, 首发后 2 个 minor 或 6 个月后 (以较晚者为准) 考虑 deprecate
- `docs/EXTENSION_GUIDE.md` — 扩展开发指南: 写新 `SnapshotRuleSource`
  vs 改旧 `LegacyRuleSource` 的判断路径
- `docs/QUICK_START.md` — 30 秒跑通更新为"新 `SnapshotRuleSource` 用法 +
  旧 `RuleSource` alias 仍可用"
- `CHANGELOG.md` — 1.0+ 段加"DEPRECATED (待定)" + 链接本 delta

### 5.4 必须的迁移文档

- `docs/MIGRATION-M6.md` (M6.1.0c 产物) — 三类用户迁移路径:
  1. 1.0 单源用户: 零代码改动, `RuleSource.start(repository)` 仍可用
  2. 1.0 多源用户 (罕见): 必须升级到 `SnapshotRuleSource` + `assemble_sources`
  3. extension 作者: 旧 `RuleSource` 实现保留; 新 `SnapshotRuleSource`
     才是 M6.1+ 推荐路径

---

## 6. 签字栏 (Sign-off)

- [x] 用户 (maintainer) — 1.x API 锁定承诺 + 默认行为
- [x] B 契约审查 owner — 公开面变化合规
- [x] C 实现 owner — 私有层不在公共路径
- [x] 测试 owner — 契约 / shim / 升级测试范围获批；执行留待 M6.1.0d
- [x] 文档 owner — MIGRATION + CHANGELOG + RULE_REFERENCE 同步计划获批；具体文档留待 M6.1.0c

以上为**设计签字**，不是实现或测试已完成的声明。五项均勾选后允许进入
M6.1.0c (写 MIGRATION-M6.md)；M6.1.0d 仍必须遵循既定实现、契约测试和退出条件。

---

## 7. 退出条件 (Exit Criteria)

- [x] 本文档 5 项决策全部签字
- [ ] `RuleSource` alias 行为等价验证 (1.0 公共面不破坏)
- [ ] `LegacyRuleSource` 与 `SnapshotRuleSource` 静态可区分
  (mypy runtime_checkable 检查)
- [ ] C 层符号 (decision 1) 物理隔离验证
  (ruff `no-private-import` + mypy private module 规则)
- [ ] `RuleSourceActivation` 3 条件 AND emit 验证
- [ ] `default-deny` 范围 (decision 5) 在 `CODE_QUALITY.md` 或
  `R-SENTINEL-API-REVIEW.md` 同步
- [ ] Repository 被动容器语义在 `PLANNING §M6.1.0` 与 MIGRATION 同步
- [ ] 跨语言 / 跨进程订阅 entry point 在 M6.1 阶段**确认无任何公开符号**
  (reviewer 用 grep 静态验证)

---

## 8. 已决策的未决项 (Decided Open Questions)

| 未决项 | 决策 (M6.1 v3) |
| ------ | -------------- |
| Delta / MIGRATION 顺序 | **delta 先**, M6.1.0c 在 delta 签字后开 |
| `SentinelEngine.aclose()` 时机 | **必须**等 Supervisor 关闭所有 Source 任务后再返回 |
| Activation fact emit 时机 | **3 条件 AND**: Repository 成功 apply + active Source 实际变更 + 业务语义属于真实切换 (不是 health / no-op) |
| `manual_replace` 但 active 未变 | **不发** activation fact, 静默 |
| 关闭时重复报警 | **不**; 单次 activation fact, 关闭时走 M6.5.7 Reporter health event |
| 弃用警告触发时机 | 在 P0 兼容模型 (`LegacyRuleSource` / `SnapshotRuleSource` 分离) 签字后**单独**决定; M6.1 阶段**不**发 deprecation warning (避免 1.0 用户 noise) |
| `event_name` 字符串常量 | M6.1 阶段**不**冻结; M6.5.7 事件 envelope 任务冻结 |
| 时间字段 (captured_at / received_at) | M6.1 fact **不**含; M6.5.7 envelope 冻结; 二者分离, 无单一 `capture_time` |
| `epoch` wire 类型 | M6.1 fact **不**冻结; M6.5.7 与 `RuleSnapshot.version` 同步 |

---

## 9. 关联文档 (Cross-references)

- `docs/rule_source_activation.md` (M6.1 内部 fact 完整 spec, 替代原 protocol 草稿)
- `docs/DESIGN.md` §10.3 L1040-1069 (Supervisor 设计)
- `docs/DESIGN.md` §13.3 (Agent Reporting Protocol 父协议占位)
- `docs/PLANNING.md` §M6.1.0 / M6.1.0a / M6.1.0b / M6.1.0c / M6.1.0d
- `docs/MIGRATION-M6.md` (M6.1.0c 待写)

---

**APPROVED v3 — 与 PLANNING §M6.1.0a / §M6.5.7 / DESIGN §10.3 / activation spec 同步，5 owner 设计签字完成。** 现在进入 M6.1.0c；C 层实现 (M6.1.0d-1) 仍须在迁移文档和实现前置条件完成后才开始。
