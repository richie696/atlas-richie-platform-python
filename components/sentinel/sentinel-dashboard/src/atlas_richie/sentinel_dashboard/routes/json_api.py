"""Atlas Richie Sentinel Dashboard v2 — JSON API routes (backward compat).

中文
----
保留 6 个原 JSON API (per-process admin API), 不破坏 1.0 兼容性:

- ``GET /health`` — 进程健康 + engine state + in_flight
- ``GET /metrics`` — MetricRegistry snapshots
- ``GET /rules`` — 当前生效规则
- ``GET /rules/{rule_id}`` — 单个 rule
- ``GET /state`` — engine state + in_flight + last_error + rules_count
- ``POST /admin/rules/reload`` — 触发 RuleSource reload
- ``POST /admin/breaker/{rule_id}/reset`` — DegradeSlot.force_reset

admin 端点受 ``AdminAuthMiddleware`` 保护, 缺失/错 token 返回 403.

English
--------
Preserves 6 original JSON API endpoints (per-process admin API) for
backward compatibility. Admin endpoints protected by ``AdminAuthMiddleware``.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..state import DashboardState


# ---------------------------------------------------------------------------
# Auth Middleware (ASGI, 兼容 streaming)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _AuditEntry:
    """Audit log entry (M5.1 历史设计, v2 保留)."""

    at_ns: int
    op: str  # "admin" / "denied"
    actor: str
    detail: str


class AdminAuthMiddleware:
    """admin 鉴权 + audit log 中间件 (纯 ASGI, 兼容 streaming).

    中文
    ----
    - 路径以 ``/admin/`` 开头才需要鉴权
    - ``Authorization: Bearer <admin_token>`` 匹配 → 放行 + audit
    - 缺失/错 token → 403 + audit
    - ``allow_admin=False`` → 一律 403 + audit
    - 不走 admin 路径直接 pass-through, **不**破坏 streaming 响应
      (跟 BaseHTTPMiddleware 不同, 后者会 read-all-body)

    State 从 ``scope["app"].state.dashboard`` 拿 (由 build_app 注入).

    English
    --------
    Pure ASGI middleware (not BaseHTTPMiddleware) for streaming
    compatibility. State read from ``scope["app"].state.dashboard``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/admin/"):
            # Non-admin path: pass through
            await self.app(scope, receive, send)
            return
        # Admin path: check auth (从 scope.headers 直接拿, 不构造 Request)
        auth_header = b""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_header = value
                break
        auth = auth_header.decode("latin-1") if auth_header else ""
        # state 从 scope["app"].state.dashboard 拿
        # 注意: scope["app"] 是 Application 引用, .state 是 State 实例
        app = scope.get("app")
        if app is None:
            await self.app(scope, receive, send)
            return
        state: DashboardState = app.state.dashboard
        ok, reason = self._check_admin(state, auth)
        if not ok:
            self._audit(state, "denied", self._get_client(scope), f"{scope.get('method', '?')} {path}")
            response = JSONResponse(
                {"error": reason}, status_code=403
            )
            await response(scope, receive, send)
            return
        # Auth OK: pass through + audit after
        # 简化: 总是审计 (无论 2xx / 4xx / 5xx), 不捕获 status
        # (streaming 响应无法拦截 http.response.start)
        await self.app(scope, receive, send)
        # audit 每次 admin 调用都记录 (成功 + 业务错), 跟 denied 区分
        # denied 是 auth 失败, admin 是过了 auth 但 handler 任意状态
        self._audit(state, "admin", self._get_client(scope), f"{scope.get('method', '?')} {path}")

    @staticmethod
    def _get_client(scope: Scope) -> str:
        client = scope.get("client")
        if client is None:
            return "?"
        if isinstance(client, tuple) and len(client) >= 1:
            return str(client[0])
        return str(client)

    @staticmethod
    def _check_admin(state: DashboardState, auth_header: str) -> tuple[bool, str]:
        if not state.allow_admin:
            return False, "admin disabled"
        if not state.admin_token:
            return False, "admin not configured"
        if not auth_header.startswith("Bearer "):
            return False, "missing bearer"
        if auth_header[len("Bearer "):] != state.admin_token:
            return False, "invalid token"
        return True, "ok"

    @staticmethod
    def _audit(state: DashboardState, op: str, actor: str, detail: str) -> None:
        state.audit_log.append(
            _AuditEntry(
                at_ns=time.time_ns(),
                op=op,
                actor=actor,
                detail=detail,
            )
        )
        if len(state.audit_log) > 1000:
            del state.audit_log[: len(state.audit_log) - 1000]


