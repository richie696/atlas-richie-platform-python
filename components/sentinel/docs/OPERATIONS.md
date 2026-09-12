# Atlas Richie Sentinel — Operations Guide

> 生产部署、监控、故障排查、性能调优的**运维边界**。本文档区分
> **Sentinel 控制** 和 **1.0 已知限制**,以及 1.x 升级路径。
>
> **Operational boundaries** for production: deployment, monitoring,
> troubleshooting, performance tuning. Distinguishes **Sentinel's
> control surface** from **1.0 known limits** and **1.x upgrade
> paths**.

---

## 1. 部署边界(中文)

### 1.1 进程模型:per-process 状态机

Sentinel **不是**分布式协调器。每个 Python 进程有独立的
`SentinelEngine`、独立的 `RuleRepository`、独立的指标计数器。

| 部署模式 | 行为 |
| -------- | ---- |
| 单进程 | 1 个 Engine / 1 个 Repository / 1 套指标 |
| 多 worker(uvicorn `--workers N` / gunicorn) | **N 个**独立 Engine / 各自 Repository / 各自指标 |
| 多机器(N pods × N workers) | **M × N** 个独立 Engine |

**绝对不要**做以下假设:

- ❌ "`threshold=5` × 2 workers = 集群 5 QPS"
  - 实际:每个 worker 各 5 QPS,集群总 QPS 上限 ≈ 2 × 5(如果负载均分)
- ❌ "Dashboard 看到的就是整个服务的流量"
  - 实际:Dashboard 看到的是**单 worker**;多 worker 需要外部 metrics
    aggregation

**Cluster 模式(1.x)** 才提供跨 worker / 跨进程的精确总量。当前 1.0
**不**提供,文档明确说明。

### 1.2 per-worker 资源命名建议

```python
# ❌ 错:把整个 worker 看成一个资源
resource = Resource("worker")

# ✅ 对:per-host + per-path 命名,让规则可以精细匹配
resource = Resource(f"{method} {host}{path}")
```

`source-file` 默认 `default_resource_name(scope)` 即此格式。

### 1.3 启动顺序

```python
# 1. Repository
repo = RuleRepository()

# 2. Source(可选)
source = FileRuleSource(path="/etc/sentinel/rules.json", poll_interval_sec=5.0)
source.start(repo)

# 3. Engine
engine = SentinelEngine()
engine.add_slot(FlowSlot(repository=repo))

# 4. Lifespan(ASGI / lifespan 协议)
async with engine:
    # 业务
    ...

# 5. 清理(反向)
source.stop()
```

`source.start(repo)` **不**阻塞;它启动后台轮询 task + 立即推一次
当前快照。

## 1. Deployment Boundaries (English)

### 1.1 Process model: per-process state machine

Sentinel is **not** a distributed coordinator. Each Python process has
its own Engine / Repository / metrics.

| Mode | Behavior |
| ---- | -------- |
| Single process | 1 Engine / 1 Repository / 1 metrics |
| Multi-worker (uvicorn `--workers N` / gunicorn) | **N** independent Engine / Repository / metrics |
| Multi-machine (N pods × N workers) | **M × N** independent Engine |

**Never assume**:

- ❌ "`threshold=5` × 2 workers = cluster 5 QPS"
  - Reality: each worker has its own 5 QPS; cluster ceiling ≈ 2 × 5
    (if load is balanced).
- ❌ "Dashboard shows total cluster traffic"
  - Reality: Dashboard is **single-worker**; multi-worker aggregation
    requires external metrics.

**Cluster mode (1.x)** provides cross-worker / cross-process exact
totals. 1.0 does **not**.

---

## 2. 监控指标(Metrics)(中文)

### 2.1 内置指标(主包,无 3rd-party)

Engine 内部维护:

- `engine.in_flight` — 当前 in-flight 数量
- `engine.last_outcome` — 最近一次 outcome
- `engine.last_error` — 最近一次 swallow 的 error
- `engine.state` — `CREATED` / `READY` / `SHUTTING_DOWN` / `SHUTDOWN` / `FAILED`

通过 `sentinel-dashboard` 暴露为 REST endpoint:
- `GET /metrics` — Prometheus 文本格式
- `GET /resources` — 已知资源 + 命中规则
- `GET /health` — liveness / readiness

