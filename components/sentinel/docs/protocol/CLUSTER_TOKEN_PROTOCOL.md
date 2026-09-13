# Atlas Richie Sentinel — Cluster Token Protocol (V1)

> **V1 冻结** (M6.3.1 sign-off, 1.0 publish 前冻结).
> 配套 design / sign-off 文档: [`docs/process/M6.3-CLUSTER-TOKEN-DESIGN.md`](../M6.3-CLUSTER-TOKEN-DESIGN.md).
> 配套 envelope spec: [`docs/protocol/AGENT_REPORTING_PROTOCOL.md`](./AGENT_REPORTING_PROTOCOL.md) (M6.5.7 frozen).

| Field | Value |
| ----- | ----- |
| Protocol | `atlas-richie.cluster.token/v1` |
| Status | **Frozen** (1.x 全程可用, 不删字段) |
| Transport | (留空, M6.3.4 决策) |
| Encoding | JSON over UTF-8, 严格遵循本 schema |
| Direction | **Client → Server → Client** (request / response 模式, 无 server-push) |
| Idempotency | `request_id` 字段, Server 短期 cache (5 min TTL) |

---

## 1. 设计原则

### 1.1 三个核心不变量 (PLANNING §M6.3 验收)

- **Server 决定 lease 有效性**: Client 不能按本机墙上时钟续约或回收
- **opaque lease identity**: Server 生成, Client 不能伪造
- **owner epoch fencing**: 旧 epoch 迟到 release / renew 不影响新 epoch

### 1.2 失败模式 3 选 1 (PLANNING §M6.3.6)

| Policy | 强保证 | 风险 |
| --- | --- | --- |
| `FAIL_CLOSED` | 实际 grant 总量不超 Server 配额 | **真**deny, 业务受影响 |
| `FAIL_OPEN` | 不承诺不超发 | 可能超发, 但每次放行有可查询决策 + 指标 |
| `LOCAL_FALLBACK` | 显式配置本地策略, **不**伪装共享配额 | 仅本机决策, 多实例不一致 |

**禁止默认静默放行**: 每个集群资源必须显式选 1 项 policy.

### 1.3 启动形态 (PLANNING §M6.3.5)

- `standalone`: 独立 Server 进程
- `embedded`: 单 worker 宿主进程内启 Server (启动 assert `worker_count == 1`)
- `client_only`: 永远只做 Client

**禁止按 Uvicorn worker ordinal 选主、隐式自举、leader election、服务发现猜测 owner**.

---

## 2. message_kind V1 枚举 (5 个, 冻结)

| message_kind | 方向 | 用途 |
| --- | --- | --- |
| `ACQUIRE_REQUEST` | Client → Server | 申请 lease |
| `ACQUIRE_RESPONSE` | Server → Client | 返回 lease (或 deny) |
| `RELEASE_REQUEST` | Client → Server | 归还 lease |
| `RENEW_REQUEST` | Client → Server | 续约 lease (Server 决定是否允许) |
| `RENEW_RESPONSE` | Server → Client | 返回续约结果 (新 expires_at_ns 或 deny) |
| `ERROR_RESPONSE` | Server → Client | Protocol 错误 (malformed / version mismatch / STALE_EPOCH 等) |

**签字后不可新增 message_kind** (V1 冻结). 走 V1.1 minor + ADR.

---

## 3. envelope (所有消息共享, 8 字段 + 1 个 per-kind payload)

### 3.1 完整 envelope

```json
{
  "protocol_version": "atlas-richie.cluster.token/v1",
  "message_kind": "ACQUIRE_REQUEST",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "instance_id": "550e8400-e29b-41d4-a716-446655440001",
  "startup_epoch": 0,
  "resource": "/api/v1/users",
  "permits": 1.0,
  "deadline_ns": 5000000,
  "client_requested_at": "2026-09-13T10:00:00.123456Z",
  "server_received_at": "2026-09-13T10:00:00.456789Z",
  "payload": { ... per-kind frozen object ... }
}
```

### 3.2 字段定义

