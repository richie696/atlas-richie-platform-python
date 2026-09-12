"""按可移植行为分类的 Sentinel 失败类型。
----
唯一异常层 = `atlas_richie.sentinel.errors`。根异常 `SentinelError` 直接
继承 stdlib `Exception`(主包零 3rd-party 必备);`ResilienceError` 继承
`SentinelError`;M0 阶段 5 个原语异常继承 `ResilienceError`。

M1.1 拆分: 根 `SentinelError` 在 `base.py`;Engine 拒绝异常
`SentinelBlockedError` + 5 子类在 `block.py`(独立分支,与 ResilienceError
互不为子类);配置 / 生命周期异常分别在 `configuration.py` / `lifecycle.py`。
本 `__init__.py` 仅 re-export,不重新定义任何类。

完整层级:

    SentinelError(Exception)                ← 根,stdlib(在 base.py)
    ├── ResilienceError(SentinelError)      ← 原语 throw(M0 阶段 5 个)
    │   ├── RetryExhausted
    │   ├── RetryNotPermitted
    │   ├── CircuitOpen
    │   ├── RateLimitExceeded
    │   └── BulkheadFull
    ├── SentinelBlockedError(SentinelError) ← Engine / Slot 拒绝(M1.1 引入)
    │   ├── FlowBlocked
    │   ├── ParamFlowBlocked
    │   ├── SystemBlocked
    │   ├── CircuitBlocked                  ← 暴露 retry_after/state/rule,非 CircuitOpen 子类
    │   └── AuthorityDenied
    ├── SentinelConfigurationError(SentinelError)   ← M1.1 引入
    ├── SentinelLifecycleError(SentinelError)       ← M1.1 引入
    └── RuleSnapshotError(SentinelLifecycleError)   ← M1.1 引入

关键设计:

- **单继承不复用**: `CircuitBlocked` 不是 `CircuitOpen` 子类,二者
  `isinstance` 互不成立
- **独立分支**: `SentinelBlockedError` 与 `ResilienceError` 互不为子类,
  ``except`` 互不干扰
- **稳定 code**: 每个 ``SentinelBlockedError`` 子类带 ``stable_code``
  字符串,跨进程日志关联

English
--------
Sentinel failure types, classified by portable behavior.

Sole exception layer for the ``atlas-richie-sentinel`` main wheel. The
root ``SentinelError`` inherits stdlib ``Exception`` directly so the
main wheel has zero third-party runtime dependencies. ``ResilienceError``
is its first subclass; M0 ships five concrete primitive exceptions
under ``ResilienceError``.

M1.1 split: the root ``SentinelError`` lives in ``base.py``;
``SentinelBlockedError`` + 5 subclasses in ``block.py`` (a separate
branch from ``ResilienceError``); config / lifecycle exceptions in
``configuration.py`` / ``lifecycle.py``. This ``__init__.py`` only
re-exports; it does not re-define any class.

Key design:

- **Single inheritance, no reuse**: ``CircuitBlocked`` is **not** a
  subclass of ``CircuitOpen``; the two are not ``isinstance``-related.
- **Separate branches**: ``SentinelBlockedError`` and
  ``ResilienceError`` are not subclasses of each other, so their
  ``except`` arms do not interfere.
- **Stable code**: every ``SentinelBlockedError`` subclass carries a
  ``stable_code`` string for cross-process log correlation."""

from __future__ import annotations

# 1) 根异常先 import(M0.5-A 锁定, 继承 stdlib Exception)
from .base import SentinelError

# 2) M0 原语 throw 基类 + 5 个具体异常
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

    Engine / Slot rejection paths do **not** inherit this class; they
    use the separate ``SentinelBlockedError`` branch so ``except``
    semantics stay clean.
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


# 3) M1.1 引入: 拒绝 / 配置 / 生命周期 异常
from .block import (
    AuthorityDenied,
    CircuitBlocked,
    FlowBlocked,
    ParamFlowBlocked,
    SentinelBlockedError,
    SystemBlocked,
)
from .configuration import SentinelConfigurationError
from .lifecycle import RuleSnapshotError, SentinelLifecycleError

__all__ = [
    # root
    "SentinelError",
    # M0 原语 throw 5 个 + 基类
    "ResilienceError",
    "RetryExhausted",
    "RetryNotPermitted",
    "CircuitOpen",
    "RateLimitExceeded",
    "BulkheadFull",
    # M1.1 拒绝 (独立分支, 非 ResilienceError 子类)
    "SentinelBlockedError",
    "FlowBlocked",
    "ParamFlowBlocked",
    "SystemBlocked",
    "CircuitBlocked",
    "AuthorityDenied",
    # M1.1 配置 / 生命周期
    "SentinelConfigurationError",
    "SentinelLifecycleError",
    "RuleSnapshotError",
]
