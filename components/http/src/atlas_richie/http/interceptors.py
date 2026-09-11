"""Explicit ordered interceptor contracts and audit-safe events."""

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
    """One synchronous, ordered call-aspect step."""

    def intercept(self, request: HttpRequest, proceed: SyncNext) -> HttpResponse:
        """Transform, observe, or explicitly short-circuit a request."""


class AsyncHttpInterceptor(Protocol):
    """One asynchronous, ordered call-aspect step."""

    async def intercept(self, request: HttpRequest, proceed: AsyncNext) -> HttpResponse:
        """Transform, observe, or explicitly short-circuit a request."""


@dataclass(frozen=True, slots=True)
class HttpAuditEvent:
    """A body- and header-free exchange record safe for ordinary audit sinks."""

    request_id: str | None
    method: str
    url: str
    status_code: int | None
    duration_ms: float
    error_type: str | None


class HttpAuditSink(Protocol):
    """A consumer-owned side-effect port for safe HTTP audit events."""

    def record(self, event: HttpAuditEvent) -> None:
        """Record an event without receiving request/response content or headers."""


class _RequestIdInterceptor:
    def intercept(self, request: HttpRequest, proceed: SyncNext) -> HttpResponse:
        if header_value(request.headers, "X-Request-Id") is None:
            request = request.with_header("X-Request-Id", str(uuid4()))
        return proceed(request)


class _AsyncRequestIdInterceptor:
    async def intercept(self, request: HttpRequest, proceed: AsyncNext) -> HttpResponse:
        if header_value(request.headers, "X-Request-Id") is None:
            request = request.with_header("X-Request-Id", str(uuid4()))
        return await proceed(request)


class _AuditInterceptor:
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
