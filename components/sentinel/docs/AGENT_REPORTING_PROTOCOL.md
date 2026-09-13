# Atlas Richie Sentinel — Agent Reporting Protocol (V1)

> **V1 冻结** (M6.5.7 sign-off, 1.0 publish 前冻结).
> V1 不可破坏性: 加 optional field 走 V1.1 minor; 改 / 删 / 改语义 / 改
> protocol_version 字符串走 V2 major bump (独立 ADR).
> 配套 design / sign-off 文档: [`docs/ENVELOPE-SCHEMA-FREEZE.md`](../ENVELOPE-SCHEMA-FREEZE.md).

| Field | Value |
| ----- | ----- |
| Protocol | `atlas-richie.reporting/v1` |
| Status | **Frozen** (1.x 全程可用, 不删字段) |
| Transport | (留空, M6.5.1 决策) |
| Encoding | JSON over UTF-8, 严格遵循本 schema |
| Cardinality | 单 envelope ≤ 16 KB; 6 个 V1 event_kind 全部枚举 |

---

## 1. 设计原则

### 1.1 envelope 不参与准入决策

本协议**不**承载业务请求 / 响应内容 / 用户身份 / 认证材料 / 任意日志
/ 完整规则正文。错误事件仅允许 stable error class + 脱敏 reason (≤ 64
bytes), 禁止原始异常消息 / traceback / frame locals。

### 1.2 跨语言稳定契约

- 所有 language SDK 共享同一 schema; Python `dataclass` 跟 Java
  `record` / Go `struct` / Rust `struct` 字段一一对应
- 时间字段用 ISO 8601 UTC with microseconds (`2026-09-13T10:00:00.123456Z`),
  跨语言一致
- 数字字段用 64-bit signed integer (跨语言一致)

### 1.3 两个时间字段必须分开 (V1 v3 决策)

| 字段 | 写入方 | 服务端权威 | 用途 |
| --- | --- | --- | --- |
| `captured_at` | Reporter 进程本地 UTC clock | ❌ | **仅供诊断** (乱序 / 缺口) |
| `received_at` | Collector 写入 | ✅ | 聚合 / 排序 / 跨进程比较的**唯一**权威 |

**禁止合成单一 `capture_time` 字段**。原因: server-authoritative 与 本地
UTC 互相矛盾, 跨语言无法解释 (Python `datetime.now(tz=UTC)` 与 Go
`time.Now().UTC()` / Java `Instant.now()` 的 timezone 序列化差异; 用
server-authoritative 字段作为唯一权威消除歧义)。

---

## 2. envelope schema (V1)