### 2.2 外部 metrics(用户责任)

主包**不**集成 `prometheus-client` / `opentelemetry` / `statsd`。
如需:

- 用 `sentinel-dashboard` 写好的 Prometheus exporter 1.x
- 或自己包装 `engine.last_outcome` 写到自己的 metrics backend

### 2.3 告警建议

| 指标 | 告警阈值(参考) | 含义 |
| ---- | -------------- | ---- |
| `engine.state == FAILED` | 立即 | Slot 抛非 Sentinel 异常 + FAIL_FAST 触发,Engine 进入不可用 |
| `engine.last_error` 频率 | 持续 1 分钟 > 0 | 内部 swallow 的错误,可能是某 Slot 异常 |
| `in_flight` 接近 0 | 持续 5 分钟 | 可能上游熔断 / 流量下降 |
| `BLOCKED` outcome 频率 | 取决于业务 | 限流触发,正常;但**激增**需要看规则 |

## 2. Monitoring (English)

### 2.1 Built-in (main package, no 3rd-party)

Engine maintains:

- `engine.in_flight` — current in-flight count
- `engine.last_outcome` — most recent outcome
- `engine.last_error` — most recent swallowed error
- `engine.state` — `CREATED` / `READY` / `SHUTTING_DOWN` / `SHUTDOWN` / `FAILED`

Exposed via `sentinel-dashboard` REST endpoints.

### 2.2 External metrics (caller's responsibility)

Main package does **not** integrate `prometheus-client` /
`opentelemetry` / `statsd`. Use `sentinel-dashboard` (Prometheus
exporter in 1.x) or wrap `engine.last_outcome` yourself.

### 2.3 Alerting

(See table above.)

---

## 3. 故障排查(中文)

### 3.1 Engine 报 `state == FAILED`

**原因**:`fail_safe = FAIL_FAST` 时,Slot 抛非 Sentinel 异常。

**修复**:

```python
from atlas_richie.sentinel.engine.sentinel_engine import FailSafe

engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
# 或
engine = SentinelEngine(fail_safe=FailSafe.FAIL_OPEN)
```

| FailSafe | 行为 | 适用场景 |
| -------- | ---- | -------- |
| `FAIL_CLOSED` | Slot 异常 → 拒绝请求(默认) | 严格保护 |
| `FAIL_OPEN` | Slot 异常 → 放行(记录 last_error) | 优雅降级 |
| `FAIL_FAST` | Slot 异常 → 跳 FAILED 状态,后续 entry 拒绝 | Debug / 严格门禁 |

### 3.2 5xx 触发熔断,但 4xx 不应该触发

**根因**:HTTPX 5xx **不**自动抛 `HTTPStatusError`;只在 `raise_for_status()`
时抛。`DefaultOutcomeClassifier` 读 `response.status_code`,**不**
调 `raise_for_status`。

如果看到 4xx 触发熔断,检查:

- 自定义 `OutcomeClassifier` 是否把 4xx 误判为 FAILED
- 是否用了 `httpx.AsyncClient(..., transport=...)` 而 transport 中
  调用了 `raise_for_status()`

### 3.3 限流不准

**根因 1**:规则配置错误(threshold = 0 / 选错了 grade)。
**根因 2**:SlidingWindow 窗口太短,数据抖动大。
**根因 3**:`Source` 没把最新规则推下来 — 看 `repo.last_version` 是否
有更新。

```python
print(repo.last_version)  # None = 没规则
print(repo.current_index.find("orders-api"))  # 命中的 rule 列表
```

### 3.4 Engine 卡死 / 不响应

**根因**:`async with engine.entry(...)` 内部 await 卡住(通常因为
下游 I/O hang)。

**修复**:

1. 给 entry 加 timeout(用 `asyncio.wait_for` 包业务代码)
2. 用 `Bulkhead` 限制并发,防 resource exhaustion
3. 监控 `engine.in_flight`;持续 > 0 视为异常

### 3.5 ContextVar 错误("Token was created in a different Context")

**根因**:并发 entry 共享同一个 `_context_token` 字段(已在 M1.6 修复,
token 改存 `EntryLease._context_token` per-entry)。

