"""Atlas Richie Sentinel Dashboard v2 单元测试 (M6.6.1-3).

中文
----
覆盖 6 JSON API + 6 HTML 页面 + 1 SSE + admin 鉴权 + audit log:

1. JSON API (backward compat): /health /metrics /rules /rules/{id} /state
2. Admin JSON: /admin/rules/reload /admin/breaker/{id}/reset
3. HTML pages: / /rules /rules/{id} /metrics /settings /audit
4. SSE: /sse/metrics
5. Admin auth middleware: 缺 token / 错 token → 403 + audit
6. Audit log: cap 1000
"""
from __future__ import annotations

import asyncio
import json
import unittest

from atlas_richie.sentinel_dashboard import SentinelDashboard


class _FakeRegistry:
    """Mock MetricRegistry - 返回固定 snapshots."""

    def iter_snapshots(self):
        class _Snap:
            def __init__(self, labels, admitted, blocked, succeeded, failed, cancelled, avg_rt_ns):
                self.labels = labels
                self.admitted = admitted
                self.blocked = blocked
                self.succeeded = succeeded
                self.failed = failed
                self.cancelled = cancelled
                self.avg_rt_ns = avg_rt_ns
        return [
            _Snap({"resource": "/api/v1"}, admitted=10, blocked=2, succeeded=8, failed=1, cancelled=0, avg_rt_ns=1234567),
        ]


class _FakeIndex:
    def __init__(self, rules):
        self._rules = rules

    def __len__(self):
        return len(self._rules)

    def snapshot_rules(self):
        return dict(self._rules)


class _FakeRuleRepo:
    def __init__(self):
        self.current_index = _FakeIndex({
            "flow-api-v1": {"kind": "flow", "threshold": 100},
        })


class _FakeEngine:
    def __init__(self):
        from atlas_richie.sentinel.model.enums import EngineState
        self.state = EngineState.READY
        self.in_flight = 0
        self.last_error = None


def _make_dashboard(**kwargs):
    """构造测试用 SentinelDashboard, 跳过 start() (test 用 ASGI 直接调)."""
    defaults = dict(
        engine=_FakeEngine(),
        metric_registry=_FakeRegistry(),
        rule_repository=_FakeRuleRepo(),
        host="127.0.0.1",
        port=18719,
        allow_admin=True,
        admin_token="test-token",
    )
    defaults.update(kwargs)
    return SentinelDashboard(**defaults)


def _build_asgi(dashboard: SentinelDashboard):
    """构造 ASGI app (不启动 server, 走 httpx AsyncClient)."""
    from atlas_richie.sentinel_dashboard.app import build_app
    from atlas_richie.sentinel_dashboard.state import DashboardState

    state = DashboardState(
        engine=dashboard.engine,
        metric_registry=dashboard.metric_registry,
        rule_repository=dashboard.rule_repository,
        rule_source=dashboard.rule_source,
        degrade_slot=dashboard.degrade_slot,
        host=dashboard.host,
        port=dashboard.port,
        allow_admin=dashboard.allow_admin,
        admin_token=dashboard.admin_token,
        audit_log=dashboard.audit_log,
    )
    app = build_app(state)
    app.state.dashboard = state
    return app


