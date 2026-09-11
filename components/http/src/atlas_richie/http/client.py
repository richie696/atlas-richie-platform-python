"""Stateful client facades and their single hidden HTTPX transport adapter."""

from __future__ import annotations

from codecs import getincrementaldecoder
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from typing import TypeVar

import httpx

from .errors import (
    HttpClientClosedError,
    HttpConnectError,
    HttpError,
    HttpProtocolError,
    HttpResponseLimitError,
    HttpTimeoutError,
    HttpTransportError,
)
from .interceptors import (
    AsyncHttpInterceptor,
    AsyncNext,
    HttpAuditSink,
    HttpInterceptor,
    SyncNext,
    _AsyncAuditInterceptor,
    _AsyncRequestIdInterceptor,
    _AuditInterceptor,
    _RequestIdInterceptor,
)
from .models import (
    AsyncHttpStreamResponse,
    HttpClientOptions,
    HttpRequest,
    HttpResponse,
    HttpStreamResponse,
    HttpTimeout,
    MediaType,
)
from .sse import SseEvent, SseEventParser

_T = TypeVar("_T")
_ACCEPT_HEADER = "Accept"
_UTF_8 = "utf-8"


class _SyncInvocation:
    """One object in the synchronous responsibility chain."""

    def __init__(self, interceptor: HttpInterceptor, next_step: SyncNext) -> None:
        self._interceptor = interceptor
        self._next_step = next_step

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self._interceptor.intercept(request, self._next_step)


class _AsyncInvocation:
    """One object in the asynchronous responsibility chain."""

    def __init__(self, interceptor: AsyncHttpInterceptor, next_step: AsyncNext) -> None:
        self._interceptor = interceptor
        self._next_step = next_step

    async def __call__(self, request: HttpRequest) -> HttpResponse:
        return await self._interceptor.intercept(request, self._next_step)


class _HttpxClientFactory:
    """The sole internal constructor for HTTPX clients; never a provider SPI."""

    @staticmethod
    def create_sync(options: HttpClientOptions) -> httpx.Client:
        return httpx.Client(
            headers=dict(options.headers),
            timeout=_httpx_timeout(options.timeout),
            limits=httpx.Limits(
                max_connections=options.max_connections,
                max_keepalive_connections=options.max_keepalive_connections,
            ),
            follow_redirects=options.follow_redirects,
        )

    @staticmethod
    def create_async(options: HttpClientOptions) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=dict(options.headers),
            timeout=_httpx_timeout(options.timeout),
            limits=httpx.Limits(
                max_connections=options.max_connections,
                max_keepalive_connections=options.max_keepalive_connections,
            ),
            follow_redirects=options.follow_redirects,
        )


class HttpClient:
    """A synchronous HTTP facade with an explicit lifecycle and ordered aspects."""

    def __init__(
        self,
        options: HttpClientOptions | None = None,
        *,
        interceptors: Sequence[HttpInterceptor] = (),
        audit_sink: HttpAuditSink | None = None,
    ) -> None:
        self._options = options or HttpClientOptions()
        self._client = _HttpxClientFactory.create_sync(self._options)
        self._closed = False
        self._pipeline = self._build_pipeline(tuple(interceptors), audit_sink, self._execute_transport)
        self._stream_pipeline = self._build_pipeline(tuple(interceptors), audit_sink, self._open_stream_transport)

    def execute(self, request: HttpRequest) -> HttpResponse:
        """Execute one immutable request through the fixed interceptor order."""

        self._require_open()
        return self._pipeline(request)

    def send(self, request: HttpRequest) -> HttpResponse:
        """Python-native alias for `execute`; the request owns no client reference."""

        return self.execute(request)

    def open_stream(self, request: HttpRequest) -> HttpStreamResponse:
        """Open a response stream through the same request-id, audit, and caller aspects."""

        self._require_open()
        response = self._stream_pipeline(request)
        if not isinstance(response, HttpStreamResponse):
            raise TypeError("stream interceptors must return an HttpStreamResponse")
        return response

    def iter_sse(self, request: HttpRequest) -> Iterator[SseEvent]:
        """Yield parsed SSE events and close the HTTP response on completion or failure."""

        prepared = request.with_header(_ACCEPT_HEADER, MediaType.EVENT_STREAM)
        with self.open_stream(prepared).require_success() as response:
            yield from _parse_sse(response.iter_bytes())

    def close(self) -> None:
        """Close the underlying connection pool; repeated calls are safe."""

        if not self._closed:
            self._client.close()
            self._closed = True

    def __enter__(self) -> "HttpClient":
        self._require_open()
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise HttpClientClosedError("HTTP client is closed")

    def _build_pipeline(
        self,
        interceptors: tuple[HttpInterceptor, ...],
        audit_sink: HttpAuditSink | None,
        terminal: SyncNext,
    ) -> SyncNext:
        pipeline: SyncNext = terminal
        for interceptor in reversed(interceptors):
            pipeline = _SyncInvocation(interceptor, pipeline)
        pipeline = _SyncInvocation(_AuditInterceptor(audit_sink), pipeline)
        return _SyncInvocation(_RequestIdInterceptor(), pipeline)

    def _execute_transport(self, request: HttpRequest) -> HttpResponse:
        def execute() -> HttpResponse:
            prepared = self._client.build_request(
                request.method,
                request.url,
                headers=dict(request.headers),
                content=request.content,
                params=list(request.query),
                timeout=_httpx_timeout(request.timeout) if request.timeout else None,
            )
            response = self._client.send(
                prepared,
                stream=True,
            )
            try:
                body = _read_sync_body(response, self._options.max_response_bytes, request)
                return HttpResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body=body,
                    method=request.method,
                    url=str(response.url),
                )
            finally:
                response.close()
        return _map_sync_error(request, execute)

    def _open_stream_transport(self, request: HttpRequest) -> HttpStreamResponse:
        def execute() -> HttpStreamResponse:
            prepared = self._client.build_request(
                request.method,
                request.url,
                headers=dict(request.headers),
                content=request.content,
                params=list(request.query),
                timeout=_httpx_timeout(request.timeout) if request.timeout else None,
            )
            response = self._client.send(prepared, stream=True)
            return HttpStreamResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                method=request.method,
                url=str(response.url),
                iter_bytes=response.iter_bytes,
                close=response.close,
            )
        return _map_sync_error(request, execute)


