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
    - 支持 ``?max=N`` query param 限制最大推送次数 (默认无限制)
    - 支持 ``?interval=Xs`` query param 覆盖推送间隔 (默认 5s, 测试
      用 ``?interval=0.01s`` 加速验证多 event 流式)

    English
    --------
    Implementation: first push immediate, then every 5s. Client
    disconnect via asyncio.CancelledError. Supports ``?max=N`` and
    ``?interval=Xs`` query params for testability.
    """
    state: DashboardState = request.app.state.dashboard

    # 解析 ?max=N
    max_events: int | None = None
    raw_max = request.query_params.get("max")
    if raw_max is not None:
        try:
            max_events = max(1, int(raw_max))
        except ValueError:
            max_events = None

    # 解析 ?interval=Xs (默认 SSE_INTERVAL_S)
    interval_s: float = SSE_INTERVAL_S
    raw_interval = request.query_params.get("interval")
    if raw_interval is not None:
        try:
            # 兼容 "0.01s" / "0.01" 格式
            cleaned = raw_interval.rstrip("s").strip()
            parsed = float(cleaned)
            if parsed > 0:
                interval_s = parsed
        except (ValueError, AttributeError):
            interval_s = SSE_INTERVAL_S

    async def event_stream():
        try:
            count = 0
            # 第一次立即推
            yield _format_metrics_event(state, asyncio.get_event_loop().time())
            count += 1
            if max_events is not None and count >= max_events:
                return
            # 后续每 interval_s 推
            while True:
                await asyncio.sleep(interval_s)
                yield _format_metrics_event(state, asyncio.get_event_loop().time())
                count += 1
                if max_events is not None and count >= max_events:
                    return
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
