"""End-to-end HTTP tests for `atlas-richie-http` (R-M6 E.1).

中文
----
真实服务器 + 真实客户端调用的端到端测试集。每条用例都走完整的
ASGI / HTTPX pipeline(拦截器 + 切面 + transport),**不**走受控
transport mock。

策略:

- **大多数用例**用 `httpx.ASGITransport` 跑在进程内:零网络往返,
  但**全** ASGI 生命周期是真实的。所有用例都走 `AsyncHttpClient`,
  因为 `ASGITransport` 只支持 async context manager(同步
  `httpx.Client` 不能 `with` 一个 `ASGITransport`)。
- **2 条用例**用 `uvicorn` 子进程:验证 `python -m uvicorn` 在
  真实 TCP 端口上能起来、被本组件的 `HttpClient` 调通。这一档
  涵盖 timeout 之类的网络层行为(`ASGITransport` 不强制 timeout,
  只能借真实 socket 验证)。

`pytest -m e2e` 跑全套,`pytest -m "not e2e"` 跳过。

English
--------
End-to-end tests for `atlas-richie-http` (R-M6 E.1).

This file exercises the **real** ASGI / HTTPX pipeline: the
client's interceptor chain, the request-id / audit built-ins,
and the transport adapter all run. No `MockTransport`.

Strategy:

- Most tests use `httpx.ASGITransport` for in-process execution:
  no real network round-trip, but the **full** ASGI lifecycle
  is real. Fast, deterministic, and CI-friendly. All in-process
  tests use `AsyncHttpClient` because `ASGITransport` only
  supports the async context-manager protocol (a sync
  `httpx.Client` cannot `with` an `ASGITransport`).
- Two tests use a real `uvicorn` subprocess bound to a TCP
  port. This is the only way to assert behaviours that depend
  on a real socket, such as timeout enforcement
  (`ASGITransport` does not enforce `httpx.Timeout`).

Every test is `@pytest.mark.e2e`. The `e2e_helpers` sub-package
hosts the FastAPI app, the uvicorn boot helper, and the
interceptors used by these tests.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

from atlas_richie.http import (
    AsyncHttpClient,
    HttpClient,
    HttpRequest,
    HttpResponse,
    HttpStatusError,
    HttpTimeout,
    HttpTimeoutError,
)

from .e2e_helpers.interceptors import (
    HeaderInjectInterceptor,
    RequestIdCaptureInterceptor,
)
from .e2e_helpers.server import pick_free_port, run_uvicorn, wait_for_port
from .e2e_helpers.test_app import create_app, reset_counter

# Skip the whole module if the optional ASGI/uvicorn test stack is
# unavailable. The e2e_helpers import `fastapi`, which is a
# dev-only dependency.
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


pytestmark = pytest.mark.e2e


# Absolute path to the tests/ directory; used to tell the
# `uvicorn` subprocess where to find the test app (the app is
# not part of the published `atlas_richie.http` source tree).
_TESTS_DIR = str(Path(__file__).resolve().parent)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def in_process_app() -> Iterator[Any]:
    """Yield a fresh FastAPI app, scoped per test.

    中文
    ----
    每个测试拿到一份独立的 FastAPI app,这样 `/counted` 的进程
    计数不会跨测试泄漏。`reset_counter` 在入口处也再清一次,
    双保险。

    English
    --------
    Each test gets its own `app` so router state (`/counted`'s
    counter) does not leak between tests. `reset_counter` clears
    the process-local counter on the way in, too — belt and
    braces.
    """
    reset_counter()
    yield create_app()


@pytest.fixture
def async_app_client(in_process_app: Any) -> Iterator[AsyncHttpClient]:
    """Yield an `AsyncHttpClient` whose transport is the in-process app.

    中文
    ----
    直接给 `AsyncHttpClient._client` 装一个 `ASGITransport` 绑到
    测试 app 上。`_client` 是模块私有属性,但 `test_http_client.py`
    已经用同样的方式注入受控 transport — 这是组件**留给测试的
    唯一注入点**(对照 `_HttpxClientFactory`)。

    English
    --------
    Replace `AsyncHttpClient._client` with an `httpx.AsyncClient`
    bound to the in-process ASGI app. `_client` is private but
    `test_http_client.py` already uses the same seam to inject
    `MockTransport` — the unit tests' injection pattern is the
    same one we use here for `ASGITransport`.
    """
    transport = httpx.ASGITransport(app=in_process_app)
    client = AsyncHttpClient()
    client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=transport, base_url="http://testserver"
    )
    try:
        yield client
    finally:
        # The injected `httpx.AsyncClient` is bound to no real
        # network; the `ASGITransport` was constructed without
        # external resources. We skip the `aclose()` (which
        # would require an event loop the sync fixture does
        # not own) and rely on GC for cleanup. This matches
        # the unit tests' behaviour for `MockTransport`.
        pass


def _run(coro: Any) -> Any:
    """Run a coroutine to completion on a fresh event loop.

    中文
    ----
    同步 pytest 用例 → 异步 client 调用的桥梁。组件测试没装
    `pytest-asyncio`,所以用 `asyncio.run` 自己跑。

    English
    --------
    Bridge sync pytest tests to async client calls. The
    project does not use `pytest-asyncio`, so we run the
    coroutine ourselves.
    """
    return asyncio.run(coro)


# ── 1. Server boot + GET request ────────────────────────────────────


def test_server_serves_get_request(async_app_client: AsyncHttpClient) -> None:
    """ASGI boot + a real `AsyncHttpClient.execute` GET round-trip.

    中文
    ----
    进程内 ASGI 服务器 + `AsyncHttpClient.execute` 真发一次 GET,
    断言 200 与 JSON body。

    English
    --------
    Spin up the in-process ASGI app, send a real GET through
    `AsyncHttpClient.execute`, and assert the response status +
    body.
    """

    async def _call() -> HttpResponse:
        return await async_app_client.execute(
            HttpRequest.get("http://testserver/hello")
        )

    response = _run(_call())
    assert response.status_code == 200
    assert response.is_success is True
    assert response.json() == {"hello": "world"}


# ── 2. POST request with JSON body ──────────────────────────────────


def test_post_with_json_body_round_trips(async_app_client: AsyncHttpClient) -> None:
    """POST a JSON body and assert the FastAPI `/echo` echoes it back.

    中文
    ----
    通过 `HttpRequest.json(...)` 构造带 JSON body 的 POST,服务器
    `/echo` 原样回写,断言往返一致。

    English
    --------
    Build a POST via `HttpRequest.json(...)`, send it through
    the in-process transport, and assert the server returned
    the same JSON.
    """
    payload = {"key": "value", "nested": {"list": [1, 2, 3]}}
    request = HttpRequest.json("POST", "http://testserver/echo", payload)

    async def _call() -> HttpResponse:
        return await async_app_client.execute(request)

    response = _run(_call())
    assert response.status_code == 200
    assert response.json() == payload
    # The Content-Type should have been auto-set on the way out.
    assert "application/json" in request.headers.get("Content-Type", "")


# ── 3. Interceptor chain in a real request ─────────────────────────


def test_interceptor_chain_adds_header_visible_in_response(
    in_process_app: Any,
) -> None:
    """Custom interceptor writes a header; the server reflects it back.

    中文
    ----
    装一个 `HeaderInjectInterceptor`,它在每个出站请求上写
    `X-E2E-Marker`。服务器 `/reflect-headers` 把收到的头原样
    回写,断言响应里出现 `X-E2E-Marker` 即可证明拦截器真的写
    到了 HTTPX 的请求对象上。同时 `RequestIdCaptureInterceptor`
    断言 `_RequestIdInterceptor` 也跑了(`X-Request-Id` 非空)。

    English
    --------
    Install a `HeaderInjectInterceptor` that writes
    `X-E2E-Marker` on every outbound request. The server's
    `/reflect-headers` echoes inbound headers; the assertion
    proves the interceptor's `with_header` actually reached
    the HTTPX request. `RequestIdCaptureInterceptor` additionally
    proves the built-in `_RequestIdInterceptor` ran.
    """
    transport = httpx.ASGITransport(app=in_process_app)
    header_injector = HeaderInjectInterceptor()
    id_capture = RequestIdCaptureInterceptor()

    async def _call() -> HttpResponse:
        async with AsyncHttpClient(
            interceptors=(id_capture, header_injector)
        ) as client:
            client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
                transport=transport, base_url="http://testserver"
            )
            return await client.execute(
                HttpRequest.get("http://testserver/reflect-headers")
            )

    response = _run(_call())
    assert response.status_code == 200
    echoed = response.json()
    assert echoed.get("x-e2e-marker") == "e2e-marker", (
        f"interceptor should have injected X-E2E-Marker; got headers: {echoed!r}"
    )
    assert echoed.get("x-request-id"), (
        "built-in _RequestIdInterceptor should populate X-Request-Id"
    )
    assert id_capture.record, (
        "RequestIdCaptureInterceptor should have observed X-Request-Id"
    )


# ── 4. Timeout handling (real uvicorn) ──────────────────────────────


def test_real_uvicorn_subprocess_enforces_client_timeout() -> None:
    """A real uvicorn socket is required for `HttpTimeout` to fire.

    中文
    ----
    `httpx.ASGITransport` 不会强制 `HttpTimeout`,所以 timeout
    用例必须用真的 uvicorn 子进程:启动 → 50 ms 客户端读超时 →
    `/slow?ms=200` → 断言 `HttpTimeoutError`。

    English
    --------
    `httpx.ASGITransport` does not enforce `httpx.Timeout`, so
    this test boots a real uvicorn subprocess, sends a request
    with a 50 ms read budget to a 200 ms handler, and asserts
    the client raises `HttpTimeoutError`.
    """
    port = pick_free_port()
    with run_uvicorn(
        "e2e_helpers.test_app:app",
        port=port,
        app_dir=_TESTS_DIR,
    ) as proc:
        assert wait_for_port("127.0.0.1", port, timeout=10.0), (
            f"uvicorn did not bind to 127.0.0.1:{port} within 10s "
            f"(pid={proc.pid}, exit={proc.poll()})"
        )

        client = HttpClient()
        try:
            request = (
                HttpRequest.get(f"http://127.0.0.1:{port}/slow")
                .with_query_param("ms", "200")
                .with_timeout(
                    HttpTimeout(connect=2.0, read=0.05, write=2.0, pool=2.0)
                )
            )
            with pytest.raises(HttpTimeoutError):
                client.execute(request)
        finally:
            client.close()


# ── 5. Error response propagation ───────────────────────────────────


def test_server_error_response_propagates_status_code(
    async_app_client: AsyncHttpClient,
) -> None:
    """The /error endpoint returns 500; the client surfaces the status.

    中文
    ----
    服务器 `/error` 返回 500 + JSON body;客户端 `is_success`
    判定为 False,`require_success()` 抛 `HttpStatusError`;body
    仍可被 `.json()` 解析。

    English
    --------
    The `/error` route returns 500 with a JSON body. The
    client reports `is_success = False`; `require_success()`
    raises `HttpStatusError`; the body is still parseable via
    `.json()`.
    """

    async def _call() -> HttpResponse:
        return await async_app_client.execute(
            HttpRequest.get("http://testserver/error")
        )

    response = _run(_call())
    assert response.status_code == 500
    assert response.is_success is False
    with pytest.raises(HttpStatusError) as excinfo:
        response.require_success()
    assert excinfo.value.status_code == 500
    assert response.json() == {"error": "boom", "code": "internal"}


# ── 6. Concurrent requests ──────────────────────────────────────────


def test_ten_concurrent_requests_all_succeed(in_process_app: Any) -> None:
    """10 concurrent requests hit /counted; the server really saw 10.

    中文
    ----
    10 个并发 GET `/counted` 走 `AsyncHttpClient` +
    `asyncio.gather`;服务器 `/counted` 用进程内计数证明确实
    被命中 10 次(transport 不会去重/合并)。

    English
    --------
    10 concurrent GETs to `/counted` via `AsyncHttpClient` and
    `asyncio.gather`. The server's per-process counter proves
    the transport didn't dedupe or coalesce the calls.
    """
    transport = httpx.ASGITransport(app=in_process_app)

    async def _run_concurrent() -> list[int]:
        async with AsyncHttpClient() as client:
            client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
                transport=transport, base_url="http://testserver"
            )

            async def hit() -> int:
                response = await client.execute(
                    HttpRequest.get("http://testserver/counted")
                )
                payload = response.json()
                return int(payload["hits"])

            return await asyncio.gather(*(hit() for _ in range(10)))

    results = _run(_run_concurrent())
    assert len(results) == 10
    # The /counted endpoint uses a thread-safe counter, so the
    # hits must be 1..10 in some order, with no duplicates and
    # no skipped values.
    assert sorted(results) == list(range(1, 11))


# ── 7. Streaming / chunked response ─────────────────────────────────


def test_streaming_response_chunks_concatenate(in_process_app: Any) -> None:
    """`open_stream` reads a chunked response chunk-by-chunk.

    中文
    ----
    服务器 `/chunked?n=4` 产生 4 段 chunk;客户端
    `AsyncHttpClient.open_stream` → `aiter_bytes()` 一段段读,
    拼起来与 `"chunk-0\\n...chunk-3\\n"` 完全一致。

    English
    --------
    The server's `/chunked?n=4` emits 4 chunks; the client
    consumes them via `AsyncHttpClient.open_stream` →
    `aiter_bytes()` and the concatenation matches the expected
    full body.
    """
    transport = httpx.ASGITransport(app=in_process_app)

    async def _consume() -> list[bytes]:
        async with AsyncHttpClient() as client:
            client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
                transport=transport, base_url="http://testserver"
            )
            stream = await client.open_stream(
                HttpRequest.get("http://testserver/chunked").with_query_param("n", "4")
            )
            async with stream:
                await stream.require_success()
                chunks: list[bytes] = []
                async for chunk in stream.aiter_bytes():
                    chunks.append(chunk)
            return chunks

    chunks = _run(_consume())
    body = b"".join(chunks)
    expected = b"".join(f"chunk-{i}\n".encode("utf-8") for i in range(4))
    assert body == expected
    assert len(chunks) >= 1, "StreamingResponse should yield at least one chunk"


# ── 8. Real-uvicorn smoke (in addition to the timeout test) ────────


def test_real_uvicorn_subprocess_serves_get_request() -> None:
    """Smoke: uvicorn can boot the test app and the client can hit it.

    中文
    ----
    启动 `uvicorn e2e_helpers.test_app:app` (with `--app-dir`
    指向 `tests/`),等端口可连,然后 `HttpClient.execute` 一次
    真 GET。失败的话至少能定位到 `python -m uvicorn` 路径/依
    赖问题。

    English
    --------
    Boot `uvicorn e2e_helpers.test_app:app` (with `--app-dir`
    pointing at `tests/`), wait until the port accepts
    connections, and make a real `HttpClient.execute` GET. A
    failure here pinpoints a `python -m uvicorn` / FastAPI
    wiring problem rather than a transport regression.
    """
    port = pick_free_port()
    with run_uvicorn(
        "e2e_helpers.test_app:app",
        port=port,
        app_dir=_TESTS_DIR,
    ) as proc:
        assert wait_for_port("127.0.0.1", port, timeout=10.0), (
            f"uvicorn did not bind to 127.0.0.1:{port} within 10s "
            f"(pid={proc.pid}, exit={proc.poll()})"
        )

        client = HttpClient()
        try:
            response: HttpResponse = client.execute(
                HttpRequest.get(f"http://127.0.0.1:{port}/hello")
            )
        finally:
            client.close()

    assert response.status_code == 200
    assert response.json() == {"hello": "world"}