class AsyncHttpClient:
    """An asynchronous HTTP facade with the same values and aspect semantics."""

    def __init__(
        self,
        options: HttpClientOptions | None = None,
        *,
        interceptors: Sequence[AsyncHttpInterceptor] = (),
        audit_sink: HttpAuditSink | None = None,
    ) -> None:
        self._options = options or HttpClientOptions()
        self._client = _HttpxClientFactory.create_async(self._options)
        self._closed = False
        self._pipeline = self._build_pipeline(tuple(interceptors), audit_sink, self._execute_transport)
        self._stream_pipeline = self._build_pipeline(tuple(interceptors), audit_sink, self._open_stream_transport)

    async def execute(self, request: HttpRequest) -> HttpResponse:
        """Execute one immutable request through the fixed interceptor order."""

        self._require_open()
        return await self._pipeline(request)

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Python-native alias for `execute`; no client is hidden in request values."""

        return await self.execute(request)

    async def open_stream(self, request: HttpRequest) -> AsyncHttpStreamResponse:
        """Open an async response stream through the same request aspects."""

        self._require_open()
        response = await self._stream_pipeline(request)
        if not isinstance(response, AsyncHttpStreamResponse):
            raise TypeError("stream interceptors must return an AsyncHttpStreamResponse")
        return response

    async def iter_sse(self, request: HttpRequest) -> AsyncIterator[SseEvent]:
        """Yield parsed SSE events and close the response on completion or failure."""

        prepared = request.with_header(_ACCEPT_HEADER, MediaType.EVENT_STREAM)
        response = await self.open_stream(prepared)
        await response.require_success()
        async with response:
            async for event in _parse_async_sse(response.aiter_bytes()):
                yield event

    async def aclose(self) -> None:
        """Close the underlying asynchronous connection pool; repeated calls are safe."""

        if not self._closed:
            await self._client.aclose()
            self._closed = True

    async def __aenter__(self) -> "AsyncHttpClient":
        self._require_open()
        return self

    async def __aexit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        await self.aclose()

    def _require_open(self) -> None:
        if self._closed:
            raise HttpClientClosedError("HTTP client is closed")

    def _build_pipeline(
        self,
        interceptors: tuple[AsyncHttpInterceptor, ...],
        audit_sink: HttpAuditSink | None,
        terminal: AsyncNext,
    ) -> AsyncNext:
        pipeline: AsyncNext = terminal
        for interceptor in reversed(interceptors):
            pipeline = _AsyncInvocation(interceptor, pipeline)
        pipeline = _AsyncInvocation(_AsyncAuditInterceptor(audit_sink), pipeline)
        return _AsyncInvocation(_AsyncRequestIdInterceptor(), pipeline)

    async def _execute_transport(self, request: HttpRequest) -> HttpResponse:
        async def execute() -> HttpResponse:
            prepared = self._client.build_request(
                request.method,
                request.url,
                headers=dict(request.headers),
                content=request.content,
                params=list(request.query),
                timeout=_httpx_timeout(request.timeout) if request.timeout else None,
            )
            response = await self._client.send(
                prepared,
                stream=True,
            )
            try:
                body = await _read_async_body(response, self._options.max_response_bytes, request)
                return HttpResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body=body,
                    method=request.method,
                    url=str(response.url),
                )
            finally:
                await response.aclose()
        return await _map_async_error(request, execute)

    async def _open_stream_transport(self, request: HttpRequest) -> AsyncHttpStreamResponse:
        async def execute() -> AsyncHttpStreamResponse:
            prepared = self._client.build_request(
                request.method,
                request.url,
                headers=dict(request.headers),
                content=request.content,
                params=list(request.query),
                timeout=_httpx_timeout(request.timeout) if request.timeout else None,
            )
            response = await self._client.send(prepared, stream=True)
            return AsyncHttpStreamResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                method=request.method,
                url=str(response.url),
                iter_bytes=response.aiter_bytes,
                close=response.aclose,
            )
        return await _map_async_error(request, execute)


def _httpx_timeout(timeout: HttpTimeout) -> httpx.Timeout:
    return httpx.Timeout(connect=timeout.connect, read=timeout.read, write=timeout.write, pool=timeout.pool)


def _read_sync_body(response: httpx.Response, limit: int, request: HttpRequest) -> bytes:
    chunks: list[bytes] = []
    received = 0
    for chunk in response.iter_bytes():
        received += len(chunk)
        if received > limit:
            raise HttpResponseLimitError(limit, method=request.method, url=request.url)
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_async_body(response: httpx.Response, limit: int, request: HttpRequest) -> bytes:
    chunks: list[bytes] = []
    received = 0
    async for chunk in response.aiter_bytes():
        received += len(chunk)
        if received > limit:
            raise HttpResponseLimitError(limit, method=request.method, url=request.url)
        chunks.append(chunk)
    return b"".join(chunks)


def _map_sync_error(request: HttpRequest, action: Callable[[], _T]) -> _T:
    try:
        return action()
    except HttpError:
        raise
    except httpx.TimeoutException as error:
        raise HttpTimeoutError("HTTP request timed out", method=request.method, url=request.url) from error
    except httpx.ConnectError as error:
        raise HttpConnectError("HTTP connection failed", method=request.method, url=request.url) from error
    except (httpx.RemoteProtocolError, httpx.LocalProtocolError, httpx.DecodingError) as error:
        raise HttpProtocolError("HTTP protocol failure", method=request.method, url=request.url) from error
    except httpx.HTTPError as error:
        raise HttpTransportError("HTTP transport failure", method=request.method, url=request.url) from error


async def _map_async_error(request: HttpRequest, action: Callable[[], Awaitable[_T]]) -> _T:
    try:
        return await action()
    except HttpError:
        raise
    except httpx.TimeoutException as error:
        raise HttpTimeoutError("HTTP request timed out", method=request.method, url=request.url) from error
    except httpx.ConnectError as error:
        raise HttpConnectError("HTTP connection failed", method=request.method, url=request.url) from error
    except (httpx.RemoteProtocolError, httpx.LocalProtocolError, httpx.DecodingError) as error:
        raise HttpProtocolError("HTTP protocol failure", method=request.method, url=request.url) from error
    except httpx.HTTPError as error:
        raise HttpTransportError("HTTP transport failure", method=request.method, url=request.url) from error


def _parse_sse(chunks: Iterator[bytes]) -> Iterator[SseEvent]:
    parser = SseEventParser()
    for line in _decode_sse_lines(chunks):
        event = parser.feed(line)
        if event is not None:
            yield event
    event = parser.flush()
    if event is not None:
        yield event


async def _parse_async_sse(chunks: AsyncIterator[bytes]) -> AsyncIterator[SseEvent]:
    parser = SseEventParser()
    async for line in _decode_async_sse_lines(chunks):
        event = parser.feed(line)
        if event is not None:
            yield event
    event = parser.flush()
    if event is not None:
        yield event


def _decode_sse_lines(chunks: Iterator[bytes]) -> Iterator[str]:
    decoder = getincrementaldecoder(_UTF_8)()
    buffered = ""
    for chunk in chunks:
        buffered += decoder.decode(chunk)
        *lines, buffered = buffered.split("\n")
        yield from (line.removesuffix("\r") for line in lines)
    buffered += decoder.decode(b"", final=True)
    if buffered:
        yield buffered.removesuffix("\r")


async def _decode_async_sse_lines(chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
    decoder = getincrementaldecoder(_UTF_8)()
    buffered = ""
    async for chunk in chunks:
        buffered += decoder.decode(chunk)
        *lines, buffered = buffered.split("\n")
        for line in lines:
            yield line.removesuffix("\r")
    buffered += decoder.decode(b"", final=True)
    if buffered:
        yield buffered.removesuffix("\r")