class JsonApiTest(unittest.IsolatedAsyncioTestCase):
    """6 JSON API (backward compat)."""

    async def test_health(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/health")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["engine_state"], "ready")
            self.assertEqual(data["in_flight"], 0)

    async def test_metrics(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/metrics")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["admitted"], 10)

    async def test_rules(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/rules")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("flow-api-v1", data)

    async def test_rule_detail(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/rules/flow-api-v1")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("flow-api-v1", data)

    async def test_rule_not_found(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/rules/nonexistent")
            self.assertEqual(r.status_code, 404)

    async def test_state(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/state")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["engine_state"], "ready")
            self.assertEqual(data["rules_count"], 1)


class AdminAuthTest(unittest.IsolatedAsyncioTestCase):
    """admin 鉴权 + audit log."""

    async def test_no_token_denied(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/admin/rules/reload")
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json()["error"], "missing bearer")
            # audit log 记录 denied
            self.assertEqual(len(dashboard.audit_log), 1)
            self.assertEqual(dashboard.audit_log[0].op, "denied")

    async def test_invalid_token_denied(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/admin/rules/reload",
                headers={"Authorization": "Bearer wrong-token"},
            )
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json()["error"], "invalid token")

    async def test_valid_token_passes_to_handler(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()  # no rule_source
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/admin/rules/reload",
                headers={"Authorization": "Bearer test-token"},
            )
            # 400 因为 no rule_source configured (handler 错误, 不是 auth 错误)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"], "no rule_source configured")
            # audit log 记录 admin
            self.assertEqual(len(dashboard.audit_log), 1)
            self.assertEqual(dashboard.audit_log[0].op, "admin")

    async def test_admin_disabled_denied(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard(allow_admin=False, admin_token="")
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post(
                "/admin/rules/reload",
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json()["error"], "admin disabled")


class AuditLogTest(unittest.IsolatedAsyncioTestCase):
    """audit log cap 1000."""

    def test_audit_log_capped_at_1000(self) -> None:
        from atlas_richie.sentinel_dashboard.routes.json_api import AdminAuthMiddleware, _AuditEntry
        import time

        from atlas_richie.sentinel_dashboard.state import DashboardState

        audit_log: list = []
        state = DashboardState(
            engine=_FakeEngine(),
            metric_registry=_FakeRegistry(),
            rule_repository=_FakeRuleRepo(),
            rule_source=None,
            degrade_slot=None,
            host="127.0.0.1",
            port=18719,
            allow_admin=True,
            admin_token="t",
            audit_log=audit_log,
        )
        # 加 1500 条
        for i in range(1500):
            AdminAuthMiddleware._audit(state, "admin", "127.0.0.1", f"op {i}")
        self.assertEqual(len(state.audit_log), 1000)
        # 应该是最后 1000 条
        self.assertEqual(state.audit_log[0].detail, "op 500")
        self.assertEqual(state.audit_log[-1].detail, "op 1499")


class HtmlPageTest(unittest.IsolatedAsyncioTestCase):
    """6 HTML 页面."""

    async def test_dashboard_page(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/")
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/html", r.headers["content-type"])
            self.assertIn("Atlas Richie Sentinel", r.text)
            self.assertIn("ready", r.text)

    async def test_rules_page(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/dashboard/rules")
            self.assertEqual(r.status_code, 200)
            self.assertIn("flow-api-v1", r.text)

    async def test_rule_detail_page(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/dashboard/rules/flow-api-v1")
            self.assertEqual(r.status_code, 200)
            self.assertIn("flow-api-v1", r.text)

    async def test_rule_detail_not_found(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/dashboard/rules/nonexistent")
            self.assertEqual(r.status_code, 404)
            self.assertIn("not found", r.text)

    async def test_metrics_page(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/dashboard/metrics")
            self.assertEqual(r.status_code, 200)
            self.assertIn("EventSource", r.text)
            self.assertIn("/sse/metrics", r.text)

    async def test_settings_page(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/dashboard/settings")
            self.assertEqual(r.status_code, 200)
            self.assertIn("127.0.0.1", r.text)
            self.assertIn("18719", r.text)

    async def test_audit_page(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/dashboard/audit")
            self.assertEqual(r.status_code, 200)
            self.assertIn("Audit Log", r.text)

    async def test_static_css(self) -> None:
        from httpx import AsyncClient, ASGITransport
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/static/style.css")
            self.assertEqual(r.status_code, 200)
            self.assertIn("text/css", r.headers["content-type"])
            self.assertIn("--bg", r.text)


class SseTest(unittest.TestCase):
    """SSE 实时推送 (用 Starlette TestClient 同步流式读取).

    中文
    ----
    ``starlette.testclient.TestClient`` 用 ``requests`` 同步库, 通过
    WSGI/ASGI 桥接调用, 跟 ASGITransport + 异步生成器 + pytest-asyncio
    组合不同, 可以稳定读取流式响应. 验证:
    - 200 + content-type: text/event-stream
    - 立即推 1 条 event (第 1 个 yield 在 sleep 之前)
    - event 格式: ``event: metrics\\ndata: <json>\\n\\n``
    - data 字段含 snaps + ts
    - ``?max=N`` query 限制最大推送次数 (1 条验证 immediate push,
      2 条验证后续 push)

    English
    --------
    Uses Starlette TestClient (sync via ``requests``) instead of
    ASGITransport (async) to avoid pytest-asyncio hang. Verifies:
    endpoint, content-type, immediate 1st event, format, JSON content,
    ``?max=N`` cap.
    """

    def test_sse_endpoint_immediate_push(self) -> None:
        """GET /sse/metrics?max=1 — 立即推 1 条 event."""
        from starlette.testclient import TestClient
        import json as _json
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        with TestClient(app) as client:
            with client.stream("GET", "/sse/metrics?max=1") as r:
                self.assertEqual(r.status_code, 200)
                self.assertIn("text/event-stream", r.headers["content-type"])
                # TestClient 同步读取, max=1 立即终止
                collected = ""
                for line in r.iter_lines():
                    collected += line + "\n"
                # 验证 event + data 格式
                self.assertIn("event: metrics", collected)
                self.assertIn("data: ", collected)
                # 解析 data 行 JSON
                for line in collected.split("\n"):
                    if line.startswith("data: "):
                        data = _json.loads(line[len("data: "):])
                        self.assertIn("snaps", data)
                        self.assertIn("ts", data)
                        self.assertEqual(len(data["snaps"]), 1)
                        self.assertEqual(data["snaps"][0]["admitted"], 10)
                        return
                self.fail(f"no data: line found in collected: {collected!r}")

    def test_sse_endpoint_max_events(self) -> None:
        """GET /sse/metrics?max=3&interval=0.01s — 验证 max=N + interval 限制."""
        from starlette.testclient import TestClient
        import json as _json
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        with TestClient(app) as client:
            # interval=0.01s 加速, max=3 限制 (1 immediate + 2 follow-up)
            with client.stream("GET", "/sse/metrics?max=3&interval=0.01s") as r:
                self.assertEqual(r.status_code, 200)
                collected = ""
                for line in r.iter_lines():
                    collected += line + "\n"
                # 计数 event 出现次数
                event_count = collected.count("event: metrics")
                self.assertEqual(event_count, 3, f"expected 3 events, got {event_count}: {collected!r}")
                # 验证每条 event 都有 data
                data_count = collected.count("data: ")
                self.assertEqual(data_count, 3)

    def test_sse_endpoint_max_invalid(self) -> None:
        """GET /sse/metrics?max=invalid — 降级为无限制 (不抛错, 立即 push 1 条).

        中文
        ----
        用 ``?max=1&interval=invalid`` 验证 interval 降级 + max=1 立即终止.
        max=invalid 不能测 (会无限循环, 任何客户端 cap 都受 transport
        buffer 限制).
        """
        from starlette.testclient import TestClient
        dashboard = _make_dashboard()
        app = _build_asgi(dashboard)
        with TestClient(app) as client:
            # interval=invalid 降级为默认 5s, 但 max=1 立即终止 (1 条 event)
            with client.stream(
                "GET", "/sse/metrics?max=1&interval=invalid"
            ) as r:
                self.assertEqual(r.status_code, 200)
                collected = ""
                for line in r.iter_lines():
                    collected += line + "\n"
                # 1 条 event (max=1 立即终止)
                self.assertEqual(collected.count("event: metrics"), 1)


if __name__ == "__main__":
    unittest.main()
