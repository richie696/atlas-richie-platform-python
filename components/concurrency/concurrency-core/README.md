# atlas-richie-concurrency-core

纯并发算法，零第三方依赖。对位 Java `atlas-richie-concurrency` 中可移植的
高价值子集（sentinel primitives 已覆盖熔断/异步重试/令牌桶，这里补其缺口）。

| 组件 | 说明 |
|---|---|
| `Retryer` | **同步**重试：指数退避封顶 + 可选 jitter + retryOn 类型过滤 + fallback |
| `Debouncer` | 去抖：trigger 重置计时、flush 立即执行、cancel 丢弃、is_pending 查询 |
| `NamedRegistry` | 命名注册表：get_or_create/find/remove/keys/size/clear，使熔断器/限流器可按资源复用 |

**不移植**（JVM 特有，CPython 无等价物）：`DynamicExecutor` 的
corePoolSize/maximumPoolSize/有界队列/拒绝策略与运行时 resize、
`VirtualThreadFactory`、`ThreadPoolConfigRefresher`（Spring 环境绑定）、
`StructuredTaskScope`（JDK 结构化并发）。`Stopwatch` 用 `perf_counter`
即可，无需包装。

## Retryer

```python
from datetime import timedelta
from atlas_richie.concurrency_core import Retryer

result = (
    Retryer.of(timedelta(milliseconds=100))
    .max_attempts(5)
    .max_backoff(timedelta(seconds=2))
    .jitter(True)
    .retry_on(ConnectionError, TimeoutError)
    .execute(call_backend)
)
# 或带兜底：
result = Retryer.of(timedelta(milliseconds=50)).execute_with_fallback(call, default)
```

退避 = `min(initial × 2^(attempt-1), max_backoff)`，溢出取 max；jitter 在
`[backoff/2, backoff]` 均匀取值。不匹配 retryOn 的异常**立即原样上抛**，
不消耗重试次数。耗尽抛 `RetryExhaustedError`（携带最后一次异常）。

## Debouncer

```python
debouncer = Debouncer.of(timedelta(milliseconds=300), refresh)
debouncer.trigger()   # 300ms 内再次 trigger 会重置计时
debouncer.flush()     # 取消计时并立即执行
debouncer.cancel()    # 丢弃待执行动作
```

动作异常被吞掉（对位 Java）——去抖是尽力而为的旁路，不应把异常抛给触发方。
