# RULE_SOURCE_ACTIVATION (Internal Fact)

| Field | Value |
| ----- | ----- |
| Document Name | `RULE_SOURCE_ACTIVATION` |
| Status | **APPROVED v3 — B/C 设计签字完成；实现与静态验证仍按 M6.1.0d 执行** |
| Date | 2026-09-13 |
| Author | Mavis |
| Pre-req | `R-SENTINEL-M6.1.0b-api-delta.md` 决策 4 签字 |

> 中文
> ----
> 本文档**不是**跨语言 wire protocol。它是 M6.1 主包内部 Supervisor
> 暴露的 **activation fact** 的 C 层事件 schema, 供 C 层 / 内部
> 单元测试 / 同进程 reporter hook 消费。
>
> **不**是协议:本 fact 的跨语言投影由 M6.5.1 父协议 transport 承载,
> envelope schema / 时间字段 / `event_kind` 枚举 / V1 不可破坏性规则
> 由 **M6.5.7** 冻结。本文档**不**冻结任何跨语言兼容性承诺, 也
> **不**为 `event_kind` 字符串常量背书。
>
> 任何把本文档当作协议使用的 extension / 跨语言报告方, 都在 M6.1
> 范围外, 应当等待 M6.5.7 envelope 冻结。
>
> English
> --------
> This document is **not** a cross-language wire protocol. It is the
> **C-layer event schema** of the internal activation fact that the
> M6.1 main package's Supervisor emits, intended for C-layer / internal
> unit tests / same-process reporter hooks.
>
> **Not a protocol**: the cross-language projection of this fact is
> carried by the M6.5.1 父协议 transport; the envelope schema, the
> time fields, the `event_kind` enum, and the V1 immutability rules are
> frozen by **M6.5.7**. This document **does not** freeze any
> cross-language compatibility commitment and **does not** endorse any
> `event_kind` string constant.
>
> Any extension / cross-language reporter that treats this document as
> a protocol is out of scope for M6.1 and should wait for the M6.5.7
> envelope freeze.

---

## 1. 范围 (Scope)

### 1.1 IN (M6.1 范围)

- 主包 `source._supervisor.RuleSourceSupervisor` 内部 emit 的
  activation fact 的 frozen dataclass shape
- 触发条件(decision: 仅在 active Source 实际变更时)
- 同进程 observer 的 hook 形态(C 层 `subscribe(callback)`)
- 与 M3.1 `RuleRepository.apply_snapshot` 的关系: fact **仅在**
  Repository 成功 apply + active Source 实际变更时 emit

### 1.2 OUT (不在 M6.1 范围, 推迟到 M6.5.7 envelope)

- 跨语言 wire projection (string `event_kind` / 序列化格式 / per-kind
  payload schema)
- 跨进程 transport (gRPC / HTTP / 自定义协议) — 由 M6.5.1 父协议
  承载
- `event_kind` 字符串常量(必须等 envelope 冻结)
- 时间字段(M6.5.7 envelope 提供 `captured_at` + `received_at`,
  本 fact 不重复; 不存在单一 `capture_time`)
- 与 Agent Reporting batch 的嵌入 / sequence 关联
- V1 不可破坏性规则与 V2+ 演进策略

### 1.3 同步状态(decision 4 移除前的承诺)

> 在 M6.1 阶段**禁止**任何外部 / extension 消费者订阅本 fact。
> M6.1 阶段 `subscribe_activations` hook 仅为:
> - C 层单元测试用
> - 内部 metrics 计数用
> - 未来 M6.5 Reporter 的客户端接入点(只接同进程)
>
> 跨进程 / 跨语言 / extension 订阅 = M6.5.7 envelope 冻结后的事。

---

## 2. 触发条件 (When the fact is emitted)

**decision 4 修正后**: 严格 3 条件 AND, 缺一不 emit:

1. `RuleRepository.apply_snapshot(snap)` 返回 `True` (业务校验通过,
   atomic replace 成功)
2. active Source **实际**变更(new active source_id != old active source_id)
3. 业务语义属于真实切换 (not "all_stale" / not "no-op manual_replace")

**不 emit** 的场景:

- 同一 active Source 的 checksum 刷新(同 source, 新 version)
  → 这是 health event, 走 M6.5.7 envelope Reporter health event, 不走 activation fact
