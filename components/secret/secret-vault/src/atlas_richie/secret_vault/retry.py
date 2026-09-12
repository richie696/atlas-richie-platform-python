"""Vault retry executor — bounded retry for transient failures only。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultRetryExecutor`。

设计原则:

1. **只重试 transient 失败**:网络错误(`requests.exceptions.ConnectionError` /
   `requests.exceptions.Timeout`)+ Vault 5xx / 429。其它(403 / 404 /
   业务级 4xx)**不**重试,因为这些是配置错误或权限问题,重试只会
   放大 log 噪音。
2. **bounded**:max_attempts 上限(对位 Java `BootstrapSecretProperties
   .getResilience().getMaxAttempts()`),默认 3。
3. **退避策略**:exponential with jitter,基础 `0.1s * 2^(attempt-1)`,
   上限 `1.0s`,jitter 50–100%。可被 `Retry-After` 头覆盖(Vault
   自身在 429 时会发)。
4. **副作用考虑**:只重试读取 + Transit(无持久化副作用的密码学操作)
   — Java 注释明确说"重试产生的未采用密文不会被持久化"。本仓的
   `VaultSecretClient.wrap_key` / `unwrap_key` 也是纯计算,符合这条
   边界。
5. **类型:`Supplier[T]`** 镜像 Java `Supplier<T>`,Python 用 `Callable[[], T]`。

错误转译:不主动包装异常,只决定"是否重试"。调用方 `VaultSecretClient`
在最终重试失败时,自己捕获 `hvac.exceptions.VaultError` 并映射到
`SecretException` / `SecretCryptoException`。

English
--------
Bounded retry executor. Mirrors Java `VaultRetryExecutor`. Retries
network errors + 5xx + 429; refuses to retry 4xx (config / auth
errors). Exponential backoff with jitter, capped at 1.0s; honors
`Retry-After` header. Operates on the same side-effect-free subset
(reads + Transit) as Java's executor.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

import hvac
import requests

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_vault.retry")

T = TypeVar("T")

# Status codes that are safe to retry (server overloaded / throttling).
_RETRIABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Backoff ceiling (millis). Mirrors Java: `min(1_000L, 100L << attempt)`.
_BACKOFF_CEILING_MS = 1_000
_BACKOFF_BASE_MS = 100


class VaultRetryExecutor:
    """Bounded retry for transient Vault / network failures.

    Args:
        max_attempts: Maximum attempts including the first try.
            Clamped to ``>= 1``. ``1`` disables retry.
        base_backoff_seconds: Base for exponential backoff. Default
            ``0.1`` (100 ms) so the math matches Java's `100L << attempt`.
    """

    __slots__ = ("_base_backoff", "_max_attempts", "_rng")

    def __init__(
        self,
        max_attempts: int = 3,
        base_backoff_seconds: float = 0.1,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._max_attempts = max_attempts
        self._base_backoff = base_backoff_seconds
        # Per-instance RNG so test seeding is straightforward.
        self._rng = random.Random()

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def execute(self, operation: Callable[[], T]) -> T:
        """Run `operation` with bounded retry on transient failures.

        Re-raises the last exception when retries are exhausted or
        when the failure is non-transient. Does not catch
        `BaseException` (KeyboardInterrupt / SystemExit propagate
        cleanly).
        """
        last_exception: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return operation()
            except Exception as error:  # noqa: BLE001 - we filter inside
                last_exception = error
                if attempt == self._max_attempts or not _is_transient(error):
                    raise
                retry_after_seconds = _retry_after_seconds(error)
                self._pause(attempt, retry_after_seconds)
        # Unreachable: the loop either returns or raises on the last
        # attempt. Defensive `raise` to keep mypy strict-mode happy.
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("vault: retry executor exited without result")

    def _pause(self, attempt: int, retry_after_seconds: float) -> None:
        # Exponential ceiling: 100ms * 2^(attempt-1), capped at 1.0s.
        ceiling_ms = min(_BACKOFF_CEILING_MS, _BACKOFF_BASE_MS << (attempt - 1))
        # Jittered sleep in [ceiling/2, ceiling].
        sleep_ms = self._rng.randint(max(1, ceiling_ms // 2), ceiling_ms)
        # Honor Retry-After, but cap it at 2.0s (matches Java's
        # `min(2_000L, ...)` upper bound).
        retry_after_ms = min(2_000, max(0, int(retry_after_seconds * 1000)))
        sleep_ms = max(sleep_ms, retry_after_ms)
        _logger.debug(
            "vault: transient failure; retrying in %dms (attempt %d)",
            sleep_ms,
            attempt,
        )
        time.sleep(sleep_ms / 1000.0)


def _is_transient(error: BaseException) -> bool:
    """Return True iff `error` is safe to retry.

    Transient: network failures + 429 + 5xx. Anything else (404,
    403, business 4xx) is a permanent failure for this call.
    """
    # Network layer failures.
    if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    # Walk the cause chain for hvac / requests exceptions.
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, hvac.exceptions.VaultError):
            status = getattr(current, "status_code", None)
            if status is not None and status in _RETRIABLE_STATUSES:
                return True
            # hvac also raises RateLimitExceeded for 429 explicitly.
            if isinstance(current, hvac.exceptions.RateLimitExceeded):
                return True
            if isinstance(current, hvac.exceptions.InternalServerError):
                return True
            # 4xx other than 429 are not retriable.
            return False
        if isinstance(current, requests.exceptions.HTTPError):
            status = getattr(current.response, "status_code", None) if current.response is not None else None
            if status is not None and status in _RETRIABLE_STATUSES:
                return True
            return False
        current = current.__cause__ or current.__context__
    return False


def _retry_after_seconds(error: BaseException) -> float:
    """Extract the `Retry-After` value (seconds) if `error` is an
    HTTP response with that header; otherwise 0.
    """
    current: BaseException | None = error
    while current is not None:
        response = getattr(current, "response", None)
        if response is not None:
            try:
                retry_after = response.headers.get("Retry-After")
            except Exception:  # noqa: BLE001
                return 0.0
            if not retry_after:
                return 0.0
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                # HTTP-date form is uncommon on Vault; ignore and
                # fall back to 0.
                return 0.0
        current = current.__cause__ or current.__context__
    return 0.0


__all__ = ["VaultRetryExecutor"]
