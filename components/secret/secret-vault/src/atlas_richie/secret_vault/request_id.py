"""Vault request-id correlation — per-thread 关联 ID,审计 / 日志 / bootstrap 输出。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultRequestIdCapture`。

Java 端在 `RestTemplate` 上挂 `ClientHttpRequestInterceptor`,把
`X-Atlas-Request-Id` 写到请求头,response 走 `X-Vault-Request-Id`(Vault
自身的 bool flag,不携带 UUID)。Python 端 hvac 2.x 不暴露 request
header 注入点(改 adapter 风险大),所以采用 **业务侧关联** 做法:

- 每个 logical operation(`SecretBackend.get` / `KeyWrappingBackend.wrap_key`
  / `SecretBootstrapClient.bootstrap`)进入时 `clear()` 生成新 UUID;
- 操作结束后 `consume()` 取走该 ID,作为该 operation 的"指纹"写进
  `SecretBootstrapResult` 或日志;
- `threading.local()` 保证并发线程互不污染。

`consume()` 后 thread-local 状态被清空,下一次 operation 重新生成。
不直接写 header 是已知 trade-off:framework 端能拿到 ID 做审计,
但 Vault server log 里看不到这层 metadata(只能看到 hvac 自己的
`X-Vault-Request-Id`)。

English
--------
Per-thread correlation id for the Vault backend. Mirrors Java
`VaultRequestIdCapture`. hvac 2.x does not expose a clean header-
injection API, so we attach the id to logs + `SecretBootstrapResult`
rather than the HTTP request. `consume()` reads + clears thread-local
state; `clear()` resets to a fresh UUID.
"""

from __future__ import annotations

import logging
import threading
import uuid

_logger = logging.getLogger("atlas_richie.secret_vault.request_id")


class VaultRequestIdCapture:
    """Per-thread correlation id holder.

    `clear()` produces a new id; `consume()` reads the current id
    and clears thread-local state. `current_id()` is a non-mutating
    accessor used by log statements.
    """

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state = threading.local()

    def clear(self) -> str:
        """Force a new correlation id on this thread and return it.

        The id is stored thread-local; subsequent calls on the same
        thread observe the same id until `consume()` or another
        `clear()` runs.
        """
        new_id = str(uuid.uuid4())
        self._state.correlation_id = new_id
        return new_id

    def consume(self) -> str | None:
        """Read the current correlation id, then clear the slot.

        Returns ``None`` if `clear()` was not called on this thread.
        """
        current = getattr(self._state, "correlation_id", None)
        if hasattr(self._state, "correlation_id"):
            delattr(self._state, "correlation_id")
        return current

    def current_id(self) -> str | None:
        """Non-mutating accessor for the current correlation id.

        Useful for log records attached to a long-lived operation
        where the id must not be cleared mid-flight.
        """
        return getattr(self._state, "correlation_id", None)


__all__ = ["VaultRequestIdCapture"]


_ = (logging.getLogger,)
