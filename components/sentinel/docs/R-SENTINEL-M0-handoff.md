# R-SENTINEL-M0 实施交接

> **状态**: M0 完成,准备进入 M1 (Engine / 领域模型)
> **Author**: Mavis (root session 2026-09-13)
> **Range**: M0.4 ~ M0.11 + M0.9 + M0 Exit
> **HEAD**: 见 `git log --oneline | head -10`

## M0 Exit 验收 (8/8 通过)

| # | 验收项 | 证据 |
|---|---|---|
| 1 | 主 wheel 零 3rd-party | `components/sentinel/sentinel/pyproject.toml` `dependencies = []` |
| 2 | 8 原语迁完 | `primitives/{retry,circuit_breaker,bulkhead,idempotency,token_bucket,clock,random_source}.py` + `errors/__init__.py` |
| 3 | 67 测试通过 | `pytest components/sentinel/sentinel/tests/ -q` → `67 passed` (干净 venv) |
| 4 | 仓库无双份代码实现 | `grep -rE "^from atlas_richie\.resilience\|^import atlas_richie\.resilience" --include="*.py" --include="*.toml"` = 0 行 |
| 5 | `components/resilience/` 完整删除 | `ls components/` 无 resilience/ |
| 6 | `git diff --check` 干净 | 最近 10 commit 范围 diff 无冲突标记 |
| 7 | `uv lock` 干净 | 移除 `atlas-richie-resilience` + `aiolimiter` + `stamina` + `tenacity`,加入 `atlas-richie-sentinel` |
| 8 | HANDOFF.md "当前架构" 段无 resilience 引用 | `awk` 段内 grep = 0;`## 15. R-220` 段历史事实保留 |

## M0 commit 链 (8 个)

```
21e1ad2 M0.9: 删 components/resilience + 同步 HANDOFF + uv lock
9170640 M0.11: tools/release/check_version_consistency.py + RELEASE.md
56b518d M0.10: git mv 7 test_*.py + 改 import + 67/67 测试通过
c8d3566 M0.8.1: tools/release/check_sentinel_namespace.py
d30d1b3 M0.8: foundation/platform 换 dep
(已合并 M0.6 到 M0.7/M0.7.1 一次性 commit)
06c07ed M0.5 + M0.5-A + M0.7.1: 迁源码 + 改异常层 + 集中 re-export
d0f9f60 M0.4: 创建 atlas-richie-sentinel 主 wheel
```

## 关键决策摘要

- **包名**: `atlas-richie-sentinel` (单主 wheel,内部模块 `atlas_richie.sentinel`)
- **零依赖**: 主 wheel `dependencies = []`,不依赖 contracts / stamina / aiolimiter
- **唯一异常层**: `SentinelError(Exception)` → `ResilienceError(SentinelError)` → 5 原语异常
- **公开 API**: 保留 `RetryPolicy` / `RetryExecutor` / `IdempotencyKey` 三实现 / `CircuitBreaker` / `TokenBucket` / `Bulkhead` / `Clock` 三实现 / `RandomSource` 三实现 / `system_sleep`;**不**存在 `Retry`
- **版本号唯一源**: `pyproject.toml [project] version = "0.2.0"`;运行时走 PEP 562 `__getattr__` 懒加载 `importlib.metadata.version()`
- **发布门禁**: 专用目录 + `--clear --no-create-gitignore` + `check_version_consistency.py` (4 项: 数量/文件名/METADATA/PKG-INFO)
- **命名空间所有权**: `atlas_richie.sentinel` 由主 wheel 独占;`check_sentinel_namespace.py` 防扩展 wheel 污染

## 下一步 (M1)

按 PLANNING.md §21:
- M1.x: 领域模型 (`Resource` / `Entry` / `Outcome` / `Context`)
- M1.x: `Engine` 异步上下文管理器 + `SlotChain` 责任链
- M1.x: 5 类规则 (Flow / Degrade / ParamFlow / Authority / System)
- M1.x: 单元 + 边界 + 状态 + 并发 + 组合测试 (SEN-CORE-001 / SEN-CB-001 / SEN-FLOW-001 / SEN-PARAM-001 / SEN-SYSTEM-001 / SEN-AUTH-001)
- M1.x: `SentinelBlockedError` 独立分支 (M0.5-A 预留, M1.x 实现)
- M1.x: `TokenService` Protocol + `LocalTokenService` 默认 (M2.7 前置)

约束提醒:
- 主 wheel 持续零 3rd-party (M1+ 仍不能拉 httpx / starlette / pydantic 到主包)
- 5 类规则共享类型,放主 wheel,不分 5 个子 wheel
- 异常分层严格: `SentinelBlockedError` 与 `ResilienceError` 互不为子类

## 已知遗留

- R-240 aliyun-kms yanked dep (`alibabacloud-darabonba-array==0.1.0`) 仍卡 `prepare_wheelhouse.py` → `verify_isolated_wheels.py` 全平台验证;与 Sentinel 无关,后续单独处理
- 7 个 sentinel 扩展 wheel (asgi/httpx/source-file/source-nacos/source-redis/dashboard/cluster) 仍为 skeleton,M1+ 实施时实现
- 历史 handoff 文档 (`docs/acceptance/R-233*.md`) 保留 `atlas-richie-resilience` 事实记录,符合"历史事实保留"原则
