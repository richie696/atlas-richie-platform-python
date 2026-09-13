"""Atlas Richie Sentinel Dashboard v2 — Starlette ASGI app 构造.

中文
----
``build_app`` 把 routes / templates / static / auth 装配成 Starlette ASGI
app, 供 ``SentinelDashboard`` 启动 uvicorn server 时使用.

设计要点 (M6.6 v2):

- **Facade**: 1 个 ``SentinelDashboard`` 对象 = 1 个 admin 入口
  (SentinelEngine + MetricRegistry + RuleRepository 聚合)
- **Decorator (Starlette Middleware)**: admin 鉴权 + audit log 中间件
- **不**用其它 GoF 模式 (1.0 单策略, 简单路由 + 模板足够, 评估见
  ``docs/process/M6.6-DASHBOARD-AGGREGATOR-EVAL.md`` v2 §2.5)
- **依赖**: Starlette + Jinja2 + uvicorn (extension wheel, 主包 0 3rd-party 不变)

English
--------
``build_app`` assembles routes / templates / static / auth into a
Starlette ASGI app, used by ``SentinelDashboard`` when starting uvicorn.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .routes.html_pages import (
    audit_page,
    dashboard_page,
    metrics_page,
    rule_detail_page,
    rules_page,
    settings_page,
)
from .routes.json_api import (
    health_json,
    metrics_json,
    rules_json,
    rule_json,
    state_json,
    admin_reload_rules,
    admin_reset_breaker,
    AdminAuthMiddleware,
)
from .routes.sse import sse_metrics
from .state import DashboardState


# 模板目录: 相对当前文件
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def build_templates() -> Jinja2Templates:
    """构造 Jinja2Templates (templates 目录).

    中文
    ----
    autoescape HTML/XML, 避免 XSS; ``request`` 全局可用, 模板里
    ``request.state.dashboard`` 访问共享状态.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    templates = Jinja2Templates(env=env)
    return templates


def build_app(state: DashboardState) -> Starlette:
    """构造 Starlette ASGI app (装配 routes + middleware).

    中文
    ----
    路由分组:
    - 6 JSON API (backward compat): /health /metrics /rules /rules/{id} /state
    - 2 admin JSON API: /admin/rules/reload /admin/breaker/{id}/reset
    - 1 SSE: /sse/metrics
    - 6 HTML 页面: / /rules /rules/{id} /metrics /settings /audit
    - 1 static: /static/* (CSS / JS / favicon)
    """
    templates = build_templates()

    # Pass shared state into route handlers via closure
    json_routes = [
        Route("/health", endpoint=health_json, methods=["GET"]),
        Route("/metrics", endpoint=metrics_json, methods=["GET"]),
        Route("/rules", endpoint=rules_json, methods=["GET"]),
        Route("/rules/{rule_id}", endpoint=rule_json, methods=["GET"]),
        Route("/state", endpoint=state_json, methods=["GET"]),
        Route(
            "/admin/rules/reload",
            endpoint=admin_reload_rules,
            methods=["POST"],
        ),
        Route(
            "/admin/breaker/{rule_id}/reset",
            endpoint=admin_reset_breaker,
            methods=["POST"],
        ),
        Route("/sse/metrics", endpoint=sse_metrics, methods=["GET"]),
    ]

    # HTML pages with templates
    # Note: HTML 页面用独立路径 (dashboard / dashboard/rules / dashboard/metrics /
    # dashboard/settings / dashboard/audit) 避免跟 JSON API (/metrics /rules) 冲突.
    def make_html_handler(handler):
        """Wrap HTML handler to inject templates + state."""
        async def wrapped(request):
            return await handler(
                request, state=state, templates=templates
            )
        return wrapped

    html_routes = [
        Route(
            "/",
            endpoint=make_html_handler(dashboard_page),
            methods=["GET"],
        ),
        Route(
            "/dashboard",
            endpoint=make_html_handler(dashboard_page),
            methods=["GET"],
        ),
        Route(
            "/dashboard/rules",
            endpoint=make_html_handler(rules_page),
            methods=["GET"],
        ),
        Route(
            "/dashboard/rules/{rule_id}",
            endpoint=make_html_handler(rule_detail_page),
            methods=["GET"],
        ),
        Route(
            "/dashboard/metrics",
            endpoint=make_html_handler(metrics_page),
            methods=["GET"],
        ),
        Route(
            "/dashboard/settings",
            endpoint=make_html_handler(settings_page),
            methods=["GET"],
        ),
        Route(
            "/dashboard/audit",
            endpoint=make_html_handler(audit_page),
            methods=["GET"],
        ),
    ]

    # Static files
    static_app = StaticFiles(directory=str(STATIC_DIR))

    routes = [
        Mount("/static", app=static_app),
        *json_routes,
        *html_routes,
    ]

    middleware = [
        Middleware(AdminAuthMiddleware),
    ]

    app = Starlette(
        routes=routes,
        middleware=middleware,
    )

    return app