**若仍然出现**:升级到 1.0+;1.0 已修复。

### 3.6 ASGI middleware 不响应 / 卡住

**根因**:SentinelASGIMiddleware 不会在下游 app 卡住时主动断开 —
透传 ASGI 协议。

**修复**:用 `Bulkhead` 限制并发 + `BulkheadFull` 触发 503。

## 3. Troubleshooting (English)

### 3.1 Engine `state == FAILED`

**Cause**: `fail_safe = FAIL_FAST` triggers when a Slot raises a
non-Sentinel exception.

**Fix**: switch to `FAIL_CLOSED` (default, reject) or `FAIL_OPEN`
(admit + log).

### 3.2 5xx trips CB but 4xx should not

**Root cause**: HTTPX 5xx does **not** auto-raise. Classifier reads
`status_code`, never calls `raise_for_status()`. If 4xx trips CB,
check: custom classifier / transport that called `raise_for_status()`.

### 3.3 Rate limit inaccurate

(See code block above for diagnosis.)

### 3.4 Engine hangs

Use `asyncio.wait_for` for timeouts + `Bulkhead` to cap concurrency;
monitor `engine.in_flight`.

### 3.5 ContextVar error

Fixed in M1.6 (token moved to `EntryLease`). Upgrade to 1.0+.

### 3.6 ASGI middleware hang

`SentinelASGIMiddleware` is a pass-through; downstream hangs propagate.
Use `Bulkhead` for backpressure.

---

## 4. 性能调优(中文)

### 4.1 测量,不要猜

```bash
cd components/sentinel/sentinel
source .venv/bin/activate

# 数据采集(无 assert)
RUN_SEN_PERF=1 pytest tests/benchmark/test_sen_perf.py -v -s

# 5 场景:无规则 / 1 FlowRule / 5 规则 / 1000 索引命中 / 1000 索引未命中
# 输出 commit / Python / OS / CPU / p50 / p95 / p99 / max / mean
```

基线见 `docs/acceptance/R-SENTINEL-M1-baseline.md`。**不要**写
"p99 < 1ms" 之类的硬阈值。

### 4.2 已知热路径

| 路径 | 开销 | 优化 |
| ---- | ---- | ---- |
| `engine.entry()` | async context manager 进出 + contextvars bind/reset | **不优化**,已 ~20µs p50 |
| `RuleIndex.find()` | 字典扫描 O(n) | 1.x: 改 trie / bloom filter |
| `FlowSlot` 计数 | in-memory atomic | 1.x: lock-free + thread-local 聚合 |
| `MetricRegistry` 采样 | 滑动窗口循环 | 1.x: 增量式 snapshot |

### 4.3 GC 调优

Sentinel 主包用 frozen dataclass + slots,**不**产生大量短命对象。
在 10 分钟 soak 中,5 场景 × 5000 entry ≈ 25k entry 无崩溃(基线
数据)。

### 4.4 别优化 1.0 不需要的部分

- 50 ms p99 已经很好,不要去搞 SIMD
- 内存 10MB 以下的占用不需要 Pool
- SlidingWindow 4 桶足够,不要 16 / 64 桶

## 4. Performance Tuning (English)

### 4.1 Measure, don't guess

Run the perf baseline (no asserts). Compare to
`docs/acceptance/R-SENTINEL-M1-baseline.md`. **Do not** write hard
thresholds.

### 4.2 Known hot paths

(See table above.)

### 4.3 GC tuning

Main package uses frozen dataclass + slots; minimal short-lived
object churn.

### 4.4 Don't optimize what 1.0 doesn't need

50ms p99 is fine; < 10MB memory doesn't need Pool; 4-bucket
SlidingWindow is enough.

---

## 5. 安全边界(中文)

### 5.1 Dashboard 认证

`sentinel-dashboard` 默认:

- **只**绑 `127.0.0.1`
- **要求** `ADMIN_TOKEN` 环境变量
- **审计日志**记录每个 admin 操作

**禁止**把 Dashboard 暴露到公网(0.0.0.0 / 公开 IP);如需,前置
nginx + bearer token + 限流。

### 5.2 凭证脱敏

