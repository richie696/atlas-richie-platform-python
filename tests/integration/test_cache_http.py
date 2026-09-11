"""集成测试：cache + http（cache-aside 响应缓存）。

中文
----
验证 `RedisProviderRegistrar` 与 `atlas_richie.http.HttpClient` 拦截器链
可以一起工作，把"重复请求"分流到缓存：

- 写一个 `CacheResponseInterceptor` 作为 `HttpInterceptor`：命中
  `value_ops.get(key, bytes)` → 直接返回 `HttpResponse`，不调用
  `proceed`；未命中 → 调 `proceed` 拿到响应 → 写入缓存 → 返回。
- 用 `unittest.mock.patch` 替换 `_HttpxClientFactory.create_sync`，
  走 `httpx.MockTransport` 模拟远端 200 OK（**不发起真实网络请求**）。
- 关键断言：
  - 第一次请求：MockTransport 被调用一次，body = "remote-v1"。
  - 第二次请求：MockTransport **仍然只被调用一次**（被拦截器短路
    走缓存），body 仍是 "remote-v1"。
  - 缓存被 invalidate 后：MockTransport 被调用两次，body 变成
    "remote-v2"。
  - cache miss（key 不在缓存中）：MockTransport 被调用，缓存被写。

该测试展示了"两个组件边界"：拦截器是 http 的扩展点；缓存是 cache
的扩展点；通过把缓存的 `get` / `set` 嫁接在拦截器的
`intercept(request, proceed)` 闭包上，证明二者协作无侵入。

English
--------
Integration test: cache + http (cache-aside response cache).

Verifies that `RedisProviderRegistrar` and the `atlas_richie.http`
interceptor chain can cooperate so that repeated requests are
short-circuited to the cache:

- A `CacheResponseInterceptor` implements `HttpInterceptor`: cache
  hit → return a `HttpResponse` without calling `proceed`; cache
  miss → call `proceed`, write the response body to the cache, then
  return.
- The HTTPX transport is swapped via `unittest.mock.patch` over
  `_HttpxClientFactory.create_sync`, with an `httpx.MockTransport`
  standing in for the remote (no real network).
- Key assertions:
  - 1st call: MockTransport invoked once, body = "remote-v1".
  - 2nd call: MockTransport still invoked exactly once (cache
    short-circuited the 2nd call), body still "remote-v1".
  - After invalidating the cache, the MockTransport is invoked a
    2nd time, and the body changes to "remote-v2".
  - Cache miss path: MockTransport invoked, cache is populated.

Demonstrates the clean composition: the interceptor is the http
extension point; the cache is the cache extension point; bridging
them requires only the `intercept(request, proceed)` closure shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from atlas_richie.http import (
    HttpClient,
    HttpRequest,
    HttpResponse,
    HttpResponseLimitError,
)

pytestmark = pytest.mark.integration


# ── Test-local helpers ─────────────────────────────────────────────


class _TrackingTransport(httpx.MockTransport):
    """`httpx.MockTransport` subclass that records every dispatched
    request and returns a versioned body, so we can assert call
    counts and observe cache short-circuiting behaviour.

    The body version is mutable so a test can flip the response
    between calls (used by `test_invalidation_re_populates_the_cache`).
    Inherits `handle_request` / `close` from `httpx.MockTransport`.
    """

    def __init__(self, body_version: list[str]) -> None:
        self.body_version = body_version
        self.calls: list[httpx.Request] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        version = self.body_version[0]
        return httpx.Response(
            200,
            content=f"remote-{version}".encode("utf-8"),
            request=request,
        )


class _CacheResponseInterceptor:
    """Http-side cache-aside interceptor backed by `value_ops`."""

    def __init__(self, value_ops: Any, namespace: str) -> None:
        self._value_ops = value_ops
        self._namespace = namespace
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _cache_key(request: HttpRequest) -> str:
        # Method + URL is enough for a non-`Vary`-aware cache; the
        # assertion only checks short-circuiting, not correctness
        # across many distinct URLs.
        return f"{request.method}|{request.url}"

    def intercept(self, request: HttpRequest, proceed: Any) -> HttpResponse:
        cache_key = f"{self._namespace}:{self._cache_key(request)}"
        cached = self._value_ops.get(cache_key, bytes)
        if cached is not None:
            self.hits += 1
            return HttpResponse(
                status_code=200,
                headers={},
                body=cached,
                method=request.method,
                url=request.url,
            )
        self.misses += 1
        response = proceed(request)
        # Only cache successful 200 responses.
        if 200 <= response.status_code < 300:
            self._value_ops.set_with_ttl(
                cache_key, response.body, timeout_millis=60_000
            )
        return response


# ── Tests ──────────────────────────────────────────────────────────


class TestCacheAsResponseCache:
    """Cache-aside behaviour over the http interceptor chain."""

    def test_second_call_is_short_circuited_by_cache(
        self,
        installed_registrar: Any,
        controlled_http_client: Any,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        transport = _TrackingTransport(body_version=["v1"])
        interceptor = _CacheResponseInterceptor(
            value_ops, namespace="http-test"
        )

        with controlled_http_client(transport):
            client = HttpClient(interceptors=(interceptor,))
            try:
                # First call: cache miss → MockTransport invoked.
                first = client.execute(HttpRequest.get("https://unit.test/v1"))
                # Second call: cache hit → MockTransport not invoked again.
                second = client.execute(HttpRequest.get("https://unit.test/v1"))
            finally:
                client.close()

        assert first.body == b"remote-v1"
        assert second.body == b"remote-v1"
        assert len(transport.calls) == 1, (
            "second call must be served from cache, not the network"
        )
        assert interceptor.hits == 1
        assert interceptor.misses == 1

    def test_invalidation_re_populates_the_cache(
        self,
        installed_registrar: Any,
        controlled_http_client: Any,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        transport = _TrackingTransport(body_version=["v1", "v2"])
        interceptor = _CacheResponseInterceptor(
            value_ops, namespace="http-test"
        )

        with controlled_http_client(transport):
            client = HttpClient(interceptors=(interceptor,))
            try:
                client.execute(HttpRequest.get("https://unit.test/v2"))
                # Invalidate the cached entry and re-issue.
                key = interceptor._cache_key(HttpRequest.get("https://unit.test/v2"))
                key_ops.remove_cache(f"http-test:{key}")
                transport.body_version[0] = "v2"
                again = client.execute(HttpRequest.get("https://unit.test/v2"))
            finally:
                client.close()

        assert again.body == b"remote-v2"
        assert len(transport.calls) == 2, (
            "after cache invalidation, the network must be hit again"
        )

    def test_different_urls_get_different_cache_entries(
        self,
        installed_registrar: Any,
        controlled_http_client: Any,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        transport = _TrackingTransport(body_version=["v1"])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=f"remote-{request.url.path}".encode("utf-8"),
                request=request,
            )

        # Replace the pre-built transport with a per-URL body.
        transport = httpx.MockTransport(handler)
        interceptor = _CacheResponseInterceptor(
            value_ops, namespace="http-test"
        )

        with controlled_http_client(transport):
            client = HttpClient(interceptors=(interceptor,))
            try:
                a1 = client.execute(HttpRequest.get("https://unit.test/a"))
                a2 = client.execute(HttpRequest.get("https://unit.test/a"))
                b1 = client.execute(HttpRequest.get("https://unit.test/b"))
                b2 = client.execute(HttpRequest.get("https://unit.test/b"))
            finally:
                client.close()

        # Each unique URL was fetched exactly once; the 2nd is a hit.
        assert a1.body == b"remote-/a"
        assert a2.body == b"remote-/a"
        assert b1.body == b"remote-/b"
        assert b2.body == b"remote-/b"
        # 4 execute() calls → 2 cache hits + 2 misses.
        assert interceptor.hits == 2
        assert interceptor.misses == 2

    def test_http_request_response_models_survive_a_round_trip(
        self,
        installed_registrar: Any,
        controlled_http_client: Any,
    ) -> None:
        """Sanity: the `HttpRequest` / `HttpResponse` models (the
        integration layer for cache + http) keep their immutable
        `with_header` / `with_query` semantics when handed to the
        interceptor chain.
        """
        value_ops = installed_registrar.value_ops()
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={"echo": request.headers["X-Request-Id"]},
                request=request,
            )

        interceptor = _CacheResponseInterceptor(
            value_ops, namespace="http-test"
        )
        with controlled_http_client(httpx.MockTransport(handler)):
            client = HttpClient(interceptors=(interceptor,))
            try:
                request = HttpRequest.get("https://unit.test/json").with_query_param(
                    "q", "1"
                )
                response = client.execute(request)
            finally:
                client.close()

        # The response is parsed cleanly off the wire.
        body: Mapping[str, str] = response.json()
        assert body["echo"] == captured[0].headers["X-Request-Id"]
        assert captured[0].url.query.decode() == "q=1"

    def test_response_limit_is_unaffected_by_interceptor_short_circuit(
        self,
        installed_registrar: Any,
        controlled_http_client: Any,
    ) -> None:
        """When the cache serves the body, the response-limit
        enforcement doesn't run (no network I/O). The interceptor
        returns the cached bytes directly.
        """
        value_ops = installed_registrar.value_ops()
        # Pre-populate the cache with a body larger than the limit.
        # (We use a known key so the interceptor's hash is stable.)
        url = "https://unit.test/large"
        request = HttpRequest.get(url)
        cache_key = (
            f"http-test:{_CacheResponseInterceptor._cache_key(request)}"
        )
        value_ops.set_with_ttl(cache_key, b"x" * 100, timeout_millis=60_000)

        # Transport would raise HttpResponseLimitError if called.
        def handler(req: httpx.Request) -> httpx.Response:
            raise HttpResponseLimitError(  # type: ignore[misc]
                "transport invoked, but the cache should have "
                "short-circuited this request",
                method=req.method,
                url=str(req.url),
            )

        interceptor = _CacheResponseInterceptor(
            value_ops, namespace="http-test"
        )
        with controlled_http_client(httpx.MockTransport(handler)):
            client = HttpClient(interceptors=(interceptor,))
            try:
                response = client.execute(request)
            finally:
                client.close()

        assert response.body == b"x" * 100
        assert interceptor.hits == 1
        assert interceptor.misses == 0