### 2.1 完整 envelope (8 字段, 全部必填)

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "event_kind": "RULE_SOURCE_ACTIVATED",
  "event_payload": {
    "source_id": "nacos-prod",
    "rule_version_epoch": 1726000000,
    "rule_version_revision": 0,
    "rule_version_checksum": "sha256:abc123..."
  },
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "sequence": 1,
  "captured_at": "2026-09-13T10:00:00.123456Z",
  "received_at": "2026-09-13T10:00:00.456789Z"
}
```

### 2.2 字段定义

| 字段 | 类型 | 必填 | 约束 | 写入方 |
| --- | --- | --- | --- | --- |
| `protocol_version` | string | ✅ | 常量 `"atlas-richie.reporting/v1"`; 任何不一致 = 协议错误, 禁止静默忽略 | Reporter |
| `event_kind` | string | ✅ | V1 枚举见 §3; 6 个允许值 | Reporter |
| `event_payload` | object | ✅ | per-kind frozen schema, 见 §3; 严禁 `dict[str, Any]` | Reporter |
| `instance_id` | string | ✅ | UUID 字符串; Reporter 实例唯一身份, 同进程同 epoch 不变 | Reporter |
| `startup_epoch` | int64 | ✅ | 单调递增, 进程启动后从 0 开始; 用于 Collector 去重旧 epoch 迟到数据 | Reporter |
| `sequence` | int64 | ✅ | 单调递增, 同 (instance_id, startup_epoch) 内连续; 用于缺口检测 + 乱序排序 | Reporter |
| `captured_at` | string | ✅ | ISO 8601 UTC, microsecond 精度 (`YYYY-MM-DDTHH:MM:SS.ffffffZ`); **仅诊断**, **不**做服务端权威 | Reporter |
| `received_at` | string | ✅ | ISO 8601 UTC, microsecond 精度; **唯一**服务端权威字段 | Collector |

### 2.3 字段序列化

- **字符串**: UTF-8, 严格 JSON 字符串 (无多余空白)
- **数字**: JSON number; 整数 64-bit signed (`int64`); 浮点不出现
- **布尔**: JSON `true` / `false`
- **时间**: ISO 8601 UTC, microsecond 精度, 强制 `Z` 后缀 (无 timezone
  offset); 跨语言 strftime 模板 `%Y-%m-%dT%H:%M:%S.%fZ`
- **UUID**: 8-4-4-4-12 格式, 小写; 跨语言一致
- **checksum**: `sha256:<hex>` (64 hex chars), 跨语言一致
- **object 字段顺序**: 不保证; 跨语言 consumer 必须按 key 解析, 不按 position

### 2.4 必填字段缺失

任何必填字段缺失或类型不匹配 → 协议错误 (`ProtocolVersionMismatch` /
`MalformedEnvelope`); Collector **不**静默忽略字段, **不**猜测降级解析。

### 2.5 size 上限

单 envelope ≤ 16 KB (序列化后). 超出 → 协议错误, Reporter 走 overflow policy
(M6.5.3 决策).

---

## 3. event_kind V1 枚举 (6 个, 冻结)

### 3.1 完整 V1 枚举

| event_kind | 类别 | 用途 | payload schema |
| --- | --- | --- | --- |
| `RULE_SOURCE_ACTIVATED` | source-switch | 切源 / 启源 (新 source_id + version 进入 active) | `RuleSourceActivatedPayload` |
| `RULE_SOURCE_STALE` | health | 不切源但状态变 stale (last-known-good 仍可消费) | `RuleSourceHealthPayload` |
| `RULE_SOURCE_DEGRADED` | health | health 进一步恶化 (degraded / disconnected) | `RuleSourceHealthPayload` |
| `RULE_APPLIED` | biz-exec | 规则被成功 apply 到 Engine | `RuleExecPayload` |
| `RULE_BLOCKED` | biz-exec | 规则 block 一次请求 | `RuleExecPayload` |
| `RULE_FAILED` | biz-exec | 规则应用失败 (codec / type / state 错) | `RuleExecPayload` |

### 3.2 类别规则

- **source-switch event** (RULE_SOURCE_ACTIVATED): 切源 / 启源时上报;
  payload 必含 `source_id` + 完整 `rule_version_*` 三元组 (epoch /
  revision / checksum)
- **health event** (RULE_SOURCE_STALE / `_DEGRADED`): 不切源但状态变化;
  payload 必含 `source_id` + `health_class` 字符串
- **biz-exec event** (RULE_APPLIED / `_BLOCKED` / `_FAILED`): 业务执行结果;
  payload 必含 `source_id` + `rule_id` + 业务执行结果字段

**health event 与 source-switch event 不混用同一 kind**: 切源走
`RULE_SOURCE_ACTIVATED`, 不切源但状态变化走 health 类。

### 3.3 V1 不可新增 event_kind (签字后)

M6.5.7 签字后, 任何子任务 (M6.5.1 / M6.5.2 / M6.5.3 / M6.5.6) **禁止**
直接向 V1 枚举塞项。新增 event_kind 必须走 V1.1 minor (走 ADR + 兼容性
矩阵) 或 V2 major (独立 ADR).

### 3.4 不可用的 event_kind 命名

- `*_DEBUG` / `*_TEST` / `*_INTERNAL` — 业务边界外
- 单数字后缀 (`EVENT_1`) — 不可读
- 长字符串 (> 64 chars) — wire size 浪费

---

## 4. event_payload schema (per-kind frozen)

### 4.1 `RuleSourceActivatedPayload` (RULE_SOURCE_ACTIVATED)

```json
{
  "source_id": "nacos-prod",
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123..."
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `source_id` | string | ✅ | RuleSource.source_id, ≤ 256 chars, 跨语言 SDK 必须接受任意 UTF-8 |
| `rule_version_epoch` | int64 | ✅ | ≥ 0; 单调递增, 但 V1 不强制严格 (clock skew 容忍) |
| `rule_version_revision` | int64 | ✅ | ≥ 0; 同 epoch 内单调 |
| `rule_version_checksum` | string | ✅ | `sha256:` 前缀 + 64 hex chars |

**来源**: 来自 M6.1 内部 `RuleSourceActivation` fact (C 层 frozen
dataclass); M6.5.3 Reporter 序列化为本 payload (M6.5.7 envelope 路径),
**不**直接进 wire.

### 4.2 `RuleSourceHealthPayload` (RULE_SOURCE_STALE / _DEGRADED)

```json
{
  "source_id": "nacos-prod",
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123...",
  "health_class": "STALE",
  "reason_class": "EMPTY_DATA_ID",
  "reason_message": "nacos data_id returns empty content (server returned 200 OK with empty body)"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `source_id` | string | ✅ | 同 §4.1 |
| `rule_version_epoch` | int64 | ✅ | 同 §4.1 |
| `rule_version_revision` | int64 | ✅ | 同 §4.1 |
| `rule_version_checksum` | string | ✅ | 同 §4.1 |
| `health_class` | string | ✅ | V1 允许值: `STALE`, `DEGRADED`, `DISCONNECTED` |
| `reason_class` | string | ✅ | stable error class (e.g. `EMPTY_DATA_ID`, `NETWORK_TIMEOUT`, `AUTH_FAILED`, `DECODE_FAILED`) |
| `reason_message` | string | ❌ | 脱敏 reason, ≤ 64 bytes; 严禁原始异常 / traceback / frame locals / 用户数据 |

### 4.3 `RuleExecPayload` (RULE_APPLIED / _BLOCKED / _FAILED)

```json
{
  "source_id": "nacos-prod",
  "rule_id": "flow:/api/v1/users",
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123...",
  "exec_result": "BLOCKED",
  "failure_class": null
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `source_id` | string | ✅ | 同 §4.1 |
| `rule_id` | string | ✅ | ≤ 256 chars; 跨语言一致 (e.g. `"flow:/api/v1/users"`) |
| `rule_version_epoch` | int64 | ✅ | 同 §4.1 |
| `rule_version_revision` | int64 | ✅ | 同 §4.1 |
| `rule_version_checksum` | string | ✅ | 同 §4.1 |
| `exec_result` | string | ✅ | V1 允许值: `APPLIED`, `BLOCKED`, `FAILED` |
| `failure_class` | string | ❌ | 仅 `exec_result=FAILED` 时必填; stable error class; 严禁原始异常 |

---

## 5. 协议错误 (M6.5.1 决策, 摘要)

| 错误名 | 触发 | 行为 |
| --- | --- | --- |
| `ProtocolVersionMismatch` | `protocol_version` ≠ `"atlas-richie.reporting/v1"` | Collector 返回错误; Reporter 重试无效, 应升级 SDK |
| `MalformedEnvelope` | 必填字段缺失 / 类型错 | Collector 返回错误; 单条丢弃, 不影响其他 batch |
| `UnknownEventKind` | `event_kind` 不在 V1 6 个枚举中 | Collector 返回错误; 单条丢弃 |
| `PayloadSchemaMismatch` | per-kind payload 字段缺失 / 类型错 | Collector 返回错误; 单条丢弃 |
| `InstanceIdEmpty` | `instance_id` 为空字符串 | Collector 返回错误 |
| `SequenceNotMonotonic` | 同 (instance_id, startup_epoch) 内 `sequence` 不单调 | Collector 接受但 flag; 不影响投递 |
| `SequenceGap` | 同 (instance_id, startup_epoch) 内 `sequence` 有缺口 | Collector 接受但 flag; 不影响投递 |
| `StaleEpoch` | envelope 的 `startup_epoch` < Collector 已知的同 instance_id 最新 epoch | Collector 丢弃 (迟到数据, M6.5.4 去重) |
| `EnvelopeTooLarge` | 序列化后 > 16 KB | Collector 返回错误; Reporter 走 overflow policy (M6.5.3 决策) |

**重试策略**: Collector 不重试 (at-least-once 由 Reporter 负责); Reporter
按 M6.5.3 退避策略重试; `StaleEpoch` / `MalformedEnvelope` 不重试
(permanently failed, 丢弃 + log warn).

---

## 6. V1 兼容性矩阵

| 变更类型 | 是否破坏 V1 | 路径 | 约束 |
| --- | --- | --- | --- |
| 加 optional field (现有 enum 之外) | 否 | V1.1 minor + ADR | 旧 consumer 不读也兼容 |
| 加新 event_kind | 否 (V1 6 个仍合法) | V1.1 minor + ADR | 旧 consumer skip unknown kind |
| 改 event_kind 字符串值 | **是** | V2 major + 独立 ADR | 老 enum 永不再恢复 |
| 改 event_payload 字段语义 | **是** | V2 major + 独立 ADR | 跨语言 SDK 必须更新 |
| 删字段 | **是** | V2 major + 独立 ADR | 旧 consumer 立刻 break |
| 改时间字段语义 (captured_at / received_at) | **是** | V2 major + 独立 ADR | 跨语言时区序列化 |
| 改 protocol_version 字符串 | **是** | V2 major + 独立 ADR | 路由层立刻 break |
| 改 size 上限 (> 16 KB) | **是** | V2 major + 独立 ADR | 跨语言 SDK 必查 |

**M6.5.7 签字后**, 任何破坏 V1 兼容性的变更**禁止**在 1.x 末静默塞入, 必须
走 V2 + 新 ADR + 用户签字。

---

## 7. 跨语言 contract test (1.0 publish 前 worker 实施)

| 测试 | 描述 |
| --- | --- |
| `python_serialize_roundtrip` | Python 序列化 envelope → JSON → 反序列化 → 字段值完全一致 (frozen dataclass 一一对应) |
| `python_payload_schema_per_kind` | 6 个 event_kind 各自 payload 序列化反序列化, 字段顺序无关 (按 key 解析) |
| `python_time_iso8601_utc` | `captured_at` / `received_at` 用 microsecond 精度, 跨语言 SDK strftime 模板一致 |
| `python_protocol_version_constant` | 任何跟 `"atlas-richie.reporting/v1"` 不一致 → 抛 `ProtocolVersionMismatch` |
| `python_malformed_envelope` | 必填字段缺失 / 类型错 → 抛 `MalformedEnvelope`, 单条丢弃 |
| `go_mock_decode` | Go SDK mock (1.0 publish 前 worker 实施) 用同 spec 反序列化, 字段名 + 类型完全一致 |
| `java_mock_decode` | Java SDK mock (1.0 publish 前 worker 实施) 用同 spec 反序列化, 字段名 + 类型完全一致 |

---

## 8. 后续工作 (1.0 publish 前, 1.x 末 worker / Mavis)

- M6.5.1 决策 transport (gRPC / HTTP / 自定义) + 父协议 envelope 路径
- M6.5.2 Reporter 批次 + ack 状态机 + 缺口 / 乱序处理
- M6.5.3 Reporter 实现 (batch / queue / backoff / overflow)
- M6.5.4 Collector 实现 (去重 / 乱序 / stale epoch)
- M6.5.5 实例认证 (mTLS / OAuth)
- M6.5.6 cardinality 配额 + dropped 统计
- `atlas-richie-contracts` 加 `atlas_richie.reporting.v1` 包 (Python 投影)
- 跨语言 contract test (Go / Java SDK mock)

---

## 9. sign-off

本 V1 spec 签字栏见 [`docs/ENVELOPE-SCHEMA-FREEZE.md` §9](../ENVELOPE-SCHEMA-FREEZE.md#9-sign-off-%E6%A0%8F-5-owner)。
5 owner 全部签字后, V1 冻结; 任何变更走 §6 兼容性矩阵。

---

**Document version**: 1.0 (frozen)
**Created by**: Mavis (mvs_cef3b0c9918e473f8de8ad4b42fef7ca)
**Last updated**: 2026-09-13
**Status**: V1 frozen, awaiting 5 owner sign-off