Sentinel **不**在 metrics / 日志中包含:
- HTTP body
- HTTP header 的 `Authorization` / `Cookie`
- DB 连接串

`DefaultOutcomeClassifier` 只读 `response.status_code`,**不**读 body
/ header。

### 5.3 错误信息

`SentinelBlockedError.message` 包含规则描述(rule_id + 原因),**不**
包含用户数据。

### 5.4 Python 安全

- 3.12+ 要求(3.11 及以下 1.0 不支持)
- 锁定依赖:`uv lock` 生成 lockfile
- CVE 监控:`pip-audit` 集成到 CI(1.x)

## 5. Security Boundaries (English)

### 5.1 Dashboard auth

`Sentinel-dashboard` defaults:

- **Loopback only** (`127.0.0.1`).
- **Requires** `ADMIN_TOKEN` env var.
- **Audit log** records each admin op.

Do **not** expose Dashboard to public networks without an nginx +
bearer-token + rate-limit front.

### 5.2 Credential scrubbing

Sentinel does **not** include in metrics / logs:

- HTTP body
- `Authorization` / `Cookie` headers
- DB connection strings

`DefaultOutcomeClassifier` reads only `response.status_code`.

### 5.3 Error messages

`SentinelBlockedError.message` contains rule description (rule_id +
reason), no user data.

### 5.4 Python security

- 3.12+ required (3.11 and below are unsupported in 1.0)
- Locked deps: `uv lock`
- CVE monitoring: `pip-audit` in CI (1.x)

---

## 6. 升级路径(中文)

### 6.1 1.0 → 1.x

**主包**:1.0 → 1.x **不 breaking**(semver 严格)。升级只换
`atlas-richie-sentinel>=1.0,<2.0`。

**Adapter / Source / Dashboard wheel**:每个独立升级。CHANGELOG 看
每个 wheel 自己的版本。

### 6.2 集群模式(1.x)

1.0 的 per-process 状态机不够用时(跨 worker 精确限流、跨机器
metrics aggregation),升级到 1.x 的 Cluster 模式:

```python
# 1.x
from atlas_richie.sentinel.cluster import ClusterTokenClient

client = ClusterTokenClient(...)
flow_slot = FlowSlot(repository=repo, token_client=client)
```

**不是** 1.0 的功能,需要切到 1.x 系列 wheel。

### 6.3 0.x → 1.0(无)

1.0 是**第一个**正式发布;0.x 标记 alpha,**不**保证 1.0 兼容。

## 6. Upgrade Path (English)

### 6.1 1.0 → 1.x

**Main package**: 1.0 → 1.x is **non-breaking** (strict semver).
Upgrade by bumping `atlas-richie-sentinel>=1.0,<2.0`.

**Adapter / Source / Dashboard wheels**: each upgrades independently.
Check each wheel's CHANGELOG.

### 6.2 Cluster mode (1.x)

When 1.0's per-process state machine is insufficient (cross-worker
exact limits, cross-machine metrics aggregation), upgrade to 1.x
Cluster mode.

**Not** a 1.0 feature; requires 1.x series wheel.

### 6.3 0.x → 1.0 (n/a)

1.0 is the **first** stable release; 0.x marked alpha; no compat
guarantee to 1.0.

---

## 7. 升级 / 故障排查 Runbook(中文)

```bash
# 1. 看 Engine 状态
python -c "
from atlas_richie.sentinel.engine import SentinelEngine
import asyncio
async def main():
    async with SentinelEngine() as e:
        print(f'state: {e.state.value}')
        print(f'last_outcome: {e.last_outcome}')
        print(f'last_error: {e.last_error}')
        print(f'in_flight: {e.in_flight}')
asyncio.run(main())
"

# 2. 跑 5 场景 perf baseline
RUN_SEN_PERF=1 pytest tests/benchmark/test_sen_perf.py -v -s

# 3. 看版本一致性
python tools/release/check_version_consistency.py --name atlas-richie-sentinel
```

## 7. Operations Runbook (English)

```bash
# 1. Inspect Engine state (script above)

# 2. Perf baseline
RUN_SEN_PERF=1 pytest tests/benchmark/test_sen_perf.py -v -s

# 3. Version consistency
python tools/release/check_version_consistency.py --name atlas-richie-sentinel
```
