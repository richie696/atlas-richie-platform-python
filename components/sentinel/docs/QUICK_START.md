# Atlas Richie Sentinel — Quick Start

> 5 分钟上手 `atlas-richie-sentinel`。主 wheel 零三方依赖;
> 出站 HTTP 集成走 `sentinel-adapter-httpx`,ASGI 集成走
> `sentinel-adapter-asgi`,Dashboard 走 `sentinel-dashboard`。
>
> Get up and running with `atlas-richie-sentinel` in 5 minutes. The
> main wheel has zero third-party dependencies. Outbound HTTPX
> integration lives in `sentinel-adapter-httpx`; ASGI integration
> in `sentinel-adapter-asgi`; Dashboard in `sentinel-dashboard`.

---

## 1. Install

```bash
# 主 wheel (零依赖)
pip install atlas-richie-sentinel

# 集成 wheel(按需)
pip install atlas-richie-sentinel-adapter-asgi     # FastAPI / Starlette / 任意 ASGI 3.0
pip install atlas-richie-sentinel-adapter-httpx    # httpx 0.27+
pip install atlas-richie-sentinel-source-file      # JSON / YAML 文件热加载
pip install atlas-richie-sentinel-dashboard        # 控制面 / 指标
```

要求 Python 3.12+。

## 2. 30 秒跑通(中文)

```python
import asyncio
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.model.resource import Resource

async def main():
    async with SentinelEngine() as engine:
        # 没有规则时,所有 entry 都通过
        async with engine.entry(Resource("hello-world")):
            print("请求通过")

asyncio.run(main())
```

`SentinelEngine` 是 async context manager;`engine.entry(resource)`
返回另一个 async context manager。**不需要**任何规则也可以跑,
只是没有流控。

## 3. 30 秒跑通(English)

```python
import asyncio
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.model.resource import Resource

async def main():
    async with SentinelEngine() as engine:
        # Without rules, every entry is admitted.
        async with engine.entry(Resource("hello-world")):
            print("request admitted")

asyncio.run(main())
```

`SentinelEngine` is an async context manager; `engine.entry(resource)`
returns another async context manager. **No rules are required** to
run — the engine just admits everything.

---

## 4. 加一条 FlowRule(中文)

```python
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.flow import FlowRule, FlowGrade
from atlas_richie.sentinel.slots.flow import FlowSlot
from atlas_richie.sentinel.rules.selector import ResourceSelector

# 1. 准备规则
rule = FlowRule(
    rule_id="orders-qps-5",
    resource_selector=ResourceSelector.exact("orders"),
    grade=FlowGrade.QPS,
    threshold=5.0,
)

# 2. 推送到仓库
repo = RuleRepository()
snapshot = RuleSnapshot(
    version=RuleVersion(
        epoch=1, revision=0,
        checksum=RuleVersion.compute_checksum({"rules": 1}),
    ),
    rules={rule.rule_id: rule},
    applied_at_ns=0,
    source_id="manual",
)
repo.apply_snapshot(snapshot)

# 3. 启动引擎 + 装载 FlowSlot
engine = SentinelEngine()
engine.add_slot(FlowSlot(repository=repo))

async with engine:
    for _ in range(10):
        try:
            async with engine.entry(Resource("orders")):
                print("通过")
        except SentinelBlockedError as e:
            print(f"被限流: {e.block_reason}")
```

## 4. Add a FlowRule (English)

