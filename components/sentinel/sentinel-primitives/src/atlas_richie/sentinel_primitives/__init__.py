"""`atlas-richie-sentinel-primitives` — low-level resilience primitives.

中文
----
Sentinel 家族的**底层原语层**(Layer 1 / M0)。对位 Java
Sentinel 拆出来的 5 个底层能力:

- `RetryPolicy` / `RetryExecutor` — 指数退避 + 抖动 + elapsed budget
- `CircuitBreaker` — closed/half_open/open 状态机
- `TokenBucket` RateLimiter — 容量 + 限流速率
- `Bulkhead` — 信号量并发上限
- `IdempotencyKey` Protocol — 3 个实现(Stateless / Never / Callable)
- `Clock` / `ManualClock` / `RandomSource` — DIP 注入

**3rd-party deps(借鉴成熟库,不重复造轮子)**:

- `stamina` — retry + circuit-breaker(`stamina>=0.10`,Hynek Schlawack 维护)
- `aiolimiter` — rate-limit(`aiolimiter>=1.1`)
- `Bulkhead` / `IdempotencyKey` / `Clock` — 自研(我们的契约,框架特定)

**关系**:
- 上层(`sentinel-core`)用这里 5 个原语构造 slot chain 里的统计 + 降级
- 旧 `atlas-richie-resilience` wheel 改为 shim,re-export 本包

English
--------
Sentinel family Layer 1 — low-level resilience primitives.
See `atlas_richie.sentinel_primitives.retry` / `circuit_breaker` /
`rate_limit` / `bulkhead` / `idempotency` / `clock` for the
five primitives + the clock / random injection.
"""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Will be populated after M0 R-SENTINEL-M0 migration
    # from atlas-richie-resilience.
    # "RetryPolicy",
    # "RetryExecutor",
    # "CircuitBreaker",
    # "CircuitState",
    # "TokenBucket",
    # "Bulkhead",
    # "IdempotencyKey",
    # "StatelessIdempotencyKey",
    # "NeverIdempotencyKey",
    # "CallableIdempotencyKey",
    # "Clock",
    # "SystemClock",
    # "ManualClock",
    # "RandomSource",
    # "ResilienceError",
    # "RetryExhausted",
    # "RetryNotPermitted",
    # "CircuitOpen",
    # "RateLimitExceeded",
    # "BulkheadFull",
]
