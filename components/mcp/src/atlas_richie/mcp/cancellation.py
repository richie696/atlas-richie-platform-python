"""MCP 协作式取消值，与框架任务运行时无关。

中文
----
提供：

- `CancellationToken`：线程安全的协作式取消信号，单次 MCP 调用所有。
- `McpInvocationCancelled`：处理器显式观察到远程调用方已取消时抛出的异常。

不绑定任何具体运行时（asyncio 任务、Java 线程池等），纯 `threading.Event` 实现；
业务实现可以在长循环 / 阻塞操作中轮询 `is_cancelled` 或调用 `throw_if_cancelled()`
触发快速失败。

English
--------
Cooperative MCP cancellation values independent of a framework task runtime.

- `CancellationToken`: a thread-safe, cooperative cancel signal owned by
  one MCP invocation.
- `McpInvocationCancelled`: the exception raised by a handler when it
  explicitly observes the remote caller cancelled the request.

No runtime binding (asyncio task, Java thread pool, …) — implemented on
top of a plain `threading.Event` so business code can poll
`is_cancelled` or call `throw_if_cancelled()` for a fast-fail in
long loops / blocking operations.

Mirrors `cn.richie696.component.mcp.api.McpCancellationToken` +
`McpCallCancelledException` (Java).
"""

from __future__ import annotations

from threading import Event


class McpInvocationCancelled(Exception):
    """中文
    ----
    处理器显式观察到远程调用方已取消请求时抛出的异常。

    English
    --------
    A handler explicitly observed that its remote caller cancelled the
    request.
    """


class CancellationToken:
    """中文
    ----
    线程安全的协作式取消信号，归属一次 MCP 调用。

    English
    --------
    A thread-safe, cooperative cancellation signal owned by one MCP
    invocation.
    """

    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        """中文
        ----
        是否已被请求取消。

        English
        --------
        Whether cancellation has been requested.
        """
        return self._event.is_set()

    def cancel(self) -> None:
        """中文
        ----
        标记本令牌为已取消；幂等，多次调用安全。

        English
        --------
        Mark this token as cancelled. Idempotent.
        """
        self._event.set()

    def throw_if_cancelled(self) -> None:
        """中文
        ----
        若已取消则抛出 `McpInvocationCancelled`；业务代码的快速失败入口。

        Raises:
            McpInvocationCancelled: 当 `is_cancelled` 为真时。

        English
        --------
        Raise `McpInvocationCancelled` if cancelled. Fast-fail hook for
        business code.

        Raises:
            McpInvocationCancelled: when `is_cancelled` is true.
        """
        if self.is_cancelled:
            raise McpInvocationCancelled("MCP invocation was cancelled")