- 所有 ready Source 都 stale, 切换被拒绝, 维持 last-known-good
  → 这是 health event, 走 M6.5.7 envelope Reporter health event
- `assemble_sources()` 再次调用, 但所有 binding 解析后 active Source 不变
  → 静默 no-op, 不发任何事件
- Repository 拒绝 candidate (apply_snapshot 返回 False) → 静默 no-op

---

## 3. C 层事件 schema (Internal Fact Shape)

> **不**是 wire format, 是 Python C 层 frozen dataclass。extension
> **不**能 import 这个类; 任何 Python 外的消费者等 **M6.5.7** envelope
> 冻结后, 经 M6.5.1 父协议 transport 投到 wire。

### 3.1 数据类

```python
# 位置: atlas_richie/sentinel/source/_supervisor/activation.py
# __module__ 内部 + 不进 __all__; extension 不允许 import

from dataclasses import dataclass
from typing import Literal
from ...rules.snapshot import RuleVersion

@dataclass(frozen=True, slots=True)
class RuleSourceActivation:
    """Internal fact emitted by Supervisor on real active-source change.

    M6.1 scope: same-process C layer only.
    M6.5.7 envelope will project this to a cross-language event
    (carried by M6.5.1 父协议 transport).
    """
    previous_source_id: str | None   # None = first activation
    source_id: str                    # new active
    version: RuleVersion              # newly-applied snapshot version
    reason: Literal["initial", "failover", "manual_replace"]
    # NOTE: NO timestamp. M6.5.7 envelope provides
    # captured_at (Reporter 本地 UTC) + received_at (Collector 服务端
    # 权威). Wall-clock and monotonic clock are both unsafe
    # for cross-process interpretation; defer to envelope.
```

### 3.2 `reason` 字段枚举 (固定, 不扩展)

| 值 | 触发场景 |
| -- | -------- |
| `"initial"` | Engine 启动后, 第一个 ready Source 激活 |
| `"failover"` | active Source 变 stale 后, 切到优先级次高的 ready Source |
| `"manual_replace"` | `assemble_sources()` 再次调用, 显式替换 bindings, **且** active Source 实际变更 |

**移除**(decision 4 修正):
- ~~`"all_stale"`~~: 改为 M6.5.7 envelope Reporter health event, 不进 activation
- ~~`"upgrade"` / `"downgrade"`~~: 1.x 全程不存在
- 未来 1.x 阶段扩展 `reason` 必须先有 ADR + M6.5.7 envelope 同步

### 3.3 `version` 字段

- 引用 M0 锁的 `RuleVersion` 公共 dataclass
- wire 类型 / schema 在 M6.5.7 envelope 里**重新**冻结, 与 `RuleSnapshot`
  的 `version` 字段保持一致; M6.5.1 父协议 transport 承载
- 本 fact 内部不重新声明 wire schema

---

## 4. 订阅 hook (C 层 / 同进程)

```python
# 位置: atlas_richie/sentinel/source/_supervisor/observer.py
# C 层私有, 不进 __all__

from typing import Callable
from .activation import RuleSourceActivation

# C 层 observer; 同进程 only; M6.1 不导出给 extension
ActivationObserver = Callable[[RuleSourceActivation], None]

class _RuleSourceActivationBus:
    """C-layer internal pub-sub; no thread/process boundary.

    **异常隔离** (P1 #2): 单个 observer 抛任何异常**不能**影响
    (1) 其它 observer 的调用
    (2) ``publish()`` 调用栈本身 (包括 Supervisor 的"Repository 成功
    apply + active Source 实际变更"主链路)
    失败必须:
    - 被记录 (warn log, 不含 payload 内容)
    - 隔离到失败 observer 自身
    - 下一 publish 仍正常分发

    故意**不**传播异常到 ``publish()`` 调用方, 因为:
    (1) ``publish()`` 在 Supervisor 的 hot path (rule 切换主链路),
    一旦失败就破坏规则应用;
    (2) 多 observer 模式下, 一个内部订阅者不能拖累外部订阅者。
    """
    def subscribe(self, observer: ActivationObserver) -> None: ...
    def unsubscribe(self, observer: ActivationObserver) -> None: ...
    def publish(self, fact: RuleSourceActivation) -> None: ...
```

