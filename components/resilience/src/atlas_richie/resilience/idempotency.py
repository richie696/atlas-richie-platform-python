"""Idempotency-key derivation strategies.

`RetryExecutor` only retries work that is known to be safe to repeat. The
`IdempotencyKey` strategy decides whether a given operation carries such a
guarantee. The result is opaque to `RetryPolicy`; it only needs to be
hashable and stable across retries of the same logical call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Hashable, Protocol


class IdempotencyKey(Protocol):
    """Derives an idempotency tag for one operation.

    Returning `None` is a hard signal that the operation must not be retried
    even when its exception would otherwise qualify. Returning a hashable
    value allows the executor to group retried calls under the same key.
    """

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        ...


class StatelessIdempotencyKey:
    """Marks every operation as safely retryable.

    Use for read-only side effects (DPoP verification, JWKS fetch, GET
    requests, `introspect` calls) where the operation is naturally
    idempotent.
    """

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        return "stateless"


class NeverIdempotencyKey:
    """Marks every operation as non-retryable.

    Use for side-effecting calls (POST without `Idempotency-Key`, random
    number generation, audit-emitting writes) where a retry would be
    incorrect.
    """

    def derive(self, op: Callable[[], Awaitable[Any]]) -> Hashable | None:
        return None


class CallableIdempotencyKey:
    """Derives an idempotency key from a user-supplied function.

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