```python
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.flow import FlowRule, FlowGrade
from atlas_richie.sentinel.slots.flow import FlowSlot
from atlas_richie.sentinel.rules.selector import ResourceSelector

# 1. Build the rule
rule = FlowRule(
    rule_id="orders-qps-5",
    resource_selector=ResourceSelector.exact("orders"),
    grade=FlowGrade.QPS,
    threshold=5.0,
)

# 2. Push to repository
repo = RuleRepository()
snapshot = RuleSnapshot(
    version=RuleVersion(
        epoch=1, revision=0,
        checksum=RuleVersion.compute_checksum({"rules": 1}),
    ),
    rules={rule.rule_id: rule},
    applied_at_ns=0,
    source_id="manual",
)
repo.apply_snapshot(snapshot)

# 3. Start the engine + install FlowSlot
engine = SentinelEngine()
engine.add_slot(FlowSlot(repository=repo))

async with engine:
    for _ in range(10):
        try:
            async with engine.entry(Resource("orders")):
                print("admitted")
        except SentinelBlockedError as e:
            print(f"blocked: {e.block_reason}")
```

---

## 5. ASGI 集成(中文)

```python
from fastapi import FastAPI
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.slots.flow import FlowSlot
from atlas_richie.sentinel_adapter_asgi import SentinelASGIMiddleware

app = FastAPI()

@app.get("/orders")
async def orders():
    return {"ok": True}

# 包一层
async def lifespan(app):
    engine = SentinelEngine()
    engine.add_slot(FlowSlot(repository=...))
    yield
    await engine.aclose()

# uvicorn main:app --workers 4
```

`SentinelASGIMiddleware` 是纯 ASGI 3.0,不依赖 Starlette / FastAPI。

## 5. ASGI Integration (English)

```python
from fastapi import FastAPI
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.slots.flow import FlowSlot
from atlas_richie.sentinel_adapter_asgi import SentinelASGIMiddleware

app = FastAPI()

@app.get("/orders")
async def orders():
    return {"ok": True}

# Wrap the app
async def lifespan(app):
    engine = SentinelEngine()
    engine.add_slot(FlowSlot(repository=...))
    yield
    await engine.aclose()

# uvicorn main:app --workers 4
```

`SentinelASGIMiddleware` is a pure ASGI 3.0 callable; it does **not**
depend on Starlette / FastAPI.

---

## 6. HTTPX 出站(中文)

```python
import httpx
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.slots.flow import FlowSlot
from atlas_richie.sentinel_adapter_httpx import SentinelAsyncTransport

engine = SentinelEngine()
engine.add_slot(FlowSlot(repository=...))

transport = SentinelAsyncTransport(
    engine=engine,
    flow_slot=engine.chain[0],  # 见下文
    inner_transport=httpx.AsyncHTTPTransport(),
)

async with httpx.AsyncClient(transport=transport) as client:
    response = await client.get("https://api.example.com/orders")
```

**默认不重试**(PLANNING §M4.5);如需重试,显式 `RetryExecutor` + `RetryPolicy`
+ `IdempotencyKey` 组合。

## 6. HTTPX Outbound (English)

```python
import httpx
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.slots.flow import FlowSlot
from atlas_richie.sentinel_adapter_httpx import SentinelAsyncTransport

engine = SentinelEngine()
engine.add_slot(FlowSlot(repository=...))

transport = SentinelAsyncTransport(
    engine=engine,
    flow_slot=engine.chain[0],  # see below
    inner_transport=httpx.AsyncHTTPTransport(),
)

async with httpx.AsyncClient(transport=transport) as client:
    response = await client.get("https://api.example.com/orders")
```

**No retry by default** (PLANNING §M4.5); to retry, explicitly compose
`RetryExecutor` + `RetryPolicy` + `IdempotencyKey`.

---

## 7. 进一步阅读(中文)

- 规则手册 → `docs/RULE_REFERENCE.md`
- 扩展开发指南 → `docs/EXTENSION_GUIDE.md`
- 运维边界 → `docs/OPERATIONS.md`
- 设计总览 → `docs/DESIGN.md`
- 实施路线 → `docs/PLANNING.md`

## 7. Further Reading (English)

- Rule reference → `docs/RULE_REFERENCE.md`
- Extension guide → `docs/EXTENSION_GUIDE.md`
- Operations guide → `docs/OPERATIONS.md`
- Design overview → `docs/DESIGN.md`
- Roadmap → `docs/PLANNING.md`
