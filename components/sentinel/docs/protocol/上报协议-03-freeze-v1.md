# Atlas Richie 事件上报 Envelope Schema V1 冻结候选记录

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0 (Draft)
> **Status**: Provisional — sign-off pending
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **语言**: [中文 (本文件)](./上报协议-03-freeze-v1.md) · [English](./reporting-protocol-03-freeze-record-v1.md)

---

## 摘要 (Abstract)

本文档记录 Atlas Richie Agent Reporting Envelope Schema 的 V1 冻结候选。
它是 [`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 的 sign-off 记录, 也是
Reporter 和 Collector **必须**遵守的 schema 级合同。

本文档有意保持简短。Schema 本身, 包括所有字段定义, payload 类型, 以及
序列化规则, 在 [`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 中规定。
外层 transport, 鉴权, batching 和 sequence 语义在
[`上报协议-02-transport-v1.md`](./上报协议-02-transport-v1.md) 中规定。本文档只记录冻结事件本身,
以及由此带来的不可变性保证。

## 本备忘录状态 (Status of This Memo)

本文档记录 Atlas Richie Agent Reporting Envelope Schema 的 V1 冻结候选。
在全部 owner 签字前，它不是已发布或不可变的 wire contract。

## 版权声明 (Copyright Notice)

Copyright © 2026 Atlas Richie. 本文档根据 Apache License 2.0 分发。

## 目录 (Table of Contents)

1. [冻结声明](#1-冻结声明)
2. [不可变性保证](#2-不可变性保证)
3. [与后续版本的兼容性](#3-与后续版本的兼容性)
4. [交叉引用](#4-交叉引用)
5. [签字](#5-签字)
[版本历史](#版本历史)
[作者地址](#作者地址)

---

## 1. 冻结声明

Atlas Richie Agent Reporting Envelope Schema V1, 由 wire 字符串
`atlas-richie.reporting/v1` 标识，当前处于 **DRAFT / PROVISIONAL**。只有 §5
的五位 owner 全部签字后，维护者才能将状态改为 **FROZEN**；此前不得把它作为
已发布或不可变合同使用。

被冻结的工件是 [`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 中规定的
schema。以下内容是拟冻结 V1 合同的组成部分；签字后，除非有新的版本号 bump、
ADR 和新的 5-owner 签字，**不得**改变：

- Reporter ingress envelope 字段集 (7 个字段) 及其类型；Collector 写入的
  `received_at` 只属于 Ack / 持久化投影。
- 6 个 `event_kind` 字符串值。
- 3 个 `event_payload` schema 类型及其字段集。
- 序列化规则 (UTF-8 字符串, ISO 8601 微秒时间, 小写 UUID, 基于 key 的
  object 解析)。
- 大小限制 (envelope ≤ 16 KB; 参见 `上报协议-02-transport-v1.md` §3.4)。

## 2. 不可变性保证

正式冻结之后：

1. 6 个 `event_kind` 值不可变。新的取值需要 V2 major 和一个 ADR。
2. 3 个 `event_payload` schema 不可变。可安全忽略的 optional 字段需要 V1.x
   compatibility matrix；新增 payload 类型需要 V2 major 和一个 ADR。
3. Envelope 大小限制 (16 KB) 不可变。提高该上限需要 V2 major 和一个 ADR。
4. Wire 标识符字符串 (`atlas-richie.reporting/v1`) 不可变。任何改动需要
   V2 major 和一个 ADR。
5. [`上报协议-01-envelope-v1.md` §3.3](./上报协议-01-envelope-v1.md#33-serialization)
   中的序列化规则不可变。

## 3. 与后续版本的兼容性

### 3.1. V1 Consumer 读取 V1.x Producer

V1 consumer 在收到带额外可选字段的 V1.x envelope 时，**必须**忽略未知字段。
V1.x 不得新增 `event_kind`、错误码或改变 Ack 语义；此类变更必须走 V2。

### 3.2. V1.x Consumer 读取 V1 Producer

V1.x consumer **必须**把 V1 envelope 作为子集接受。它**必须**接受全部
6 个 V1 `event_kind` 值, 全部 3 个 V1 payload 类型, 以及 V1 envelope 大小
上限。

### 3.3. V2 Major 兼容性

V2 将使用独立的 wire 标识符 (`atlas-richie.reporting/v2`)。支持 V2 的
Collector 仍将继续接受 V1。支持 V2 的 Reporter 中, V1 producer 支持是
可选的。

## 4. 交叉引用

| 文档 | 用途 |
| --- | --- |
| `上报协议-01-envelope-v1.md` (本协议族) | V1 envelope schema。本文冻结的工件。 |
| `上报协议-02-transport-v1.md` | 外层 transport, 鉴权, batching 和 sequence。 |
| `集群令牌协议-v1.md` (兄弟协议) | Atlas Richie 集群令牌协议 (准入)。 |
| `process/M6.5-REPORTING-PROTOCOL-V1.md` | M6.5 的过程设计文档 (内部)。 |
| `process/M6.5.7-ENVELOPE-FREEZE.md` | 历史 sign-off 记录 (已被本文档取代)。 |

## 5. 签字

本 V1 冻结由以下 5 位 owner 签字:

| Owner    | 角色                                  | 状态         | 日期       |
| -------- | ------------------------------------- | ------------ | ---------- |
| richie696 | Project owner                          | ☐ pending    |            |
| owner 1  | Protocol designer                     | ☐ pending    |            |
| owner 2  | Reporter implementation owner          | ☐ pending    |            |
| owner 3  | Collector implementation owner         | ☐ pending    |            |
| owner 4  | Cross-language SDK owner               | ☐ pending    |            |

在 5 位 owner 全部签字之前, V1 处于 provisional 状态。5 位签字全部到位
之后, 本文档即为正式的 V1 冻结记录, 任何改动**必须**遵守 §2 和 §3 的
程序。

## 版本历史

| 版本 | 日期       | 作者                          | 改动                       |
| ---- | ---------- | ----------------------------- | -------------------------- |
| 1.0-draft.2 | 2026-09-13 | Atlas Richie Team / Mavis | 收口前的 provisional 冻结候选。 |

## 作者地址

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)
