"""Ordered, framework-neutral MCP tool invocation aspects."""

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
    descriptor: ToolDescriptor
    context: ToolContext
    arguments: Mapping[str, Any]


class McpInvocationInterceptor(Protocol):
    async def intercept(self, invocation: McpInvocation, proceed: InvocationNext) -> object: ...


@dataclass(frozen=True, slots=True)
class McpAuditEvent:
    tool_name: str
    duration_ms: float
    outcome: str


class McpAuditSink(Protocol):
    def record(self, event: McpAuditEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class McpTraceEvent:
    trace_id: str | None
    tool_name: str
    phase: str


class McpTraceSink(Protocol):
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
    """Build the fixed `trace -> deadline -> caller -> audit -> handler` composition."""

    pipeline: InvocationNext = _InvocationStep(_AuditInterceptor(audit_sink), terminal)
    for interceptor in reversed(interceptors):
        pipeline = _InvocationStep(interceptor, pipeline)
    pipeline = _InvocationStep(_DeadlineInterceptor(), pipeline)
    return _InvocationStep(_TraceInterceptor(trace_sink), pipeline)


async def invoke_handler(invocation: McpInvocation) -> object:
    invocation.context.cancellation.throw_if_cancelled()
    result = invocation.descriptor.function(invocation.context, **dict(invocation.arguments))
    return await result if inspect.isawaitable(result) else result
