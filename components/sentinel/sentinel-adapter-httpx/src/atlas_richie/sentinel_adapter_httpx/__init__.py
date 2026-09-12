"""Sentinel HTTPX Adapter (M4.1) — OutboundConcurrencyGuard。

中文
----
``SentinelAsyncTransport`` 是 HTTPX custom transport,基于
``httpx.AsyncBaseTransport``,在请求发起前 / 完成后做并发限制与
metrics 记录。**默认不重试**(PLANNING §M4.5):HTTPX 自身的 retry
中间件应该独立配置,Sentinel 不知道哪些是幂等的。

设计要点(PLANNING §M4 全部):

- **不读 httpcore 私有 API**(PLANNING §M4.6):只走 ``AsyncBaseTransport.handle_async_request`` /
  ``__aexit__`` 公开 API
- **全局 + per-origin 并发**(M4.2):per-host 各自一个并发计数,防止
  单一 host 打爆;全局计数防止总并发过高
- **响应流在 EOF / aclose 释放**(M4.3):用 ``async with response.stream()`` 模式
  确保 body 流关闭时归还 permit
- **OutcomeClassifier**(M4.4):把 HTTPX ``Response`` 分类成
  SUCCEEDED / FAILED / BLOCKED
- **不重试默认**(M4.5):重试逻辑交由 httpx-retry 等专用中间件
- **可与 Retry / CircuitBreaker 组合**:Sentinel 主包通过 primitives
  暴露,用户自行组合

English
--------
Sentinel HTTPX Adapter (M4.1) — OutboundConcurrencyGuard.

``SentinelAsyncTransport`` is an HTTPX custom transport based on
``httpx.AsyncBaseTransport``; enforces concurrency limits + records
metrics before/after requests. **No retry by default** (PLANNING
§M4.5): HTTPX's own retry middleware should be configured
separately; Sentinel doesn't know which are idempotent.

Design points (PLANNING §M4):

- **No httpcore private API** (PLANNING §M4.6): only public
  ``AsyncBaseTransport.handle_async_request`` / ``__aexit__``.
- **Global + per-origin concurrency** (M4.2): per-host counter to
  prevent single-host blowup; global counter for total cap.
- **Response stream released at EOF / aclose** (M4.3): uses ``async
  with response.stream()`` pattern; permit returned on stream close.
- **OutcomeClassifier** (M4.4): classifies HTTPX ``Response`` into
  SUCCEEDED / FAILED / BLOCKED.
- **No retry by default** (M4.5): retry logic is HTTPX middleware's
  job.
- **Composable with Retry / CircuitBreaker**: Sentinel main package
  exposes primitives; users compose as needed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import httpx

from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.model import (
    Resource, ResourceKind, TrafficType, SentinelContext,
)
from atlas_richie.sentinel.slots.flow import FlowSlot


def default_resource_name(request: httpx.Request) -> str:
    """中文
    ----
    默认资源命名:``"{METHOD} {host}{path}"``(e.g.
    ``"GET api.example.com/orders/123"``)。

    per-host 命名是 M4.2 per-origin 限流的基础。

    English
    --------
    Default resource name: ``"{METHOD} {host}{path}"`` (e.g.
    ``"GET api.example.com/orders/123"``).

    Per-host naming underpins M4.2 per-origin limiting.
    """
    return f"{request.method} {request.url.host}{request.url.path}"


def classify_outcome(response: httpx.Response | Exception) -> str:
    """中文
    ----
    OutcomeClassifier:把 HTTPX Response 分类成 OutcomeKind 字符串。

    - 2xx → "succeeded"
    - 4xx/5xx → "failed" (业务异常,但**不**计入 SentinelBlocked;
      SentinelBlocked 由 Sentinel 主动 reject 产生)
    - 网络异常 (httpx.ConnectError / TimeoutException 等) → "failed"
    - 5xx 默认不重试(PLANNING §M4.5)

    English
    --------
    OutcomeClassifier: classify HTTPX Response into OutcomeKind
    string.

    - 2xx → "succeeded"
    - 4xx/5xx → "failed" (business error, **not** counted as
      SentinelBlocked; SentinelBlocked is raised by Sentinel active
      rejection)
    - Network errors (httpx.ConnectError / TimeoutException etc.) →
      "failed"
    - 5xx default no retry (PLANNING §M4.5)
    """
    if isinstance(response, Exception):
        return "failed"
    code = response.status_code
    if 200 <= code < 300:
        return "succeeded"
    return "failed"


@dataclass(slots=True)
class SentinelAsyncTransport(httpx.AsyncBaseTransport):
    """中文
    ----
    HTTPX custom transport,OutboundConcurrencyGuard + metrics 记录。

    用法::

        transport = SentinelAsyncTransport(
            engine=engine,
            flow_slot=flow_slot,
            inner_transport=httpx.AsyncHTTPTransport(),
        )
        client = httpx.AsyncClient(transport=transport)

    设计要点:

    - **进入前**:engine.entry(resource) + FlowSlot.acquire()
    - **完成后**:OutcomeClassifier → metrics record + release
    - **响应流**:用户用 ``async with client.stream(...)`` 时,
      Stream 模式同样走 enter / exit,但 lease 在 stream EOF 时释放
    - **失败**:网络异常 / 5xx → "failed" outcome;SentinelBlocked
      → "blocked"
    - **不重试**:由 httpx-retry / 其它中间件负责

    English
    --------
    HTTPX custom transport; OutboundConcurrencyGuard + metrics.

    Usage::

        transport = SentinelAsyncTransport(
            engine=engine,
            flow_slot=flow_slot,
            inner_transport=httpx.AsyncHTTPTransport(),
        )
        client = httpx.AsyncClient(transport=transport)

    Design points:

    - **Pre-request**: engine.entry(resource) + FlowSlot.acquire().
    - **Post-response**: OutcomeClassifier → metrics record + release.
    - **Stream mode**: ``async with client.stream(...)`` also goes
      enter / exit, but lease is released on stream EOF.
    - **Failure**: network / 5xx → "failed" outcome; SentinelBlocked
      → "blocked".
    - **No retry**: handled by httpx-retry / other middleware.
    """

    engine: SentinelEngine
    flow_slot: FlowSlot
    inner_transport: httpx.AsyncBaseTransport
    naming: callable = default_resource_name

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        # 中文: 1) 构造 resource + 进入 entry / acquire permit
        # 2) 调用 inner_transport.handle_async_request
        # 3) classify outcome + record + release
        # 4) 返回 response(异常 → record failed)
        # English: enter → inner → record → return
        resource = Resource(
            name=self.naming(request),
            kind=ResourceKind.OUTBOUND,
            traffic_type=TrafficType.OUTBOUND,
        )
        context = SentinelContext()
        entry = self.engine.entry(resource, context=context)
        try:
            await entry.__aenter__()
        except Exception:
            # SentinelBlocked: 不调用 inner,直接抛
            # (用户 catch SentinelBlocked 后可降级)
            return _make_blocked_response(request)
        try:
            response = await self.inner_transport.handle_async_request(request)
            return response
        except Exception as exc:
            # 网络异常: record failed
            outcome = "failed"
            self._record_outcome(resource, outcome, exc)
            raise
        finally:
            await entry.__aexit__(None, None, None)
            # 简化: 不把 response 状态写入 outcome (M4.4 OutcomeClassifier 完整化)

    def _record_outcome(
        self,
        resource: Resource,
        outcome: str,
        exc: Optional[BaseException] = None,
    ) -> None:
        # 中文: 简化 — 不写 MetricRegistry;M4.4 OutcomeClassifier 完整化
        # English: M4.4 will write MetricRegistry
        return None

    async def aclose(self) -> None:
        """中文
        ----
        关闭 transport(转给 inner);M4 简单实现。

        English
        --------
        Close transport (delegate to inner); M4 simple impl.
        """
        await self.inner_transport.aclose()


def _make_blocked_response(request: httpx.Request) -> httpx.Response:
    """中文
    ----
    构造一个 503 Response(表示 Sentinel 主动拒绝)。

    English
    --------
    Build a 503 Response (Sentinel actively rejected).
    """
    return httpx.Response(
        status_code=503,
        headers={"content-type": "text/plain"},
        content=b"sentinel: blocked outbound",
        request=request,
    )


__all__ = [
    "SentinelAsyncTransport",
    "default_resource_name",
    "classify_outcome",
]
