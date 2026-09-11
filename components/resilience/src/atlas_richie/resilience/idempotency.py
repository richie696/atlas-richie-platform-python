"""幂等键派生策略。
----
`RetryExecutor` 只会重试已知可安全重复的操作。`IdempotencyKey` 策略
负责为给定操作做出该判定。其返回值对 `RetryPolicy` 是不透明的——
只要求可哈希，并且在同一逻辑调用的多次重试间保持稳定。

提供三种开箱即用的实现：

- `StatelessIdempotencyKey`：所有操作视为可重试（适用于无副作用的
  读类操作）。
- `NeverIdempotencyKey`：所有操作视为不可重试（适用于带副作用的
  写操作）。
- `CallableIdempotencyKey`：由调用方提供的派生函数决定。

English
--------
Idempotency-key derivation strategies.

`RetryExecutor` only retries work that is known to be safe to repeat. The
`IdempotencyKey` strategy decides whether a given operation carries such a
guarantee. The result is opaque to `RetryPolicy`; it only needs to be
hashable and stable across retries of the same logical call.

Three built-in strategies are provided:

- `StatelessIdempotencyKey` — every operation is safely retryable
  (read-only side effects).
- `NeverIdempotencyKey` — every operation is non-retryable
  (side-effecting writes).
- `CallableIdempotencyKey` — caller-supplied derive function.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Hashable, Protocol


class IdempotencyKey(Protocol):
    """中文
    ----
    为一次操作派生幂等标签。

    返回 `None` 是硬性信号：即使异常本身属于可重试类型，该操作也
    不得被重试。返回可哈希值则允许 executor 将多次重试归入同一键下
    统计。

    English
    --------
    Derives an idempotency tag for one operation.

    Returning `None` is a hard signal that the operation must not be retried
    even when its exception would otherwise qualify. Returning a hashable
    value allows the executor to group retried calls under the same key.
    """

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        ...


class StatelessIdempotencyKey:
    """中文
    ----
    将所有操作标记为可安全重试。

    适用于天然幂等的读类副作用：DPoP 验证、JWKS 拉取、GET 请求、
    `introspect` 调用等。

    English
    --------
    Marks every operation as safely retryable.

    Use for read-only side effects (DPoP verification, JWKS fetch, GET
    requests, `introspect` calls) where the operation is naturally
    idempotent.
    """

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        return "stateless"


class NeverIdempotencyKey:
    """中文
    ----
    将所有操作标记为不可重试。

    适用于带副作用的调用：未带 `Idempotency-Key` 的 POST、随机数生成、
    触发审计的写等。

    English
    --------
    Marks every operation as non-retryable.

    Use for side-effecting calls (POST without `Idempotency-Key`, random
    number generation, audit-emitting writes) where a retry would be
    incorrect.
    """

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        return None


class CallableIdempotencyKey:
    """中文
    ----
    使用调用方提供的函数派生幂等键。

    该函数在每次 `RetryExecutor.execute` 中被调用一次；可以检查绑定的
    operation、闭包或 header 集合。返回 `None` 等价于
    `NeverIdempotencyKey`。

    English
    --------
    Derives an idempotency key from a user-supplied function.

    The function is invoked once per call to `RetryExecutor.execute`. It may
    inspect the bound operation, a closure, or a header bag. Returning `None`
    has the same meaning as `NeverIdempotencyKey`.
    """

    def __init__(self, derive: Callable[[Callable[[], Awaitable[Any]]], Hashable | None]) -> None:
        if not callable(derive):
            raise TypeError("CallableIdempotencyKey derive must be callable")
        self._derive = derive

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        return self._derive(op)
