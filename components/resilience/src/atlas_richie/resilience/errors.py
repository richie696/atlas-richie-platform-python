"""按可移植行为分类的 resilience 失败类型。
----
所有 resilience 原语在受控失败时抛 `ResilienceError` 子类。共同的契约
是带 `retry_after: float`（如果适用），调用方可以根据它做退避或
熔断决策。这些异常继承自 `atlas_richie.contracts.PlatformError`，
因此与平台其他模块的错误体系统一。

- `RetryExhausted` / `RetryNotPermitted`：retry 阶段失败
- `CircuitOpen`：熔断器拒绝调用
- `RateLimitExceeded`：限流器拒绝请求
- `BulkheadFull`：并发舱已满

English
--------
Resilience failure types, classified by portable behavior.

All resilience primitives raise subclasses of `ResilienceError` on
controlled failure. The shared contract carries a `retry_after: float`
where applicable so callers can drive backoff or circuit-breaker
decisions. These exceptions inherit from
`atlas_richie.contracts.PlatformError`, keeping the failure model
consistent with the rest of the platform.

- `RetryExhausted` / `RetryNotPermitted` — retry-stage failure
- `CircuitOpen` — circuit breaker rejected the call
- `RateLimitExceeded` — rate limiter denied the request
- `BulkheadFull` — concurrency cap reached"""

from __future__ import annotations

from atlas_richie.contracts import PlatformError


class ResilienceError(PlatformError):
    """中文
    ----
    受控 resilience 失败的基类。

    English
    --------
    Base class for controlled resilience failures.
    """


class RetryExhausted(ResilienceError):
    """中文
    ----
    重试次数耗尽仍未成功，或总耗时超出预算。

    English
    --------
    Retry attempts were exhausted without success, or the elapsed budget elapsed.
    """

    def __init__(self, message: str, *, attempts: int, last_exception: BaseException) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception


class RetryNotPermitted(ResilienceError):
    """中文
    ----
    配置的幂等策略拒绝重试该操作（`IdempotencyKey.derive` 返回 `None`）。

    English
    --------
    The configured idempotency policy refused to retry the operation.
    """


class CircuitOpen(ResilienceError):
    """中文
    ----
    熔断器当前为 OPEN 状态，调用被拒绝。`retry_after` 指示距离进入
    `HALF_OPEN` 的剩余秒数。

    English
    --------
    A call was rejected because the circuit breaker is currently open.
    """

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitExceeded(ResilienceError):
    """中文
    ----
    限流器因令牌桶已空且不允许等待而拒绝请求。`retry_after` 指示
    直到令牌可用的剩余秒数。

    English
    --------
    A rate limiter denied the request because the bucket was empty and no wait was allowed.
    """

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BulkheadFull(ResilienceError):
    """中文
    ----
    并发舱在容量已满且不允许等待时拒绝请求。

    English
    --------
    A bulkhead rejected the request because the concurrency cap is at capacity and no wait was allowed.
    """

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after
