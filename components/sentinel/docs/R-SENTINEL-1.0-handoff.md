# R-SENTINEL 1.0 Release Handoff

> **Status**: M0-M5 全部落地; 5 wheel 独立 build 成功; 一致性检查通过; 67 测试过
> **Date**: 2026-09-13
> **Range**: M0.4 → M5.6
> **HEAD**: 见 `git log --oneline | head -25`

## 1.0 范围

主包 + 4 扩展 wheel (PLANNING §M5.6 锁定为"5 个已实现 wheel"):

| Wheel | Name | 依赖 |
|---|---|---|
| 主包 | `atlas-richie-sentinel` | 0 3rd-party |
| 扩展 | `atlas-richie-sentinel-source-file` | 主包 + (pyyaml optional) |
| 扩展 | `atlas-richie-sentinel-adapter-asgi` | 主包 (pure stdlib) |
| 扩展 | `atlas-richie-sentinel-adapter-httpx` | 主包 + httpx |
| 扩展 | `atlas-richie-sentinel-dashboard` | 主包 (stdlib http.server) |

**1.x 延后 (M6+)**: sentinel-source-nacos / sentinel-source-redis /
sentinel-cluster / sentinel-observability。

## M0-M5 验收 (全过)

- **M0 完整闭环** (10 commit, 8/8 Exit 验收): 主 wheel 0 3rd-party
  + 8 原语迁完 + 67 测试过 + 仓库无双份代码实现。
- **M1 完整闭环** (5 子项, 5 验证脚本): model/ 6 文件 + errors/ 拆分
  + Engine (6 状态机) + SlotChain + SlidingWindow + MetricRegistry
  + ResourceRegistry + RuleSnapshot + Repository + Selector + Index
  + 8 步 apply 流程。
- **M2 完整闭环** (7 子项, 12/12 验证): 5 类规则 (Flow/Degrade/ParamFlow
  /Authority/System) + TokenService + LocalTokenService + 强制不变量
  + SystemMetricSampler + OriginResolver + 5 规则组合测试。
- **M3-M5 完整闭环** (18 子项, 6/6 验证): FileRuleSource (JSON/YAML
  hot reload) + ASGI Middleware (pure stdlib) + HTTPX Transport
  (OutboundConcurrencyGuard, 不读 httpcore 私有) + Dashboard
  (loopback + read-only 默认 + admin token + audit log) +
  check_version_consistency.py 扩展支持 5 wheel。

## 1.0 发布门禁 (PLANNING §M0.4 / §M5.4)

- **5 wheel 独立 build** — 全部成功:
  ```
  Successfully built /tmp/wheels-final/sentinel/atlas_richie_sentinel-0.2.0.{whl,tar.gz}
  Successfully built /tmp/wheels-final/sentinel-adapter-asgi/atlas_richie_sentinel_adapter_asgi-0.2.0.{whl,tar.gz}
  Successfully built /tmp/wheels-final/sentinel-source-file/atlas_richie_sentinel_source_file-0.2.0.{whl,tar.gz}
  Successfully built /tmp/wheels-final/sentinel-adapter-httpx/atlas_richie_sentinel_adapter_httpx-0.2.0.{whl,tar.gz}
  Successfully built /tmp/wheels-final/sentinel-dashboard/atlas_richie_sentinel_dashboard-0.2.0.{whl,tar.gz}
  ```
- **版本一致性** — 全部 OK (4 处 Name + 3 处 Version):
  ```
  OK: name='atlas-richie-sentinel' version='0.2.0' consistent
  OK: name='atlas-richie-sentinel-adapter-asgi' version='0.2.0' consistent
  OK: name='atlas-richie-sentinel-source-file' version='0.2.0' consistent
  OK: name='atlas-richie-sentinel-adapter-httpx' version='0.2.0' consistent
  OK: name='atlas-richie-sentinel-dashboard' version='0.2.0' consistent
  ```
- **测试** — 67 passed (主包 primitives + engine + metrics + rules +
  slots + ports 集成)。
- **PEP 625 slug 校验** — wheel + sdist 文件名规范化正确 (下划线)。

## 主包内部结构

