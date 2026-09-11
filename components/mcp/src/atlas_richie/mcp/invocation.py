"""MCP tool 调用的有序、框架无关切面。

中文
----
定义 MCP tool 调用的横切关注点（interceptor / audit / trace / deadline / 调用链），
**与具体运行时无关**（asyncio / Spring / Akka 等都不绑定）。

核心类型：

- `McpInvocation`：不可变的 (descriptor, context, arguments) 三元组。
- `McpInvocationInterceptor`：协作者协议 `intercept(invocation, proceed)`。
- `McpAuditEvent` / `McpAuditSink`：调用结束后写入一次审计事件。
- `McpTraceEvent` / `McpTraceSink`：start / end 两个阶段。
- `build_invocation_pipeline(...)`：构造固定顺序
  `trace → deadline → caller interceptors → audit → handler` 的链。
- `invoke_handler(invocation)`：在 `descriptor.function` 上调用；若返回
  awaitable 则 `await`；先检查取消。

固定顺序的设计动机：trace 包外层、audit 包最贴近 handler（观测到真实退出）、
deadline 包裹业务逻辑；调用方可以插入自己的 interceptor（例如授权、metrics），
顺序由 `build_invocation_pipeline` 集中保证。

English
--------
Ordered, framework-neutral MCP tool invocation aspects.

Defines the cross-cutting concerns of an MCP tool invocation
(interceptor / audit / trace / deadline / chain) **independent of any
runtime** (no asyncio / Spring / Akka binding here).

Core types:

- `McpInvocation`: an immutable (descriptor, context, arguments)
  triple.
- `McpInvocationInterceptor`: a Protocol with
  `intercept(invocation, proceed)`.
- `McpAuditEvent` / `McpAuditSink`: write one audit event per
  completed invocation.
- `McpTraceEvent` / `McpTraceSink`: start / end phases.
- `build_invocation_pipeline(...)`: build the fixed-order chain
  `trace → deadline → caller interceptors → audit → handler`.
- `invoke_handler(invocation)`: invoke `descriptor.function`; `await`
  the result if it is awaitable; check cancellation first.

The fixed ordering exists so that `trace` wraps the outside, `audit`
sits closest to the handler (so it observes the actual exit), and
`deadline` bounds the business logic. Callers can insert their own
interceptors (e.g. auth, metrics) and the order is guaranteed by
`build_invocation_pipeline`.

Mirrors `cn.richie696.component.mcp.api.server.McpToolInvocation` +
`McpToolInvocationInterceptor` + `McpToolInvocationChain` (Java).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol

from .models import ToolContext, ToolDescriptor

InvocationNext = Callable[["McpInvocation"], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class McpInvocation:
    """中文
    ----
    不可变 (descriptor, context, arguments) 三元组；invocation chain 上
    每一步看到的"当前调用"。

    English
    --------
    Immutable (descriptor, context, arguments) triple representing the
    "current invocation" at every step of the chain.
    """

    descriptor: ToolDescriptor
    context: ToolContext
    arguments: Mapping[str, Any]


class McpInvocationInterceptor(Protocol):
    """中文
    ----
    调用链拦截器协议；`intercept(invocation, proceed)` 必须 `await proceed`
    至少一次，否则调用挂起。

    English
    --------
    Invocation chain interceptor protocol;
    `intercept(invocation, proceed)` must `await proceed` at least
    once or the call will hang.
    """

    async def intercept(self, invocation: McpInvocation, proceed: InvocationNext) -> object: ...


@dataclass(frozen=True, slots=True)
class McpAuditEvent:
    """中文
    ----
    单次调用结束后的审计事件：tool 名 / 耗时毫秒 / 结果标签
    （`success` / `failure`）。

    English
    --------
    Post-invocation audit event: tool name, duration in milliseconds,
    and outcome label (`success` / `failure`).
    """

    tool_name: str
    duration_ms: float
    outcome: str


class McpAuditSink(Protocol):
    """中文
    ----
    审计接收器协议；`record` 在 `audit` interceptor 的 `finally` 块中调用，
    接收器抛出的异常不会反向影响调用结果。

    English
    --------
    Audit sink protocol; `record` is invoked from the `audit`
    interceptor's `finally` block, and any exception raised by the
    sink does not affect the call's outcome.
    """

    def record(self, event: McpAuditEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class McpTraceEvent:
    """中文
    ----
    单次 trace 阶段事件：trace_id / tool 名 / 阶段（`start` / `end`）。

    English
    --------
    Single trace phase event: trace_id, tool name, and phase label
    (`start` / `end`).
    """

    trace_id: str | None
    tool_name: str
    phase: str


class McpTraceSink(Protocol):
    """中文
    ----
    Trace 接收器协议；`record` 在 `trace` interceptor 的 start / end 钩子
    中调用。

    English
    --------
    Trace sink protocol; `record` is invoked from the `trace`
    interceptor's start / end hooks.
    """

    def record(self, event: McpTraceEvent) -> None: ...


class _InvocationStep:
    def __init__(self, interceptor: McpInvocationInterceptor, next_step: InvocationNext) -> None:
        self._interceptor = interceptor
        self._next_step = next_step

    async def __call__(self, invocation: McpInvocation) -> object:
        return await self._interceptor.intercept(invocation, self._next_step)


class _DeadlineInterceptor:
    async def intercept(self, invocation: McpInvocation, proceed: InvocationNext) -> object:
        deadline = invocation.context.deadline
        if deadline is None:
            return await proceed(invocation)
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("MCP invocation deadline has elapsed")
        return await asyncio.wait_for(proceed(invocation), timeout=remaining)


class _TraceInterceptor:
    def __init__(self, sink: McpTraceSink | None) -> None:
        self._sink = sink

    async def intercept(self, invocation: McpInvocation, proceed: InvocationNext) -> object:
        self._record(invocation, "start")
        try:
            return await proceed(invocation)
        finally:
            self._record(invocation, "end")

    def _record(self, invocation: McpInvocation, phase: str) -> None:
        if self._sink is not None:
            self._sink.record(McpTraceEvent(invocation.context.trace_id, invocation.descriptor.name, phase))


class _AuditInterceptor:
    def __init__(self, sink: McpAuditSink | None) -> None:
        self._sink = sink

    async def intercept(self, invocation: McpInvocation, proceed: InvocationNext) -> object:
        started = monotonic()
        outcome = "success"
        try:
            return await proceed(invocation)
        except Exception:
            outcome = "failure"
            raise
        finally:
            if self._sink is not None:
                self._sink.record(McpAuditEvent(invocation.descriptor.name, (monotonic() - started) * 1000, outcome))


def build_invocation_pipeline(
    interceptors: tuple[McpInvocationInterceptor, ...],
    audit_sink: McpAuditSink | None,
    trace_sink: McpTraceSink | None,
    terminal: InvocationNext,
) -> InvocationNext:
    """中文
    ----
    构造固定顺序的调用链：

        trace → deadline → caller_interceptors... → audit → terminal

    调用方提供的 `interceptors` 顺序为"最外层 → 最内层"（按 reversed 嵌套）。

    Args:
        interceptors: 调用方提供的额外拦截器；最外层在前。
        audit_sink: 审计接收器（可空）。
        trace_sink: trace 接收器（可空）。
        terminal: 链最内层的下一步（通常为 `invoke_handler`）。

    Returns:
        一个 `async def(next_invocation)` 入口。

    English
    --------
    Build the fixed-order invocation chain:

        trace → deadline → caller_interceptors... → audit → terminal

    The caller's `interceptors` are listed outermost-first; they are
    nested in reverse.

    Args:
        interceptors: caller-supplied extra interceptors;
            outermost first.
        audit_sink: audit sink (nullable).
        trace_sink: trace sink (nullable).
        terminal: the innermost next-step (typically `invoke_handler`).

    Returns:
        an `async def(next_invocation)` entry point.
    """

    pipeline: InvocationNext = _InvocationStep(_AuditInterceptor(audit_sink), terminal)
    for interceptor in reversed(interceptors):
        pipeline = _InvocationStep(interceptor, pipeline)
    pipeline = _InvocationStep(_DeadlineInterceptor(), pipeline)
    return _InvocationStep(_TraceInterceptor(trace_sink), pipeline)


async def invoke_handler(invocation: McpInvocation) -> object:
    """中文
    ----
    在 `descriptor.function` 上调用；先检查取消；若返回 awaitable 则 `await`。

    Args:
        invocation: 当前调用。

    Returns:
        handler 的返回值（同步或异步结果统一）。

    Raises:
        McpInvocationCancelled: 入口处发现已取消。
        任何 handler 抛出的异常会原样上抛（由 audit / trace / 业务 interceptor
        观测）。

    English
    --------
    Invoke `descriptor.function`; check cancellation first; `await` the
    result if it is awaitable.

    Args:
        invocation: the current invocation.

    Returns:
        the handler's return value (sync or async result unified).

    Raises:
        McpInvocationCancelled: when the token is already cancelled at
            entry.
        any exception the handler raises propagates (observed by the
        audit / trace / business interceptors).
    """
    invocation.context.cancellation.throw_if_cancelled()
    result = invocation.descriptor.function(invocation.context, **dict(invocation.arguments))
    return await result if inspect.isawaitable(result) else result
