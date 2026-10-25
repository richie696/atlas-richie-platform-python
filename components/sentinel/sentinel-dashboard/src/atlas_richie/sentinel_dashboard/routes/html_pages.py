"""Atlas Richie Sentinel Dashboard v2 — HTML 页面 routes.

中文
----
HTML 页面 6 个 (用 Jinja2 模板):

- ``GET /`` — dashboard 总览 (engine state + in_flight + rules count + metrics 摘要)
- ``GET /rules`` — 规则列表
- ``GET /rules/{rule_id}`` — 规则详情
- ``GET /metrics`` — 实时 metrics (含 SSE 客户端 JS)
- ``GET /settings`` — dashboard 配置 (host / port / allow_admin / admin_token 状态)
- ``GET /audit`` — 审计日志 (最近 100 条, cap 1000)

设计原则:
- 模板里 ``request.state.dashboard`` 访问共享状态 (跟 JSON API 一致)
- 所有 admin 操作通过 fetch() 调 JSON API, 不走 form (CSRF 风险)
- 实时 metrics 通过 EventSource (``/sse/metrics``) 客户端订阅
- 不**重**复业务逻辑, HTML 渲染只调 JSON API 同样的 source

English
--------
6 HTML pages (Jinja2 templates). Admin actions via fetch() to JSON
API; live metrics via EventSource.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.templating import Jinja2Templates

from ..state import DashboardState


async def dashboard_page(
    request: Request, *, state: DashboardState, templates: Jinja2Templates
) -> Any:
    """GET / — dashboard 总览."""
    snaps = state.metric_registry.iter_snapshots()
    total_admitted = sum(s.admitted for s in snaps)
    total_blocked = sum(s.blocked for s in snaps)
    total_failed = sum(s.failed for s in snaps)
    rules_count = len(state.rule_repository.current_index)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "engine_state": state.engine.state.value,
            "in_flight": state.engine.in_flight,
            "last_error": str(state.engine.last_error) if state.engine.last_error else None,
            "rules_count": rules_count,
            "total_admitted": total_admitted,
            "total_blocked": total_blocked,
            "total_failed": total_failed,
            "host": state.host,
            "port": state.port,
        },
    )


async def rules_page(
    request: Request, *, state: DashboardState, templates: Jinja2Templates
) -> Any:
    """GET /rules — 规则列表."""
    rules = state.rule_repository.current_index.snapshot_rules()
    rule_list = sorted(rules.keys())
    return templates.TemplateResponse(
        request,
        "rules.html",
        {
            "rule_list": rule_list,
            "rules_count": len(rule_list),
        },
    )


async def rule_detail_page(
    request: Request, *, state: DashboardState, templates: Jinja2Templates
) -> Any:
    """GET /rules/{rule_id} — 规则详情."""
    rid = request.path_params["rule_id"]
    rules = state.rule_repository.current_index.snapshot_rules()
    if rid not in rules:
        return templates.TemplateResponse(
            request,
            "rule_detail.html",
            {
                "rule_id": rid,
                "rule": None,
                "error": f"rule {rid!r} not found",
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "rule_detail.html",
        {
            "rule_id": rid,
            "rule": rules[rid],
            "error": None,
        },
    )


async def metrics_page(
    request: Request, *, state: DashboardState, templates: Jinja2Templates
) -> Any:
    """GET /metrics — 实时 metrics (含 SSE 客户端 JS)."""
    return templates.TemplateResponse(
        request,
        "metrics.html",
        {},
    )


async def settings_page(
    request: Request, *, state: DashboardState, templates: Jinja2Templates
) -> Any:
    """GET /settings — dashboard 配置 (admin_token 状态不外泄)."""
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "host": state.host,
            "port": state.port,
            "allow_admin": state.allow_admin,
            "admin_token_set": bool(state.admin_token),
            "audit_log_size": len(state.audit_log),
        },
    )


async def audit_page(
    request: Request, *, state: DashboardState, templates: Jinja2Templates
) -> Any:
    """GET /audit — 审计日志 (最近 100 条, 倒序)."""
    recent = list(reversed(state.audit_log[-100:]))
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "entries": recent,
            "total": len(state.audit_log),
        },
    )