```
src/atlas_richie/sentinel/
├── __init__.py            # PEP 562 __getattr__ 懒加载 __version__
├── model/                 # 6: Resource, SentinelContext, InvocationArguments,
│                          #    Outcome, SlotLease+NoopSlotLease, BlockReason/RuleMatchKind/EngineState
├── errors/                # 5: base.py (SentinelError 根)
│                          #    __init__.py (ResilienceError + 5 M0 原语)
│                          #    block.py (SentinelBlockedError + 5 子类, 单继承不复用)
│                          #    configuration.py (SentinelConfigurationError)
│                          #    lifecycle.py (SentinelLifecycleError + RuleSnapshotError)
├── primitives/            # 8: retry, circuit_breaker, bulkhead, idempotency,
│                          #    token_bucket, clock, random_source, + __init__
├── engine/                # 4: sentinel_engine (6 状态机 async ctx mgr),
│                          #    slot, slot_chain, entry
│                          #    + resource_registry
├── metrics/               # 4: sliding_window (stdlib ring buffer),
│                          #    registry, snapshot, sink
├── rules/                 # 4: snapshot, selector, index, repository
│                          #    + flow, degrade, param_flow, system, authority (M2 5 类)
├── slots/                 # 5: flow, degrade, param_flow, system, authority (M2)
├── source/                # 1: rule_source (M3.2 FileRuleSource)
└── ports/                 # 2: system_metric_sampler, token
```

## 关键设计纪律 (从 review 学到)

1. **唯一异常层**: `SentinelError(Exception)` 根; `ResilienceError` 是
   原语 throw 分支; `SentinelBlockedError` 是 Engine 拒绝独立分支;
   二者互不为子类。
2. **单继承不复用**: `CircuitBlocked` 不是 `CircuitOpen` 子类, 复制
   字段(但保持类型独立)。
3. **Token 强制不变量**: `DENIED` 必有 `deny_reason + token=None`; 3 种
   放行必有 `token + deny_reason=None`。
4. **零 3rd-party 主包**: 主 wheel `dependencies = []`; 扩展 wheel 仅
   依赖主包 (+ 必要的 stdlib 之外的依赖如 httpx)。
5. **M1.5 ResourceRegistry + M0.6 check_version_consistency.py**:
   专用目录 + `--clear --no-create-gitignore` + 4 处 Name + 3 处
   Version 严格一致。
6. **PEP 562 懒加载 `__version__`**: 从 distribution metadata 读; 避免
   install 前 import 失败。
7. **HANDOFF.md 同步**: `## 2. 总体架构决策` 段加
   `<!-- SENTINEL_HANDOFF_CURRENT_ARCH_START -->` / `END -->` 注释
   标记; `grep` 段内 0 行 resilience 引用, 历史段保留。
8. **失败 fail-safe**: `SystemMetricSampler.degraded=True` → 跳过
   阈值检查; `DegradeSlot.force_reset` 替代 force_open/close
   (M0 CircuitBreaker 状态机不支持)。
9. **不读 httpcore 私有 API**: HTTPX Adapter 只走
   `AsyncBaseTransport.handle_async_request` / `aclose` 公开 API。
10. **不重试默认**: HTTPX Adapter 不知道哪些是幂等的; 留给
    httpx-retry 等专用中间件。

## 已知遗留 (1.x)

- M6+ (1.x 延后): sentinel-source-nacos + sentinel-source-redis +
  sentinel-cluster + sentinel-observability (cluster 模式 + 远端
  拉取 + 指标导出)
- M5.3 / M5.5 文档 (Quick Start / CHANGELOG / 迁移说明 / SBOM) —
  1.0 实际发布时由维护者撰写; 本文档为 R-### 交接基线
- M5.6 实际 `uv publish` — 需要 RICHIE 显式触发; 流程已就绪 (专用
  目录 + check_version_consistency.py 门禁 + uv publish glob 命令)
- R-240 aliyun-kms yanked dep (`alibabacloud-darabonba-array==0.1.0`)
  仍卡 `prepare_wheelhouse.py` 全平台验证; 与 Sentinel 无关
- M3.5 流式响应/断连/lifespan 完整测试套件 (M5.4 的 isolated
  wheel 门禁已就绪, 但 Python 3.12/3.13/3.14 全 matrix + 多
  worker soak 未跑; 留 1.0 前最后一轮)
- 性能基线: M1 收集原始数据, 1.0 不设硬性阈值 (<100ms /
  p99<1ms); 真实下游场景验证后再审
