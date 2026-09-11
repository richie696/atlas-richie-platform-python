"""显式有序的拦截器契约与审计安全事件。
----
定义拦截器链的形状：

- `HttpInterceptor` / `AsyncHttpInterceptor`：Protocol 形态的同步/
  异步拦截器契约；`intercept(request, proceed)` 既能 transform /
  observe，也能显式 short-circuit（不调 `proceed`）。
- `SyncNext` / `AsyncNext`：链上"下一步"的类型别名。
- `HttpAuditEvent`：不携带请求/响应 body 与 header 的交换记录，
  对普通审计 sink 而言是安全可序列化的。
- `HttpAuditSink`：消费方拥有的副作用端口，自身是 Protocol，
  消费者按需实现。

内置拦截器（私有，路径相同）：

- `_RequestIdInterceptor` / `_AsyncRequestIdInterceptor`：若请求
  缺 `X-Request-Id` 头则补一个 `uuid4()`。
- `_AuditInterceptor` / `_AsyncAuditInterceptor`：以 `monotonic()`
  为基准，产出 `HttpAuditEvent`；`sink` 为 `None` 时静默跳过。

English
--------
Explicit ordered interceptor contracts + audit-safe events.

- `HttpInterceptor` / `AsyncHttpInterceptor`: Protocol contracts
  for sync / async interceptors. `intercept(request, proceed)`
  may transform, observe, or explicitly short-circuit.
- `SyncNext` / `AsyncNext`: type aliases for "the next link".
- `HttpAuditEvent`: body- and header-free exchange record, safe
  to serialise to ordinary audit sinks.
- `HttpAuditSink`: consumer-owned side-effect port; itself a
  Protocol that consumers implement.

Built-in (private) interceptors share this module:

- `_RequestIdInterceptor` / `_AsyncRequestIdInterceptor`: fill
  `X-Request-Id` with a `uuid4()` when missing.
- `_AuditInterceptor` / `_AsyncAuditInterceptor`: time the call
  with `monotonic()` and emit an `HttpAuditEvent`; silently
  skip when `sink` is `None`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol
from uuid import uuid4

from .errors import HttpError, safe_url
from .models import HttpRequest, HttpResponse, header_value

SyncNext = Callable[[HttpRequest], HttpResponse]
AsyncNext = Callable[[HttpRequest], Awaitable[HttpResponse]]


class HttpInterceptor(Protocol):
    """同步链上的一个有序切面步骤。

    English
    --------
    One synchronous, ordered call-aspect step.
    """

    def intercept(self, request: HttpRequest, proceed: SyncNext) -> HttpResponse:
        """transform / observe / 显式 short-circuit 一个请求。

        English
        --------
        Transform, observe, or explicitly short-circuit a request.
        """


class AsyncHttpInterceptor(Protocol):
    """异步链上的一个有序切面步骤。

    English
    --------
    One asynchronous, ordered call-aspect step.
    """

    async def intercept(self, request: HttpRequest, proceed: AsyncNext) -> HttpResponse:
        """transform / observe / 显式 short-circuit 一个请求。

        English
        --------
        Transform, observe, or explicitly short-circuit a request.
        """


@dataclass(frozen=True, slots=True)
class HttpAuditEvent:
    """不带 body/header 的交换记录，普通审计 sink 可安全消费。

    English
    --------
    A body- and header-free exchange record safe for ordinary
    audit sinks.
    """

    request_id: str | None
    method: str
    url: str
    status_code: int | None
    duration_ms: float
    error_type: str | None


class HttpAuditSink(Protocol):
    """消费方拥有的副作用端口，承载安全 HTTP 审计事件。

    English
    --------
    A consumer-owned side-effect port for safe HTTP audit events.
    """

    def record(self, event: HttpAuditEvent) -> None:
        """记录事件，但不接触请求/响应的 body 与 header。

        English
        --------
        Record an event without receiving request/response content
        or headers.
        """


class _RequestIdInterceptor:
    """同步版本的 request-id 填充拦截器。

    English
    --------
    Sync `request-id` filling interceptor.
    """

    def intercept(self, request: HttpRequest, proceed: SyncNext) -> HttpResponse:
        if header_value(request.headers, "X-Request-Id") is None:
            request = request.with_header("X-Request-Id", str(uuid4()))
        return proceed(request)


class _AsyncRequestIdInterceptor:
    """异步版本的 request-id 填充拦截器。

    English
    --------
    Async `request-id` filling interceptor.
    """

    async def intercept(self, request: HttpRequest, proceed: AsyncNext) -> HttpResponse:
        if header_value(request.headers, "X-Request-Id") is None:
            request = request.with_header("X-Request-Id", str(uuid4()))
        return await proceed(request)


class _AuditInterceptor:
    """同步版本的审计拦截器，封装计时 + 事件 dispatch。

    English
    --------
    Sync audit interceptor; encapsulates timing and event dispatch.
    """

    def __init__(self, sink: HttpAuditSink | None) -> None:
        self._sink = sink

    def intercept(self, request: HttpRequest, proceed: SyncNext) -> HttpResponse:
        started = monotonic()
        try:
            response = proceed(request)
        except Exception as error:
            self._record(request, None, started, error)
            raise
        self._record(request, response, started, None)
        return response

    def _record(self, request: HttpRequest, response: HttpResponse | None, started: float, error: Exception | None) -> None:
        if self._sink is None:
            return
        self._sink.record(
            HttpAuditEvent(
                request_id=header_value(request.headers, "X-Request-Id"),
                method=request.method,
                url=safe_url(request.url),
                status_code=response.status_code if response else None,
                duration_ms=(monotonic() - started) * 1000,
                error_type=type(error).__name__ if error else None,
            )
        )


class _AsyncAuditInterceptor:
    """异步版本的审计拦截器，封装计时 + 事件 dispatch。

    English
    --------
    Async audit interceptor; encapsulates timing and event
    dispatch.
    """

    def __init__(self, sink: HttpAuditSink | None) -> None:
        self._sink = sink

    async def intercept(self, request: HttpRequest, proceed: AsyncNext) -> HttpResponse:
        started = monotonic()
        try:
            response = await proceed(request)
        except Exception as error:
            self._record(request, None, started, error)
            raise
        self._record(request, response, started, None)
        return response

    def _record(self, request: HttpRequest, response: HttpResponse | None, started: float, error: Exception | None) -> None:
        if self._sink is None:
            return
        self._sink.record(
            HttpAuditEvent(
                request_id=header_value(request.headers, "X-Request-Id"),
                method=request.method,
                url=safe_url(request.url),
                status_code=response.status_code if response else None,
                duration_ms=(monotonic() - started) * 1000,
                error_type=type(error).__name__ if error else None,
            )
        )
