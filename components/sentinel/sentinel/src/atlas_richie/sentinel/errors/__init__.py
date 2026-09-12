"""按可移植行为分类的 Sentinel 失败类型。
----
唯一异常层 = `atlas_richie.sentinel.errors`。根异常 `SentinelError` 直接
继承 stdlib `Exception`(主包零 3rd-party 必备);`ResilienceError` 继承
`SentinelError`;M0 阶段 5 个原语异常继承 `ResilienceError`。

层级:

    SentinelError(Exception)                ← 根,stdlib
    ├── ResilienceError(SentinelError)      ← 原语受控失败
    │   ├── RetryExhausted
    │   ├── RetryNotPermitted
    │   ├── CircuitOpen
    │   ├── RateLimitExceeded
    │   └── BulkheadFull
    ├── SentinelBlockedError(SentinelError) ← M1.1 新增,Engine 拒绝契约
    │   ├── FlowBlocked
    │   ├── ParamFlowBlocked
    │   ├── SystemBlocked
    │   ├── AuthorityDenied
    │   └── CircuitBlocked
    ├── SentinelConfigurationError(SentinelError)  ← M1.1 新增
    ├── SentinelLifecycleError(SentinelError)      ← M1.1 新增
    └── RuleSnapshotError(SentinelLifecycleError)  ← M1.1 新增

M0 阶段只有 `ResilienceError` + 5 个具体异常;`SentinelBlockedError` 等
M1.1 子树在 M1.1 添加,继承 `SentinelError` 而**不**经过 `ResilienceError`,
保证 `except SentinelBlockedError` 不会误捕获原语 throw 的 `CircuitOpen`。
详见 `components/sentinel/docs/PLANNING.md` §M0.5-A。

设计要点:

- **`retry_after: float` 契约**:所有带退避语义的异常都暴露 `retry_after`
  字段,调用方可以驱动退避或熔断决策。
- **不复用原语异常**:Engine / DegradeSlot 拒绝时**不**抛 `CircuitOpen`,
  而是 `CircuitBlocked(retry_after=..., state=..., rule=...) from circuit_open`,
  复制可观察字段但不伪装为原语异常。

English
--------
Sentinel failure types, classified by portable behavior.

Sole exception layer for the `atlas-richie-sentinel` main wheel. The
root `SentinelError` inherits stdlib `Exception` directly so the main
wheel has zero third-party runtime dependencies. `ResilienceError` is
its first subclass; M0 ships five concrete primitive exceptions under
`ResilienceError`. M1.1 will add `SentinelBlockedError` and its
descendants as a separate branch under `SentinelError` (not under
`ResilienceError`) so `except SentinelBlockedError` never accidentally
catches a primitive-thrown `CircuitOpen`.

- `RetryExhausted` / `RetryNotPermitted` — retry-stage failure
- `CircuitOpen` — circuit breaker rejected the call
- `RateLimitExceeded` — rate limiter denied the request
- `BulkheadFull` — concurrency cap reached"""

from __future__ import annotations


class SentinelError(Exception):
    """中文
    ----
    所有 Sentinel 异常的根。直接继承 stdlib `Exception` 以保证主包零
    3rd-party 依赖(不依赖 `atlas_richie.contracts.PlatformError`)。

    English
    --------
    Root of the Sentinel exception tree. Inherits stdlib `Exception`
    directly so the main wheel stays free of third-party runtime
    dependencies (notably `atlas_richie.contracts.PlatformError`).
    """


class ResilienceError(SentinelError):
    """中文
    ----
    受控 resilience 失败的基类(原语直接 throw 的统一父类)。

    Engine / Slot 拒绝路径**不**继承本类;它们用
    `SentinelBlockedError` 独立分支,以保持 `except` 语义干净。

    English
    --------
    Base class for controlled resilience failures (the unified parent
    that primitives throw directly).

    Engine / Slot rejection paths do **not** inherit this class; they use
    the separate `SentinelBlockedError` branch so `except` semantics stay
    clean.
    """


class RetryExhausted(ResilienceError):
    """中文
    ----
    重试次数耗尽仍未成功,或总耗时超出预算。

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
    配置的幂等策略拒绝重试该操作(`IdempotencyKey.derive` 返回 `None`)。

    English
    --------
    The configured idempotency policy refused to retry the operation.
    """


class CircuitOpen(ResilienceError):
    """中文
    ----
    熔断器当前为 OPEN 状态,调用被拒绝。`retry_after` 指示距离进入
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