**extension 接入路径**:
- M6.1: **无** (extension 不能订阅本 fact, 也不应)
- M6.5.7 envelope 冻结后, 跨进程 / 跨语言 subscription 由 Agent Reporting
  通道提供; 本 fact 在 Reporter 内部 convert 为 envelope 事件,
  经 M6.5.1 父协议 transport 投到 wire

---

## 5. 与 M3.1 `RuleRepository` 的关系

### 5.1 Repository 的事实流

```
Source.snapshots()  →  [candidate snapshot]
       ↓
Supervisor._validate_and_apply()  →  RuleRepository.apply_snapshot()
       ↓
[True]  →  RuleSourceActivation.emit()  →  C-layer bus.publish()
[False] →  静默丢弃, last-known-good 保留
```

### 5.2 Repository 是被动容器

- `RuleRepository` 无 `close()` / `aclose()` 方法 (P1 #2 实锤)
- Repository 的 lifetime 由调用方决定(用户创建, 用户持有)
- Supervisor **不**创建 Repository, **不**关闭 Repository, **不**继承
  Repository 引用(仅调用 `apply_snapshot`)
- 真正的"被关闭的资源"是 Supervisor 和各 Source; 这两个由
  `SentinelEngine.aclose()` 负责(等 Supervisor 关闭后再返回)

---

## 6. 与 M6.5 Agent Reporting 的关系 (deferred)

- 本 fact 是 M6.5.7 envelope 的**内部 Python shape** (经 M6.5.1 父协议
  transport 投到 wire), **不**是 wire format
- M6.5.7 envelope 冻结时, 会冻结:
  - 跨语言 wire schema (字段名 / 类型 / 必填 / 演进策略)
  - `event_kind` 字符串常量 (M6.1 阶段**不**冻结任何字符串)
  - 两个时间字段 (`captured_at` + `received_at`, 二者分离, 无单一
    `capture_time`; 本 fact 不重复)
  - 与 instance_id / startup_epoch / sequence 的关联
  - `event_payload` 必须是 per-kind frozen dataclass
  - V1 不可破坏性规则 (修复或加 optional field 走同 major + 兼容性矩阵;
    V2+ 独立 ADR)
- M6.5.7 envelope 冻结前, 跨进程 / 跨语言 / extension 订阅本 fact
  **不存在**

---

## 7. 安全 / 脱敏 (Security / Scrubbing)

本 fact **严禁**包含:

- 任何规则正文 (走 §10.5 `RuleSnapshot` 单独通道)
- 任何凭证 / endpoint / SDK client 对象
- 任何用户身份 / 业务请求内容
- 任何**时间戳** (M6.5.7 envelope 提供 `captured_at` + `received_at`)
- 任何健康状态 / 失败原因 (走 M6.5.7 envelope Reporter health event)

`previous_source_id` / `source_id` 必须是**配置时**用户提供的 stable
字符串 (e.g. `"nacos-prod"`), **不**包含敏感字段; **不**自动用
endpoint URL / path / token 构造 source_id。

---

## 8. 退出条件 (Exit Criteria)

- [x] §2 触发条件经 B 审查签字 (3 条件 AND)
- [x] §3.1 `RuleSourceActivation` dataclass shape 经 C 实现 owner 签字
- [x] §3.2 `reason` 枚举值固定 (3 个, 不扩展)
- [ ] §4 observer hook C 层 private (extension 不可 import) 静态验证
- [ ] §5.2 Repository 被动容器语义在 PLANNING + MIGRATION 同步
- [x] §6 M6.5.7 envelope 推迟项明确列入 M6.5.7 backlog, 不在 M6.1 范围

---

## 9. 关联文档 (Cross-references)

- `docs/R-SENTINEL-M6.1.0b-api-delta.md` (decision 4 / decision 5)
- `docs/DESIGN.md` §10.3 L1040-1069 (Supervisor 设计)
- `docs/DESIGN.md` §13.3 (Agent Reporting Protocol — 父协议占位)
- `docs/PLANNING.md` §M6.5.1 (父协议) / §M6.5.7 (envelope 与子协议挂载点)

---

**APPROVED v3 — B/C 设计签字完成。** 未勾选的静态验证与 M6.1.0c 的迁移文档同步仍是实现前置条件。M6.5.7 envelope 冻结前，任何把本文档
当作协议使用 / 引用 `event_kind` 字符串 / 跨进程订阅 / 跨语言 wire schema
的实现都被禁止。M6.5.1 父协议是 transport 承载, 不替代 envelope 冻结。
