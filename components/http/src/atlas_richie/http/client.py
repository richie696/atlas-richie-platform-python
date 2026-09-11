"""有状态客户端门面，以及隐藏在底层的单一 HTTPX transport 适配。
----
本模块是 `atlas_richie.http` 的执行入口，向业务层暴露两个对偶门面：

- `HttpClient`：同步门面。
- `AsyncHttpClient`：异步门面，与同步版共享同一份 value 模型
  （`HttpRequest` / `HttpResponse` / 流响应）以及同一份拦截器
  语义（`HttpInterceptor` / `AsyncHttpInterceptor`）。

两个门面的设计要点：

- 显式生命周期：`close()` / `aclose()` 关闭底层连接池，
  重复调用安全；亦支持 `with` / `async with` 上下文。
- 不可变请求：`HttpRequest` 自身不携带 client 引用，
  同一请求可被多个 client 复用。
- 拦截器链：用户拦截器顺序固定，内置 `_RequestIdInterceptor`
  与 `_AuditInterceptor` 永远位于最外层（最先生效）。
- 双管道：`execute` 与 `open_stream` 走同一条拦截器链，
  流式响应也走同样的 request-id + audit 切面。
- SSE 一等公民：`iter_sse` / `async iter_sse` 自动注入
  `Accept: text/event-stream` 头、要求 2xx、并在结束时关闭响应。
- HTTPX 隔离：业务层永不接触 `httpx.Client` / `httpx.AsyncClient`；
  所有 HTTPX 异常在 `_map_sync_error` / `_map_async_error` 边界被
  转译为 `HttpError` 体系。
- Body 上限：`max_response_bytes` 在流式读取时强制，超过即抛
  `HttpResponseLimitError`。

`client.py` 的私有部分：

- `_SyncInvocation` / `_AsyncInvocation`：链上的一节。
- `_HttpxClientFactory`：唯一的内部 HTTPX 构造点，**不是**
  provider SPI。

English
--------
Stateful client facades + the single hidden HTTPX transport
adapter.

This module is the execution entry point of `atlas_richie.http`.
It exposes two facades that share the same value model and the
same interceptor semantics:

- `HttpClient`: synchronous facade.
- `AsyncHttpClient`: async counterpart with the same surface.

Design highlights:

- Explicit lifecycle: `close()` / `aclose()` shut the underlying
  connection pool; repeated calls are safe. Context-manager
  form (`with` / `async with`) is supported.
- Immutable requests: `HttpRequest` carries no client reference;
  one request can be replayed by multiple clients.
- Interceptor chain: caller-supplied interceptors run in the
  configured order; the built-in `_RequestIdInterceptor` and
  `_AuditInterceptor` always sit at the outermost positions.
- Twin pipelines: `execute` and `open_stream` share the same
  chain, so streams go through the same request-id and audit
  aspects as one-shot calls.
- SSE first-class: `iter_sse` / `async iter_sse` auto-set
  `Accept: text/event-stream`, require a 2xx, and close the
  response on completion.
- HTTPX isolation: callers never see `httpx.Client` /
  `httpx.AsyncClient`. All HTTPX failures are translated into
  the `HttpError` hierarchy at the `_map_sync_error` /
  `_map_async_error` boundary.
- Body cap: `max_response_bytes` is enforced during streaming;
  `HttpResponseLimitError` is raised on overflow.

Private internals:

- `_SyncInvocation` / `_AsyncInvocation`: one link in the chain.
- `_HttpxClientFactory`: the sole internal HTTPX constructor,
  not a provider SPI.
"""

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
    """同步责任链上的一节。

    English
    --------
    One object in the synchronous responsibility chain.
    """

    def __init__(self, interceptor: HttpInterceptor, next_step: SyncNext) -> None:
        self._interceptor = interceptor
        self._next_step = next_step

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self._interceptor.intercept(request, self._next_step)


class _AsyncInvocation:
    """异步责任链上的一节。

    English
    --------
    One object in the asynchronous responsibility chain.
    """

    def __init__(self, interceptor: AsyncHttpInterceptor, next_step: AsyncNext) -> None:
        self._interceptor = interceptor
        self._next_step = next_step

    async def __call__(self, request: HttpRequest) -> HttpResponse:
        return await self._interceptor.intercept(request, self._next_step)


