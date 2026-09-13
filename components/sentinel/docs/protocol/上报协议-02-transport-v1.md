# Atlas Richie 上报协议 (V1)

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0 (Draft)
> **Status**: Draft — not frozen
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **语言**: [中文 (本文件)](./上报协议-02-transport-v1.md) · [English](./reporting-protocol-02-transport-v1.md)

---

## 摘要 (Abstract)

本文档规定 **Atlas Richie 上报协议 V1** (wire identifier:
`atlas-richie.reporting/v1`), 将 Sentinel 运行期事件从 Reporter
传输到 Collector 的父协议。协议覆盖 transport (HTTP/1.1 + JSON),
鉴权 (共享密钥), 版本协商, 错误码, batch 格式, sequence 和去重键,
ack 语义, 旧 generation 行为, 以及 cardinality 限制。

线协议上的 envelope schema 在配套文档
[`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 中规定。配套文档是 schema
本身; 本文档是协议。

## 本备忘录状态 (Status of This Memo)

本文档是待签字的 transport 草案。在 freeze record 完成全部签字前，不得作为
已发布 Standards Track 合同实现。

## 版权声明 (Copyright Notice)

Copyright © 2026 Atlas Richie. 本文档根据 Apache License 2.0 分发。

## 目录 (Table of Contents)

1. [引言](#1-引言)
   1.1. [背景](#11-背景)
   1.2. [与配套文档的关系](#12-与配套文档的关系)
2. [数据边界](#2-数据边界)
3. [Transport](#3-transport)
4. [版本协商](#4-版本协商)
5. [鉴权](#5-鉴权)
6. [错误码](#6-错误码)
7. [Batch 格式](#7-batch-格式)
8. [Sequence 与去重](#8-sequence-与去重)
9. [Ack 语义](#9-ack-语义)
10. [旧 Generation 行为](#10-旧-generation-行为)
11. [背压与 Overflow 策略](#11-背压与-overflow-策略)
12. [Cardinality 与 Dropped 统计](#12-cardinality-与-dropped-统计)
13. [安全考虑](#13-安全考虑)
14. [IANA 考量](#14-iana-考量)
15. [兼容性矩阵](#15-兼容性矩阵)
16. [跨语言合同测试](#16-跨语言合同测试)
17. [未来工作](#17-未来工作)
[附录 A. 示例](#附录-a-示例)
[附录 B. 签字](#附录-b-签字)
[版本历史](#版本历史)
[作者地址](#作者地址)

---

## 1. 引言

### 1.1. 背景

Reporter 观察 Sentinel 运行期事件并发送给 Collector, 用于聚合、审计和
dashboard 展示。由于 Reporter 和 Collector 可能由不同语言实现, 跨进程
部署, 协议**必须**自描述, 与语言无关, 不依赖任何第三方依赖。

本文档规定的是包装内层 envelope schema 的协议。内层 schema 在
[`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 中规定。

### 1.2. 与配套文档的关系

| 文档 | 范围 |
| --- | --- |
| `上报协议-01-envelope-v1.md` (本协议族) | 内层 ingress envelope schema (7 字段, 6 个 event_kind)。 |
| `上报协议-02-transport-v1.md` (本文档) | 外层 transport, 鉴权, 版本, 错误码, batch。 |
| `上报协议-03-freeze-v1.md` (sign-off 记录) | family-level 5-owner 签字表。 |
| `集群令牌协议-v1.md` (兄弟协议) | Atlas Richie 集群令牌协议 (准入)。 |

## 2. 数据边界

协议**不得**携带以下内容:

- 业务请求或响应体。
- 用户标识符、鉴权材料、凭证或 token。
- 任意日志消息、stack trace 或 frame locals。
- 完整规则体。
- 原始异常消息 (仅允许 stable error class)。
- 私有 SDK 或第三方内部字段。

本 V1 事件族**可以**携带:

- 已定义的规则执行结果: `APPLIED` / `BLOCKED` / `FAILED`，以及受限的
  failure classification。
- Source 切换: active `source_id` 和 rule version (epoch, revision,
  checksum)。
- Reporter 丢弃计数（只计 sequence 分配前的队列、cardinality 或关闭策略丢弃）。
- Stable error class 加上脱敏 reason (≤ 64 字节)。

V1 **不**定义原始 RT、circuit state 或通用 metrics 字段；它们需要独立的
per-kind schema、privacy/cardinality 评审和 V2 协议，不能借用宽 payload 填入。

## 3. Transport

### 3.1. 选型

Transport 为 HTTP/1.1 + JSON over TCP。此选型与 Atlas Richie 集群令牌
协议 V1 (见 [`集群令牌协议-v1.md`](./集群令牌协议-v1.md)) 一致, 不
引入任何第三方依赖。

### 3.2. 线协议格式

```http
POST /reporting/v1/events HTTP/1.1
Host: <collector_host>
X-Atlas-Reporting-Token: <shared_secret>
Content-Type: application/json; charset=utf-8
Content-Length: <bytes>
Connection: close

<batch_json_body>
```

### 3.3. 响应

Collector 返回 `200 OK` 加上 ack envelope (见 §9), 或 HTTP 错误加上
error envelope (见 §6)。

### 3.4. 大小限制

- 单个 batch 的 UTF-8 JSON byte length **不得**超过 **64 KiB**。
- 单个 envelope 的 UTF-8 JSON byte length **不得**超过 **16 KiB**
  (见 [`上报协议-01-envelope-v1.md` §3.4](./上报协议-01-envelope-v1.md#34-大小限制))。
- 一个 batch **必须**包含最多 256 个 envelopes。
- 超出限制返回相应错误码 (§6)。

### 3.5. Transport 级决策

| 决策 | 选型 | 理由 |
| --- | --- | --- |
| HTTP/1.1 vs HTTP/2 | HTTP/1.1 | 与兄弟协议一致。 |
| TLS | 不支持；仅 loopback | V1 Collector **必须**仅绑定 loopback，配置非 loopback 地址必须启动失败。mTLS 留待 V2。 |
| Keep-alive | 不支持 | V1 简化。单 batch 单连接。 |
| Connection pool | 不支持 | V1 简化。 |
| 压缩 | 不支持 | V1 简化。大小限制足够。 |

## 4. 版本协商

### 4.1. 版本字符串

常量版本字符串为 `"atlas-richie.reporting/v1"`。Reporter 写入每个
batch 的 `protocol_version` 字段。Collector 校验; 不匹配返回
`PROTOCOL_VERSION_MISMATCH`, Reporter **不得**重试。

### 4.2. Bump 策略

| Bump 类型 | 路径 | 例子 |
| --- | --- | --- |
| Major (v1 → v2) | 独立 ADR + 5 owner 签字 | 新增 transport、枚举或错误语义。 |
| Minor (V1 spec revision) | 5 owner 签字 + 兼容性矩阵 | 仅添加可被旧 consumer 安全忽略的 optional 字段；wire string 仍为 `v1`。 |
| Patch (v1.0.0 → v1.0.1) | 单 owner 签字 | typo 修复, 文档澄清, 不改 wire 语义。 |

### 4.3. Major 不匹配行为

- major 不匹配时，Collector **不得**部分解析、静默降级或把未知字段作为语义输入。
- 协议**不得**推测性降级未知 kind。
- Collector 返回 `PROTOCOL_VERSION_MISMATCH` 加上支持 major 版本列表。
- 重试无效; Reporter 应升级。

### 4.4. Minor 修订行为

- V1 的 wire string 只表示 major，故 V1.x **不得**改变它。
- 旧 consumer 必须忽略未知的 optional 字段。
- `event_kind`、错误码、已有字段语义和 Ack 语义不是 optional 扩展点；任何
  此类变更都必须使用 V2。

### 4.5. V1 版本支持

- Reporter: 仅发出 `v1`。
- Collector: 仅接受 `v1`。
- V1.x 不存在第二个 wire 字符串；Collector 仍只接受 `v1`。

## 5. 鉴权

### 5.1. V1 机制: 共享密钥

V1 使用通过 `X-Atlas-Reporting-Token` HTTP header 传输的共享密钥。密钥在
Reporter 启动时配置, 与 Collector 配置配对。V1 仅允许明文 loopback 通道；
Collector 必须拒绝非 loopback bind 配置，不能把该安全边界留给运维约定。

缺失或错误密钥返回 `AUTH_FAILED` (HTTP 401)。

### 5.2. 未来鉴权

| 阶段 | 机制 | 状态 |
| --- | --- | --- |
| 1.0 | 共享密钥 + 明文 header | 本文档。 |
| V2 | Mutual TLS (client cert + 双向认证) | 保留。 |
| V2 或后续 major | OAuth client credentials | 保留。 |

### 5.3. 实例身份绑定

Reporter 配置有跨重启稳定的 `instance_id` (UUID v4) 和持久化的
`startup_epoch` (int64, 每次启动严格递增且永不复用)。两者的持久化介质由
Reporter 配置明确指定；若不能保证该不变量，Reporter 必须拒绝启动。这些与
集群令牌协议使用的 `ClientIdentity` **独立** — 两个身份命名空间**不得**混用。

Collector 使用 `(instance_id, startup_epoch)` 跨 Reporter session 关联
事件。

### 5.4. 凭证安全约束

- 凭证**不得**出现在任何 event payload 中。
- 凭证**不得**出现在任何日志行中。
- 凭证**不得**出现在任何 Dashboard 响应中。
- 凭证**不得**出现在任何错误消息或异常链中。
- 凭证**仅**出现在 HTTP request header 中。

### 5.5. 凭证轮换

V1 在启动时一次性读取共享密钥, 不进行进程内轮换。任何支持凭证轮换的
transport 都需要 V2。如果凭证不可用，Reporter 将情况视为网络中断，应用
有界退避和 overflow 策略 (§11)。

## 6. 错误码

定义 11 个错误码。除重复 batch 的成功 Ack 外，所有校验均为**整个 batch
原子拒绝**；V1 不支持 per-event disposition。

| 错误码 | HTTP | 触发条件 | Reporter 行为 |
| --- | --- | --- | --- |
| `PROTOCOL_VERSION_MISMATCH` | 400 | `protocol_version` ≠ `"atlas-richie.reporting/v1"`。 | **不得**重试, 升级 SDK。 |
| `MALFORMED_ENVELOPE` | 400 | batch 或 envelope 缺必填字段, 或类型错。 | **不得**重试, 记录 error 日志。 |
| `UNKNOWN_EVENT_KIND` | 400 | 任一 `event_kind` 不在 V1 枚举中。 | 丢弃整个 batch；修复或移除该事件后重组 batch。 |
| `PAYLOAD_SCHEMA_MISMATCH` | 400 | 任一 per-kind payload schema 错。 | 丢弃整个 batch；修复或移除该事件后重组 batch。 |
| `INSTANCE_ID_EMPTY` | 400 | `instance_id` 为空字符串。 | **不得**重试, 修复 Reporter。 |
| `SEQUENCE_NOT_MONOTONIC` | 409 | batch 内 sequence 非连续递增，或其范围与 Collector 水位冲突。 | 不重试；记录 protocol fault 并以新 generation 重启 Reporter。 |
| `SEQUENCE_GAP` | 409 | 新 batch 首 sequence 不等于水位 + 1。 | 不重试；记录 protocol fault 并以新 generation 重启 Reporter。 |
| `STALE_EPOCH` | 409 | `startup_epoch` 旧于 Collector 已知最新。 | 丢弃 batch，不重试。 |
| `ENVELOPE_TOO_LARGE` | 413 | 任一 ingress envelope 超过 16 KiB。 | 丢弃 batch；不得重传超限事件。 |
| `BATCH_TOO_LARGE` | 413 | batch 超过 64 KiB。 | 切分, 用更小 batch 重试。 |
| `AUTH_FAILED` | 401 | `X-Atlas-Reporting-Token` 缺失或错。 | **不得**重试, 修复配置。 |

错误 envelope 的线格式:

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "error_code": "MALFORMED_ENVELOPE",
  "message": "field 'sequence' must be int64, got string",
  "details": {
    "field": "sequence",
    "got_type": "string"
  }
}
```

V1 不引入额外错误码。新错误码需要 V2 major + 独立 ADR。

## 7. Batch 格式

### 7.1. Batch envelope

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "sent_at": "2026-09-13T10:00:00.123456Z",
  "events": [
    { /* event envelope 1, 见 上报协议-01-envelope-v1.md §3 */ },
    { /* event envelope 2 */ }
  ],
  "dropped_count": 0
}
```

### 7.2. Batch 字段定义

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `protocol_version` | string | 是 | 同 §4.1。 |
| `instance_id` | string | 是 | UUID v4。同 §5.3。 |
| `startup_epoch` | int64 | 是 | 同 §5.3。 |
| `batch_id` | string | 是 | UUID v4。每 batch 唯一。**不**用于去重, 仅追踪。 |
| `sent_at` | string | 是 | ISO 8601 UTC microsecond。 |
| `events` | array | 是 | 1 ≤ length ≤ 256 个 envelopes；所有 event 的 `protocol_version`、`instance_id`、`startup_epoch` 必须与 batch 同值。 |
| `dropped_count` | int64 | 是 | ≥ 0；当前 generation 自启动起、在 sequence 分配**前**被 Reporter 丢弃的累计事件数。 |

任一 event 与 batch 身份或版本不一致时，Collector 必须以
`MALFORMED_ENVELOPE` 原子拒绝该 batch。一个 batch 只代表一个 Reporter
generation；不得混装多个 instance 或 generation。

### 7.3. 大小限制

- `events.length` ≤ 256; 超出切分为多个 batch。
- 序列化 batch ≤ 64 KiB; 超出返回 `BATCH_TOO_LARGE`。
- 单 envelope ≤ 16 KiB (见
  [`上报协议-01-envelope-v1.md` §3.4](./上报协议-01-envelope-v1.md#34-大小限制))。

## 8. Sequence 与去重

### 8.1. Sequence 语义

- `sequence` 按 `(instance_id, startup_epoch)` 单调递增。
- Sequence 从 **1** 开始 (不是 0)。
- 进程重启后 (新 `startup_epoch`), sequence 从 1 重新开始。

### 8.2. 去重键

唯一去重键是三元组 `(instance_id, startup_epoch, sequence)`。

Reporter 只能在事件成功进入有界 outbox 后分配 sequence。一个 generation
必须由单一 sender 按 sequence 递增发送；未确认的最早 batch 必须先重试，后续
batch 不得越过它。故正常 V1 流没有缺口，也不接受并发乱序。

Collector 维护 `(instance_id, startup_epoch) → max_contiguous_sequence`
水位。一个 batch 要么全部是已确认范围内的精确重传，要么从水位 + 1 开始，且
内部 sequence 连续递增；仅这两种情况可返回成功 Ack。重复 batch 不重复计入指标。

### 8.3. Sequence 乱序与缺口

V1 **强制**严格递增且连续的 ingress sequence。事件生产可以来自并发
slot-chain，但 sequence 分配与 outbox admission 必须串行化；这属于
Reporter 内部实现，不得放宽 wire contract。违反时整个 batch 以 §6 的
`SEQUENCE_NOT_MONOTONIC` 或 `SEQUENCE_GAP` 拒绝，不产生 Ack。

## 9. Ack 语义

### 9.1. Ack envelope

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "received_at": "2026-09-13T10:00:00.456789Z",
  "ack_sequences": [
    {
      "instance_id": "550e8400-e29b-41d4-a716-446655440000",
      "startup_epoch": 0,
      "max_contiguous_sequence": 100
    }
  ],
  "duplicate_count": 0
}
```

### 9.2. Ack 字段定义

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `protocol_version` | string | 是 | 同 §4.1。 |
| `batch_id` | string | 是 | 对应 batch 的 `batch_id`。 |
| `received_at` | string | 是 | ISO 8601 UTC microsecond。Server-authoritative 时间。 |
| `ack_sequences` | array | 是 | length 必须为 1，且身份等于 request batch。 |
| `duplicate_count` | int64 | 是 | 当前 batch 中已确认的精确重传 envelope 数；它们不会重复计入指标。 |

### 9.3. Ack 解读

`max_contiguous_sequence` 是 Collector 已接受的给定
`(instance_id, startup_epoch)` 的最大**连续** sequence。Reporter 把它与
自己最后发送的 `sequence` 比较:

- 相等: 所有事件已被接受，或整个 batch 是已确认的精确重传。
- 更小: V1 中不允许出现在成功 Ack；Collector 必须以 §6 的稳定错误码拒绝
  batch，Reporter 不得继续发送同 generation 的后续 batch。

### 9.4. 无 per-event Ack

V1 仅支持 batch 级 ack；这是因为严格单 generation FIFO 使 batch 的结果
天然原子。若未来需要 per-event disposition，必须使用 V2。

## 10. 旧 Generation 行为

### 10.1. 检测

Collector 在 `event.startup_epoch < max_epoch_seen_for(event.instance_id)`
时认为该 event stale。

### 10.2. 行为: 原子拒绝

- Collector 必须以 `STALE_EPOCH` (HTTP 409) 拒绝整个 stale batch，且不产生
  Ack。
- Collector 不得将该 batch 计入 metrics 或 audit。
- Reporter 必须丢弃该 batch 且不得重试；这不会阻塞受保护业务请求。

这与集群令牌协议的 `STALE_EPOCH` 围栏一致 (见
[`集群令牌协议-v1.md` §3.1](./集群令牌协议-v1.md#31-三大核心不变量))。

### 10.3. 理由

Stale batch 是重启与网络延迟的预期 race。显式拒绝使 Reporter 不会把没有
推进的 Ack 误认为可继续发送。围栏是强制的：上一 generation 的迟到事件
不得影响新 generation。

## 11. 背压与 Overflow 策略

### 11.1. 有界队列

Reporter 维护一个进程内队列, 最多 4096 个事件 (V1 简化)。队列满时,
overflow 策略生效。

### 11.2. Overflow 策略

1. 事件在进入 outbox 前被丢弃，`dropped_count` 累加；因此被丢弃事件不占用
   sequence，也不会制造 wire gap。
2. `RULE_SOURCE_DEGRADED` 只表达 RuleSource 健康，**不得**复用为 Reporter
   queue 或 cardinality 告警。
3. 在飞 batch 不中断。
4. Reporter **不得**阻塞受保护请求路径。`queue.put_nowait` 失败导致
   丢弃, 永不等待。

### 11.3. 退避与 Deadline

- 单 batch 发送 deadline 为 **5 秒** (与集群令牌 Client V1 一致)。
- 瞬时失败 (5xx, 网络) 时, 最多重试 3 次, 指数退避 50 ms / 200 ms / 1 s。
- 4xx 或 `AUTH_FAILED` 时, 不重试 (Client 端 bug 或配置错误)。

### 11.4. 优雅关闭

关闭时, Reporter 等待最多 5 秒, 让在飞 batch 完成。任何未能在该时间内
flush 的待发事件被丢弃 (计入 `dropped_count`)。V1 在关闭期间不保证
at-least-once 投递。

### 11.5. Reporter 独立性

Reporter 的发送任务与 Engine 热路径独立。异步宿主使用所属 event loop 中的
单一 writer task；同步宿主由其 adapter 持有专用 loop/thread。每 batch 创建
`asyncio.new_event_loop()` 是禁止的，因为它破坏连接与关闭生命周期。

## 12. Cardinality 与 Dropped 统计

### 12.1. Cardinality 配额

| 维度 | V1 上限 | 超出行为 |
| --- | --- | --- |
| 唯一 `instance_id` | 1 | N/A |
| 每 `instance_id` 的 `startup_epoch` | 无界 | N/A |
| 唯一 `source_id` | ≤ 8 | 丢弃, 递增 `source_cardinality_exceeded`。 |
| 每 source 的唯一 `rule_id` | ≤ 256 | 丢弃, 递增 `rule_cardinality_exceeded`。 |
| 唯一 `event_kind` | 6 (V1 冻结) | 丢弃, 递增 `event_kind_unknown`。 |

### 12.2. Dropped 统计

每个 batch 包含 generation 内累计的 `dropped_count`：只计算 sequence 分配前
被 Reporter 的队列、cardinality 或关闭策略主动丢弃的事件。它不是“本 batch
内”计数，Collector 用它观察 Reporter 自身数据损失。

每个 Ack 包含 `duplicate_count`：它只统计当前 batch 的已确认精确重传，不能与
Reporter 的 `dropped_count` 混淆。

### 12.3. Cardinality 监控

V1 不定义单独的 cardinality event，也不借用 source-health event。Collector
通过 batch 的累计 `dropped_count` 和本地受限指标观察该状态；新增可传输指标
字段必须使用 V2。

### 12.4. Cardinality 配置

V1 硬编码限制。Collector 本地调整上限不得改变 wire semantics；任何需要
客户端协商的配额配置需要 V2。

## 13. 安全考虑

- **数据边界**: 见 §2。协议**不得**携带业务数据、凭证、原始异常或 PII。
- **鉴权**: 见 §5。V1 使用明文共享密钥且 Collector **必须**仅绑定
  loopback；非 loopback 配置必须启动失败。mTLS 需要 V2。
- **凭证处理**: 见 §5.4。密钥仅出现在 HTTP request header 中。
- **授权**: cardinality 配额 (§12) 限制 Collector 的内存和 CPU 消耗。
- **机密性**: V1 不提供跨主机机密性保证，故没有“非 loopback + TLS”的
  例外部署模式。

## 14. IANA 考量

本文档不申请任何 IANA 动作。

## 15. 兼容性矩阵

| 变更类型 | 是否破坏 V1 | 路径 | 约束 |
| --- | --- | --- | --- |
| 在 batch envelope 添加可选字段 | 否 | V1.x spec revision + ADR | 旧 consumer 忽略未知字段。 |
| 在 event envelope 添加可选字段 | 否 | V1.x spec revision + ADR | 旧 consumer 忽略未知字段。 |
| 添加新 `event_kind` | 是 | V2 major + 独立 ADR | 枚举与处理语义同步变更。 |
| 添加新错误码 | 是 | V2 major + 独立 ADR | Reporter 行为需要明确。 |
| 改 `event_kind` 字符串值 | **是** | V2 major + 独立 ADR | 旧 enum 值不再恢复。 |
| 改 `ack_sequences` 语义 | **是** | V2 major + 独立 ADR | 跨语言 SDK **必须**更新。 |
| 删除 batch envelope 字段 | **是** | V2 major + 独立 ADR | 旧 consumer 立即 break。 |
| 改大小限制 (> 64 KiB) | **是** | V2 major + 独立 ADR | 跨语言 SDK **必须**调整 buffer。 |
| 改 `protocol_version` 字符串 | **是** | V2 major + 独立 ADR | 路由层立即 break。 |

V1 冻结后, 任何 V1-breaking 变更**不得**静默合入。所有这些变更需要
V2、新 ADR 和 5 owner 签字。

## 16. 跨语言合同测试

| 测试 | 描述 |
| --- | --- |
| `python_serialize_roundtrip` | Python batch 序列化 → JSON → 反序列化; 所有字段值完全一致。 |
| `python_batch_serialize_roundtrip` | Batch envelope 保留 `events` 数组顺序。 |
| `python_payload_schema_per_kind` | 六种 `event_kind` payload 各自 round-trip; 字段顺序无关。 |
| `python_time_iso8601_utc` | ingress 的 `captured_at`、batch `sent_at` 与 Ack 的 `received_at` 使用 microsecond 精度。 |
| `python_protocol_version_constant` | 任何不等于 `"atlas-richie.reporting/v1"` 的值抛 `PROTOCOL_VERSION_MISMATCH`。 |
| `python_malformed_envelope` | 缺失/类型错字段抛 `MALFORMED_ENVELOPE`; 违规 envelope 丢弃。 |
| `python_sequence_dedup` | 重复 `sequence` 不重复计数。 |
| `python_stale_epoch_reject` | 旧 generation batch 以 `STALE_EPOCH` 原子拒绝，且不会影响聚合。 |
| `python_ack_envelope_schema` | Ack envelope 字段 + `max_contiguous_sequence` 正确填充。 |
| `go_mock_decode` | Go SDK mock 解码同 spec; 字段名 + 类型完全一致。 |
| `java_mock_decode` | Java SDK mock 解码同 spec; 字段名 + 类型完全一致。 |

## 17. 未来工作

- mTLS 鉴权 (V2)。
- Per-event disposition (V2)。
- 可配置 cardinality 配额 (V2)。
- 多进程 Server 分布式幂等性状态存储 (V2；不预设 Redis)。
- 在 envelope 添加 `tenant` 字段（需 V1.x capability 协商或 V2）。

## 附录 A. 示例

### A.1. 成功 batch ack

```http
POST /reporting/v1/events HTTP/1.1
Host: collector.internal
X-Atlas-Reporting-Token: ********
Content-Type: application/json; charset=utf-8
Content-Length: 1024
Connection: close

{
  "protocol_version": "atlas-richie.reporting/v1",
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "sent_at": "2026-09-13T10:00:00.123456Z",
  "events": [
    {
      "protocol_version": "atlas-richie.reporting/v1",
      "event_kind": "RULE_APPLIED",
      "event_payload": {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1726000000,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:abc...",
        "exec_result": "APPLIED",
        "failure_class": null
      },
      "instance_id": "550e8400-e29b-41d4-a716-446655440000",
      "startup_epoch": 0,
      "sequence": 1,
      "captured_at": "2026-09-13T10:00:00.100000Z"
    }
  ],
  "duplicate_count": 0
}
```

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Length: 312
Connection: close

{
  "protocol_version": "atlas-richie.reporting/v1",
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "received_at": "2026-09-13T10:00:00.456789Z",
  "ack_sequences": [
    {
      "instance_id": "550e8400-e29b-41d4-a716-446655440000",
      "startup_epoch": 0,
      "max_contiguous_sequence": 1
    }
  ],
  "duplicate_count": 0
}
```

## 附录 B. 签字

本草案完成 5 owner 签字后方可冻结。family-level 5-owner 签字记录维护在
[`上报协议-03-freeze-v1.md`](./上报协议-03-freeze-v1.md)。
后续修订需要新签字周期 + §15 列出的变更。

## 版本历史

| 版本 | 日期 | 作者 | 变更 |
| --- | --- | --- | --- |
| 1.0-draft.2 | 2026-09-13 | Atlas Richie Team / Mavis | 收口 FIFO、Ack、generation、鉴权与溢出语义。 |

## 作者地址

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)
