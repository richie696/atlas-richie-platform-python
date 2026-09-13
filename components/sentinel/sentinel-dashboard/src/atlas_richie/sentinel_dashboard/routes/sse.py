"""Atlas Richie Sentinel Dashboard v2 — SSE 实时推送.

中文
----
``GET /sse/metrics`` 用 Server-Sent Events 每 5s 推一次 metrics snapshot.

设计:
- Content-Type: text/event-stream
- 每条 event: ``event: metrics\\ndata: <json>\\n\\n``
- 客户端断开 (asyncio.CancelledError) 优雅退出

注意: 1.0 SSE 用纯 async generator, 跟 Starlette 1.6.0 + ASGITransport
测试客户端兼容性有问题 (具体原因待查, 可能是 starlette 版本);
生产用浏览器 EventSource 客户端验证. 1.0 测试只验证 endpoint 注册
+ content-type, 不验证流式内容 (内容验证留 v1.x 跨语言 SDK 阶段).

English
--------
``GET /sse/metrics`` streams metrics snapshot every 5s via Server-Sent
Events. Client disconnect via asyncio.CancelledError.

Note: 1.0 SSE uses pure async generator, may have compatibility
issues with Starlette 1.6.0 + ASGITransport test client (under
investigation); production validation via browser EventSource. 1.0
tests only verify endpoint registration + content-type, not
streaming content.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import StreamingResponse

from ..state import DashboardState


SSE_INTERVAL_S = 5.0


def _format_metrics_event(state: DashboardState, ts: float) -> str:
    """构造 1 条 SSE event."""
    snaps = state.metric_registry.iter_snapshots()
    payload = {
        "ts": ts,
        "snaps": [
            {
                "labels": dict(snap.labels),
                "admitted": snap.admitted,
                "blocked": snap.blocked,
                "succeeded": snap.succeeded,
                "failed": snap.failed,
                "cancelled": snap.cancelled,
                "avg_rt_ns": snap.avg_rt_ns,
            }
            for snap in snaps
        ],
    }
    return f"event: metrics\ndata: {json.dumps(payload)}\n\n"


async def sse_metrics(request: Request) -> StreamingResponse:
    """GET /sse/metrics — 每 5s 推一次 metrics snapshot.

    中文
    ----
    实现:
    - 第一次立即推 (避免客户端等 5s)
    - 后续每 5s 推
    - 客户端断开 (asyncio.CancelledError) 优雅退出

    English
    --------
    Implementation: first push immediate, then every 5s. Client
    disconnect via asyncio.CancelledError.
    """
    state: DashboardState = request.app.state.dashboard

    async def event_stream():
        try:
            # 第一次立即推
            yield _format_metrics_event(state, asyncio.get_event_loop().time())
            # 后续每 5s 推
            while True:
                await asyncio.sleep(SSE_INTERVAL_S)
                yield _format_metrics_event(state, asyncio.get_event_loop().time())
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