| 字段 | 类型 | 必填 | 约束 | 写入方 |
| --- | --- | --- | --- | --- |
| `protocol_version` | string | ✅ | 常量 `"atlas-richie.cluster.token/v1"` | Client (REQUEST) / Server (RESPONSE) |
| `message_kind` | string | ✅ | V1 枚举见 §2 (6 个允许值) | 同上 |
| `request_id` | string | ✅ | UUID v4, Client 端生成, 用于 idempotency; 同一逻辑操作 retry 用同 request_id | Client |
| `instance_id` | string | ✅ | UUID, Client 实例唯一身份 | Client |
| `startup_epoch` | int64 | ✅ | 单调递增, 进程启动后从 0; 用于 Server fencing | Client |
| `resource` | string | ✅ | 资源名, ≤ 256 chars | Client (REQUEST) / Server (RESPONSE 回显) |
| `permits` | float64 | ✅ | 申请 / 授予 permit 数, ≥ 0.0 | 同上 |
| `deadline_ns` | int64 | ✅ | Client 端 deadline (相对当前时间纳秒); Server 超过此值不响应 | Client (REQUEST) |
| `client_requested_at` | string | ✅ | ISO 8601 UTC microsecond; **仅诊断** | Client (REQUEST) |
| `server_received_at` | string | ✅ | ISO 8601 UTC microsecond; Server 写入, 唯一服务端权威时间 | Server (REQUEST + RESPONSE) |
| `payload` | object | ✅ | per-kind frozen object, 见 §4 | 同上 |

### 3.3 字段序列化 (跟 M6.5.7 envelope 一致)

- 字符串: UTF-8 严格 JSON
- 数字: int64 / float64
- 时间: ISO 8601 UTC, `YYYY-MM-DDTHH:MM:SS.ffffffZ`
- UUID: 8-4-4-4-12 小写
- object 字段顺序: 不保证, 跨语言 consumer 按 key 解析

### 3.4 size 上限

单 envelope ≤ 8 KB (比 envelope V1 的 16 KB 小, 因为 token 协议更短).

---

## 4. payload schema (per-kind frozen)

### 4.1 `AcquireRequestPayload` (ACQUIRE_REQUEST)

