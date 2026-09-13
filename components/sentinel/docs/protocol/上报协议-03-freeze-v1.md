# Atlas Richie 事件上报 Envelope Schema V1 冻结记录

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0 (Frozen)
> **Status**: Standards Track — V1 Released
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **语言**: [中文 (本文件)](./上报协议-03-freeze-v1.md) · [English](./reporting-protocol-03-freeze-record-v1.md)

---

## 摘要 (Abstract)

本文档记录 Atlas Richie Agent Reporting Envelope Schema 的 V1 正式冻结。
它是 [`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 的 sign-off 记录, 也是
Reporter 和 Collector **必须**遵守的 schema 级合同。

本文档有意保持简短。Schema 本身, 包括所有字段定义, payload 类型, 以及
序列化规则, 在 [`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 中规定。
外层 transport, 鉴权, batching 和 sequence 语义在
[`上报协议-02-transport-v1.md`](./上报协议-02-transport-v1.md) 中规定。本文档只记录冻结事件本身,
以及由此带来的不可变性保证。

## 本备忘录状态 (Status of This Memo)

本文档记录 Atlas Richie Agent Reporting Envelope Schema 的 V1 冻结。
本备忘录的分发不受限制。

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
`atlas-richie.reporting/v1` 标识, 自 2026-09-13 起在此**正式声明 FROZEN**。

被冻结的工件是 [`上报协议-01-envelope-v1.md`](./上报协议-01-envelope-v1.md) 中规定的
schema。以下内容是 V1 合同的组成部分, 在没有新的版本号 bump, 加上新的 ADR
和 5-owner 签字的前提下, **不得**改变:

- Envelope 字段集 (8 个字段) 及其类型。
- 6 个 `event_kind` 字符串值。
- 3 个 `event_payload` schema 类型及其字段集。
- 序列化规则 (UTF-8 字符串, ISO 8601 微秒时间, 小写 UUID, 基于 key 的
  object 解析)。
- 大小限制 (envelope ≤ 16 KB; 参见 `上报协议-02-transport-v1.md` §3.4)。

## 2. 不可变性保证

冻结日之后:

1. 6 个 `event_kind` 值不可变。新的取值需要 V1.1 minor release 和一个 ADR。
2. 3 个 `event_payload` schema 不可变。在已有 schema 中新增字段需要 V1.1。
   新增 payload 类型需要 V1.1 minor 和一个 ADR。
3. Envelope 大小限制 (16 KB) 不可变。提高该上限需要 V2 major 和一个 ADR。
4. Wire 标识符字符串 (`atlas-richie.reporting/v1`) 不可变。任何改动需要
   V2 major 和一个 ADR。
5. [`上报协议-01-envelope-v1.md` §3.3](./上报协议-01-envelope-v1.md#33-serialization)
   中的序列化规则不可变。

## 3. 与后续版本的兼容性

### 3.1. V1 Consumer 读取 V1.1 Producer

V1 consumer 在收到带额外可选字段的 V1.1 envelope 时, **必须**忽略未知
字段。V1 consumer 在收到 V1 枚举中不存在的 V1.1 `event_kind` 时, **必须**
对**那一个**违例 envelope 返回 `UNKNOWN_EVENT_KIND`, 不是整批。

### 3.2. V1.1 Consumer 读取 V1 Producer

V1.1 consumer **必须**把 V1 envelope 作为子集接受。它**必须**接受全部
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
| 1.0  | 2026-09-13 | Atlas Richie Team / Mavis    | 首次 V1 冻结记录。          |

## 作者地址

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)