def _state(request: Request) -> DashboardState:
    """从 request 拿 DashboardState (由 build_app 注入)."""
    return request.app.state.dashboard


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


async def health_json(request: Request) -> JSONResponse:
    """GET /health — 进程健康 + engine state + in_flight."""
    s = _state(request)
    return JSONResponse(
        {
            "status": "ok",
            "engine_state": s.engine.state.value,
            "in_flight": s.engine.in_flight,
        }
    )


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------


async def metrics_json(request: Request) -> JSONResponse:
    """GET /metrics — MetricRegistry 全部 snapshot."""
    s = _state(request)
    snaps = s.metric_registry.iter_snapshots()
    return JSONResponse(
        [
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
        ]
    )


# ---------------------------------------------------------------------------
# GET /rules
# ---------------------------------------------------------------------------


async def rules_json(request: Request) -> JSONResponse:
    """GET /rules — 当前生效规则."""
    s = _state(request)
    rules = s.rule_repository.current_index.snapshot_rules()
    # default=str 用于序列化 dataclass / 非 JSON-native 对象
    return JSONResponse(json.loads(json.dumps(dict(rules), default=str)))


# ---------------------------------------------------------------------------
# GET /rules/{rule_id}
# ---------------------------------------------------------------------------


async def rule_json(request: Request) -> JSONResponse:
    """GET /rules/{rule_id} — 单个 rule 详情."""
    s = _state(request)
    rid = request.path_params["rule_id"]
    rules = s.rule_repository.current_index.snapshot_rules()
    if rid in rules:
        return JSONResponse(json.loads(json.dumps({rid: rules[rid]}, default=str)))
    return JSONResponse({"error": "rule not found"}, status_code=404)


# ---------------------------------------------------------------------------
# GET /state
# ---------------------------------------------------------------------------


async def state_json(request: Request) -> JSONResponse:
    """GET /state — engine state + in_flight + last_error + rules_count."""
    s = _state(request)
    return JSONResponse(
        {
            "engine_state": s.engine.state.value,
            "in_flight": s.engine.in_flight,
            "last_error": (
                str(s.engine.last_error)
                if s.engine.last_error
                else None
            ),
            "rules_count": len(s.rule_repository.current_index),
        }
    )


# ---------------------------------------------------------------------------
# POST /admin/rules/reload
# ---------------------------------------------------------------------------


async def admin_reload_rules(request: Request) -> JSONResponse:
    """POST /admin/rules/reload — 触发 RuleSource 重新拉."""
    s = _state(request)
    if s.rule_source is None:
        return JSONResponse(
            {"error": "no rule_source configured"}, status_code=400
        )
    snap = s.rule_source.latest()
    if snap is None:
        return JSONResponse({"error": "no snapshot"}, status_code=500)
    applied = s.rule_repository.apply_snapshot(snap)
    return JSONResponse({"applied": applied}, status_code=200 if applied else 500)


# ---------------------------------------------------------------------------
# POST /admin/breaker/{rule_id}/reset
# ---------------------------------------------------------------------------


async def admin_reset_breaker(request: Request) -> JSONResponse:
    """POST /admin/breaker/{rule_id}/reset — DegradeSlot.force_reset."""
    s = _state(request)
    if s.degrade_slot is None:
        return JSONResponse(
            {"error": "no degrade_slot"}, status_code=400
        )
    rid = request.path_params["rule_id"]
    s.degrade_slot.force_reset(rid)
    return JSONResponse({"reset": rid})