```json
{
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123...",
  "priority": 0
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `rule_version_epoch` | int64 | ✅ | ≥ 0 |
| `rule_version_revision` | int64 | ✅ | ≥ 0 |
| `rule_version_checksum` | string | ✅ | `sha256:` + 64 hex chars |
| `priority` | int64 | ❌ | 0-9, 默认 0 (M6.3.x future use) |

### 4.2 `AcquireResponsePayload` (ACQUIRE_RESPONSE)

```json
{
  "decision": "REMOTE_GRANTED",
  "lease_id": "550e8400-e29b-41d4-a716-446655440002",
  "lease_expires_at": "2026-09-13T10:00:05.000000Z",
  "permits_granted": 1.0,
  "retry_after_ns": 0,
  "deny_reason": null
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `decision` | string | ✅ | V1: `REMOTE_GRANTED`, `DENIED` |
| `lease_id` | string | ✅ (REMOTE_GRANTED) | Server 生成的 opaque lease identity, UUID; 仅 Server 知道 mapping |
| `lease_expires_at` | string | ✅ (REMOTE_GRANTED) | ISO 8601 UTC; Server 决定 (Client **不**能伪造) |
| `permits_granted` | float64 | ✅ (REMOTE_GRANTED) | 实际授予 permit 数, ≤ request.permits |
| `retry_after_ns` | int64 | ❌ | Server 建议重试延迟 (区分 client-side vs server-side wait) |
| `deny_reason` | string | ✅ (DENIED) | V1: `QUEUE_FULL`, `RATE_LIMITED`, `SHUTTING_DOWN`, `STALE_EPOCH`, `UNKNOWN` |

### 4.3 `ReleaseRequestPayload` (RELEASE_REQUEST)

```json
{
  "lease_id": "550e8400-e29b-41d4-a716-446655440002",
  "permits_released": 1.0
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `lease_id` | string | ✅ | 跟 AcquireResponse 拿到的 lease_id 一致 |
| `permits_released` | float64 | ✅ | 通常 == AcquireResponse.permits_granted |

**Server 校验** `(lease_id, instance_id, startup_epoch)` 三元组; 不匹配 →
返回 `STALE_EPOCH` 错误码 (不抛异常, Client 忽略).

### 4.4 `RenewRequestPayload` (RENEW_REQUEST)

```json
{
  "lease_id": "550e8400-e29b-41d4-a716-446655440002",
  "extends_for_ns": 5000000
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `lease_id` | string | ✅ | 同上 |
| `extends_for_ns` | int64 | ✅ | 续约时长 (相对当前纳秒) |

### 4.5 `RenewResponsePayload` (RENEW_RESPONSE)

跟 `AcquireResponsePayload` 同样 schema (decision + lease_id + lease_expires_at
+ permits_granted + retry_after_ns + deny_reason), 但 `decision` 允许
`RENEWED` (续约成功) / `DENIED` (lease 已过期 / quota 满 / stale epoch).

### 4.6 `ErrorResponsePayload` (ERROR_RESPONSE)

```json
{
  "error_code": "PROTOCOL_VERSION_MISMATCH",
  "error_message": "expected atlas-richie.cluster.token/v1, got atlas-richie.cluster.token/v0"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `error_code` | string | ✅ | V1: `PROTOCOL_VERSION_MISMATCH`, `MALFORMED_ENVELOPE`, `UNKNOWN_MESSAGE_KIND`, `STALE_EPOCH`, `LEASE_NOT_FOUND`, `LEASE_EXPIRED`, `RESOURCE_NOT_CONFIGURED`, `SERVER_OVERLOADED`, `INTERNAL_ERROR` |
| `error_message` | string | ❌ | 脱敏 reason, ≤ 64 bytes; 严禁原始异常 / traceback / frame locals |

---

## 5. idempotency 语义

### 5.1 request_id 重用

- Client 端为每个 logical 操作生成唯一 `request_id` (UUID v4)
- **重试** (网络失败 / deadline 超时) 用**同** `request_id`
- Server 端短期 cache `(request_id, instance_id, startup_epoch) -> response` (5 min TTL)
- 命中 cache → 直接返回上次响应 (不再执行 Server 状态变更)
- 不命中 cache → 正常处理, 写 cache

### 5.2 cache TTL 选择

- 5 min TTL
- 必须 < lease 默认 TTL (M6.3.3 决策, 建议 30 s lease)
- 避免旧 release 请求错误命中 stale cache (lease 早已过期但 cache 还有)

### 5.3 跨进程一致性

- Server 多实例共享 cache (M6.3.x future 用 Redis; 1.0 进程内 cache + 文档化限制)
- 1.0 限制: 同 instance_id + startup_epoch 跨进程可能命中旧 cache, Client 端
  retry 用同 `request_id` 即可

---

## 6. 协议错误 (M6.3.1 决策)

| 错误码 | 触发 | Client 处理 |
| --- | --- | --- |
| `PROTOCOL_VERSION_MISMATCH` | `protocol_version` ≠ `"atlas-richie.cluster.token/v1"` | retry 无效, 升级 SDK; 标 ClusterFailurePolicy 决策 (FAIL_OPEN 放行 + warn; FAIL_CLOSED deny) |
| `MALFORMED_ENVELOPE` | 必填字段缺失 / 类型错 | retry 无效, log error; 同上 policy 决策 |
| `UNKNOWN_MESSAGE_KIND` | message_kind 不在 V1 6 个枚举中 | retry 无效, SDK 升级; 同上 |
| `STALE_EPOCH` | `(lease_id, instance_id, startup_epoch)` 不匹配 Server 记录 | log warn, **不**抛异常 (正常 race 现象) |
| `LEASE_NOT_FOUND` | release / renew 时 lease_id 不存在 | log warn, lease 已过期被清理 |
| `LEASE_EXPIRED` | renew 时 lease 已超过 expires_at | log warn, 需重新 acquire |
| `RESOURCE_NOT_CONFIGURED` | acquire 时 resource 未在 Server 配额配置 | 部署错误, fail-fast; 标 ClusterFailurePolicy |
| `SERVER_OVERLOADED` | Server 资源满, 返回 DENIED + deny_reason=SERVER_OVERLOADED | 按 ClusterFailurePolicy |
| `INTERNAL_ERROR` | Server 内部异常 (5xx) | retry 一次; 仍失败按 ClusterFailurePolicy |

**重试策略**: 同一 `request_id` 最多 retry 3 次 (exponential backoff, 50ms / 200ms / 1s); 超 3 次 → ClusterFailurePolicy 决策.

---

## 7. V1 兼容性矩阵

| 变更类型 | 是否破坏 V1 | 路径 | 约束 |
| --- | --- | --- | --- |
| 加 optional field (现有 message_kind 之外) | 否 | V1.1 minor + ADR | 旧 consumer 不读也兼容 |
| 加新 message_kind | 否 (V1 6 个仍合法) | V1.1 minor + ADR | 旧 consumer skip unknown kind |
| 加新 deny_reason / error_code | 否 (V1 4 + 9 个仍合法) | V1.1 minor + ADR | 旧 consumer skip unknown value |
| 改 message_kind 字符串值 | **是** | V2 major + 独立 ADR | 老 enum 永不再恢复 |
| 改 deny_reason 语义 | **是** | V2 major + 独立 ADR | 跨语言 SDK 必须更新 |
| 删字段 | **是** | V2 major + 独立 ADR | 旧 consumer 立刻 break |
| 改时间字段语义 (client_requested_at / server_received_at / lease_expires_at) | **是** | V2 major + 独立 ADR | 跨语言时区序列化 |
| 改 protocol_version 字符串 | **是** | V2 major + 独立 ADR | 路由层立刻 break |
| 改 size 上限 (> 8 KB) | **是** | V2 major + 独立 ADR | 跨语言 SDK 必查 |

---

## 8. 跨语言 contract test (1.0 publish 前 worker 实施)

| 测试 | 描述 |
| --- | --- |
| `python_acquire_request_roundtrip` | AcquireRequest JSON 序列化反序列化, 字段值完全一致 |
| `python_acquire_response_granted` | REMOTE_GRANTED 响应包含 lease_id + lease_expires_at + permits_granted |
| `python_acquire_response_denied` | DENIED 响应含 deny_reason, 无 lease_id |
| `python_idempotency_replay` | 同 request_id 重放, Server 返回同 response (5 min TTL 内) |
| `python_idempotency_different_resource` | 同 request_id 不同 resource → Server 当作新请求 (校验 instance_id 维度) |
| `python_stale_epoch_silent` | STALE_EPOCH 响应 Client 不抛异常, 仅 log warn |
| `python_lease_id_opaque` | Client 端 lease_id 不可伪造 (Server 校验通过) |
| `python_renew_extends` | RENEW_REQUEST 续约成功, lease_expires_at 延长 |
| `python_renew_expired` | 已过期 lease renew 返回 DENIED + LEASE_EXPIRED |
| `python_release_returns_permits` | RELEASE_REQUEST 释放 permit, Server 配额恢复 |
| `go_mock_acquire` | Go SDK mock 反序列化 AcquireRequest, 字段名 + 类型一致 |
| `java_mock_acquire` | Java SDK mock 反序列化 AcquireRequest, 字段名 + 类型一致 |

---

## 9. 后续工作 (1.0 publish 前, 1.x 末 worker / Mavis)

- M6.3.3 Server 资源分配状态机 (acquire / release / lease expiry / owner epoch fencing)
- M6.3.4 RemoteTokenService (Protocol 映射 + deadline + cancel + 鉴权 + 错误翻译)
- M6.3.5 独立 Server + Embedded Server 两种启动形态
- M6.3.7 contract suite 实施 (本节 §8 列表)
- `atlas-richie-contracts` 加 `atlas_richie.cluster.v1` 包 (Python 投影)
- 跨语言 SDK 实施 (Go / Java / Rust 至少 1 个其他语言 mock 跑同 spec)
- M6.4 双实例真实网络故障验收 (依赖 M6.3 实施)

---

## 10. sign-off

本 V1 spec 签字栏见 [`docs/process/M6.3-CLUSTER-TOKEN-DESIGN.md` §9](../M6.3-CLUSTER-TOKEN-DESIGN.md#9-sign-off-%E6%A0%8F-5-owner)。
5 owner 全部签字后, V1 冻结; 任何变更走 §7 兼容性矩阵。

---

**Document version**: 1.0 (frozen)
**Created by**: Mavis (mvs_cef3b0c9918e473f8de8ad4b42fef7ca)
**Last updated**: 2026-09-13
**Status**: V1 frozen, awaiting 5 owner sign-off
