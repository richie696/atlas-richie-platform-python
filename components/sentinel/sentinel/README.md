# Atlas Richie Sentinel

## What

Atlas Richie Sentinel is a flow-control, circuit-breaking, and system-protection framework
for Python services. It is the Python-native equivalent of Alibaba Sentinel: a single
`atlas-richie-sentinel` wheel that gives you resource governance, sliding-window
statistics, slot chains, and degrade rules, with **zero third-party runtime dependencies**
in the main wheel.

## Why

Existing Python options cover only one slice each (`stamina` for retry, `pybreaker`
for circuit-breaker, `aiolimiter` for rate-limiting, `prometheus-client` for metrics).
None of them gives you a unified **resource model + multi-rule + slot chain** pipeline
that protects both the entire service and individual resources. Sentinel is the proven
"two-layer" design (system-level + business-level) used in Spring Cloud Gateway / Dubbo
/ gRPC for years; this is the Python-native version.

## Compare

| Concern              | `stamina` / `pybreaker` / `aiolimiter` | `atlas-richie-sentinel`     |
| -------------------- | -------------------------------------- | --------------------------- |
| Resource model       | None                                   | `Resource` + slot chain     |
| Flow / Degrade rules | None                                   | 5 rule families (M1-M3)     |
| System protection    | None                                   | `SystemSlot` (CPU/Load/QPS) |
| Source / push        | None                                   | `source-file` / `source-nacos` / `source-redis` (extensions) |
| Dashboard            | None                                   | `sentinel-dashboard` (REST control plane) |
| Third-party deps     | 1 each (lifecycle dep)                 | **0** in main wheel         |
| Async-native         | partial                                | asyncio-first + async ctx   |

## Quick Start

```python
# M0 surface — primitives only (retry / circuit-breaker / rate-limit / bulkhead /
# idempotency / clock / random). Full Engine + rules land in M1-M3.
from atlas_richie.sentinel.primitives import (
    RetryPolicy, RetryExecutor,
    CircuitBreaker, CircuitBreakerConfig, CircuitState,
    TokenBucket, TokenBucketConfig,
    Bulkhead, BulkheadConfig,
    IdempotencyKey, StatelessIdempotencyKey, NeverIdempotencyKey, CallableIdempotencyKey,
    Clock, SystemClock, ManualClock, system_sleep,
    RandomSource, SystemRandom, DeterministicRandom,
)
from atlas_richie.sentinel.errors import (
    SentinelError, ResilienceError,
    RetryExhausted, RetryNotPermitted,
    CircuitOpen, RateLimitExceeded, BulkheadFull,
)
```

License: Apache-2.0. See `components/sentinel/docs/DESIGN.md` and
`components/sentinel/docs/PLANNING.md` for the full design and milestone plan.
