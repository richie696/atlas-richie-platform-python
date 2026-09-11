"""跨 component 共享的最小 lifecycle 协议。
----
提供 `AsyncCloseable` 协议：可等待 + 幂等的 `aclose()`。所有需要
资源释放的 component 都实现这个协议（Redis pool、HTTP client、
file handle 等），业务方在 shutdown 时统一调 `await
resource.aclose()`，重复调用安全。

English
--------
Minimal lifecycle protocols shared across components.

`AsyncCloseable` is a Protocol declaring an `async def aclose()`
that is safe to call repeatedly. Every resource-owning component
(Redis pool, HTTP client, file handle, …) implements this; callers
can `await resource.aclose()` during shutdown without worrying about
double-close exceptions.
"""

from typing import Protocol


class AsyncCloseable(Protocol):
    """资源 close 操作可等待且幂等的对象。

    重复调用 `aclose()` 不应抛异常 — 这是 idempotent 契约，业务方
    shutdown 路径可放心调多次（finally + atexit 重复场景）。

    English
    --------
    A resource whose close operation can be awaited and is idempotent.
    """

    async def aclose(self) -> None:
        """释放资源 — 重复调用不抛异常。"""
