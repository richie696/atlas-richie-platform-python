"""Atlas Richie Sentinel Dashboard v2 (M6.6).

中文
----
per-process 嵌入管理 API + HTML UI (Web 管理页面).

``SentinelDashboard`` (Facade) 聚合 ``SentinelEngine`` /
``MetricRegistry`` / ``RuleRepository`` (主包 1.0 公共 API) 为单一管理
入口, 启动 uvicorn ASGI server 暴露 6 JSON API + 6 HTML 页面 + 1 SSE:

- JSON API (backward compat):
  - ``GET /health`` — 进程健康
  - ``GET /metrics`` — MetricRegistry snapshots
  - ``GET /rules`` — 当前生效规则
  - ``GET /rules/{rule_id}`` — 单个 rule
  - ``GET /state`` — engine state + in_flight + last_error + rules_count
  - ``POST /admin/rules/reload`` — 触发 RuleSource reload
  - ``POST /admin/breaker/{rule_id}/reset`` — DegradeSlot.force_reset
- HTML 页面:
  - ``GET /`` — dashboard 总览
  - ``GET /rules`` — 规则列表
  - ``GET /rules/{rule_id}`` — 规则详情
  - ``GET /metrics`` — 实时 metrics (SSE 5s 推送)
  - ``GET /settings`` — dashboard 配置
  - ``GET /audit`` — 审计日志
- SSE:
  - ``GET /sse/metrics`` — 5s 推一次 metrics snapshot
- Static:
  - ``/static/*`` — CSS / JS / favicon

设计要点 (M6.6 v2, 详见 ``docs/process/M6.6-DASHBOARD-AGGREGATOR-EVAL.md``):

- **Facade**: 1 个 ``SentinelDashboard`` 对象 = 1 个 admin 入口
- **Decorator**: admin 鉴权 + audit log 中间件 (Starlette Middleware)
- **依赖 (extension wheel, 主包 0 3rd-party 不变)**:
  - Starlette + Jinja2 + uvicorn (开发) / hypercorn (生产, optional)
- **Bind**: 127.0.0.1 默认 (loopback, M6.7 ADR-SEN-018 决策一致)
- **不做**:
  - 不出 ``sentinel-dashboard-aggregator`` (跨进程聚合, 留 1.x 候选)
  - 不出 Collector Python (Java/Go 服务端独立仓)

English
--------
Per-process embedded admin API + HTML UI (Web admin page).

``SentinelDashboard`` is a Facade aggregating ``SentinelEngine`` /
``MetricRegistry`` / ``RuleRepository`` into a single admin entry,
running uvicorn ASGI server exposing 6 JSON APIs + 6 HTML pages +
1 SSE + static files.

Designed for per-process use: 1 engine + 1 dashboard, loopback bind
by default. Cross-process aggregator is deferred to 1.x candidate.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from .app import build_app
from .state import DashboardState


@dataclass(slots=True)
class SentinelDashboard:
    """per-process Web 管理页面 (HTML + JSON).

    中文
    ----
    ``start()`` 在后台 task 启动 uvicorn server (loopback only by
    default). ``aclose()`` 优雅关闭 (drain + cancel task).

    1 个 ``SentinelDashboard`` 实例 = 1 个 Facade. 不支持同进程多
    dashboard (port 冲突 + 1 engine 1 dashboard 是 1.0 设计).

    English
    --------
    ``start()`` launches uvicorn server in background task (loopback
    only by default). ``aclose()`` graceful shutdown.

    1 ``SentinelDashboard`` instance = 1 Facade. Multiple dashboards
    in same process not supported (port conflict + 1-engine-1-dashboard
    is 1.0 design).
    """

    engine: Any  # SentinelEngine
    metric_registry: Any  # MetricRegistry
    rule_repository: Any  # RuleRepository
    rule_source: Optional[Any] = None  # RuleSource (admin reload 用)
    degrade_slot: Optional[Any] = None  # DegradeSlot (admin reset 用)
    host: str = "127.0.0.1"
    port: int = 8719
    allow_admin: bool = False
    admin_token: str = ""
    audit_log: list = field(default_factory=list)
    _state: Optional[DashboardState] = field(default=None, init=False, repr=False)
    _app: Any = field(default=None, init=False, repr=False)
    _server: Any = field(default=None, init=False, repr=False)
    _task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)

    async def start(self) -> None:
        """启动 ASGI server (后台 task)."""
        if self._task is not None:
            return
        import uvicorn

        self._state = DashboardState(
            engine=self.engine,
            metric_registry=self.metric_registry,
            rule_repository=self.rule_repository,
            rule_source=self.rule_source,
            degrade_slot=self.degrade_slot,
            host=self.host,
            port=self.port,
            allow_admin=self.allow_admin,
            admin_token=self.admin_token,
            audit_log=self.audit_log,
        )
        self._app = build_app(self._state)
        # 把 state 注入 app.state, route handlers 从 request.app.state.dashboard 拿
        self._app.state.dashboard = self._state
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(
            self._server.serve(), name="sentinel-dashboard"
        )
        # 等 server 启动 (poll 状态)
        for _ in range(100):  # max 5s
            await asyncio.sleep(0.05)
            if self._server.started:
                return
        # 启动失败
        if not self._server.started:
            await self.aclose()
            raise RuntimeError(
                f"SentinelDashboard failed to start on {self.host}:{self.port}"
            )

    async def aclose(self) -> None:
        """关闭 ASGI server (graceful)."""
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
            self._task = None
        self._server = None
        self._app = None
        self._state = None


__all__ = ["SentinelDashboard", "DashboardState"]