class _HttpxClientFactory:
    """唯一的内部 HTTPX 客户端构造点；不是 provider SPI。

    English
    --------
    The sole internal constructor for HTTPX clients; never a
    provider SPI.
    """

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
    """同步 HTTP 门面：显式生命周期 + 有序切面。

    English
    --------
    A synchronous HTTP facade with an explicit lifecycle and
    ordered aspects.
    """

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
        """按固定拦截器顺序执行一个不可变请求。

        English
        --------
        Execute one immutable request through the fixed
        interceptor order.
        """

        self._require_open()
        return self._pipeline(request)

    def send(self, request: HttpRequest) -> HttpResponse:
        """`execute` 的 Python-native 别名；`request` 不持有 client 引用。

        English
        --------
        Python-native alias for `execute`; the request owns no
        client reference.
        """

        return self.execute(request)

    def open_stream(self, request: HttpRequest) -> HttpStreamResponse:
        """打开响应流；走同一份 request-id / audit / 调用方切面。

        Raises:
            TypeError: 任意流式拦截器没有返回 `HttpStreamResponse` 时。

        English
        --------
        Open a response stream through the same request-id,
        audit, and caller aspects.
        """

        self._require_open()
        response = self._stream_pipeline(request)
        if not isinstance(response, HttpStreamResponse):
            raise TypeError("stream interceptors must return an HttpStreamResponse")
        return response

    def iter_sse(self, request: HttpRequest) -> Iterator[SseEvent]:
        """产出解析后的 SSE 事件；完成或失败时关闭 HTTP 响应。

        English
        --------
        Yield parsed SSE events and close the HTTP response on
        completion or failure.
        """

        prepared = request.with_header(_ACCEPT_HEADER, MediaType.EVENT_STREAM)
        with self.open_stream(prepared).require_success() as response:
            yield from _parse_sse(response.iter_bytes())

    def close(self) -> None:
        """关闭底层连接池；重复调用安全。

        English
        --------
        Close the underlying connection pool; repeated calls
        are safe.
        """

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
    """异步 HTTP 门面：与同步版共享同一份 value 模型与切面语义。

    English
    --------
    An asynchronous HTTP facade with the same values and aspect
    semantics.
    """

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
        """按固定拦截器顺序执行一个不可变请求。

        English
        --------
        Execute one immutable request through the fixed
        interceptor order.
        """

        self._require_open()
        return await self._pipeline(request)

    async def send(self, request: HttpRequest) -> HttpResponse:
        """`execute` 的 Python-native 别名；`request` 不持有 client 引用。

        English
        --------
        Python-native alias for `execute`; no client is hidden
        in request values.
        """

        return await self.execute(request)

    async def open_stream(self, request: HttpRequest) -> AsyncHttpStreamResponse:
        """打开异步响应流；走同一份 request-id / audit / 调用方切面。

        Raises:
            TypeError: 任意流式拦截器没有返回 `AsyncHttpStreamResponse` 时。

        English
        --------
        Open an async response stream through the same request
        aspects.
        """

        self._require_open()
        response = await self._stream_pipeline(request)
        if not isinstance(response, AsyncHttpStreamResponse):
            raise TypeError("stream interceptors must return an AsyncHttpStreamResponse")
        return response

    async def iter_sse(self, request: HttpRequest) -> AsyncIterator[SseEvent]:
        """异步产出解析后的 SSE 事件；完成或失败时关闭响应。

        English
        --------
        Yield parsed SSE events and close the response on
        completion or failure.
        """

        prepared = request.with_header(_ACCEPT_HEADER, MediaType.EVENT_STREAM)
        response = await self.open_stream(prepared)
        await response.require_success()
        async with response:
            async for event in _parse_async_sse(response.aiter_bytes()):
                yield event

    async def aclose(self) -> None:
        """关闭底层异步连接池；重复调用安全。

        English
        --------
        Close the underlying asynchronous connection pool;
        repeated calls are safe.
        """

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
