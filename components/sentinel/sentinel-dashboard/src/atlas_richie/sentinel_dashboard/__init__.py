"""Sentinel Dashboard (M5.1) — per-process embedded 管理 API。

中文
----
``SentinelDashboard`` 是 per-process 控制面,提供 REST 端点:

- ``GET /health`` — 进程健康
- ``GET /metrics`` — MetricRegistry 全部 snapshot
- ``GET /rules`` — RuleRepository 当前生效规则
- ``GET /rules/<rule_id>`` — 单个 rule 详情
- ``GET /state`` — Engine 状态 / in-flight / last_error
- ``POST /admin/rules/reload`` — 触发 RuleSource 重新拉(只读默认
  禁用,需配 ``allow_admin=True``)
- ``POST /admin/breaker/<rule_id>/reset`` — DegradeSlot.force_reset

设计要点(PLANNING §M5.1 / §M5.2):

- **默认 loopback + read-only**:bind ``127.0.0.1``,admin 端点返回 403
  除非 ``allow_admin=True``(避免误用把生产服务暴露)
- **写操作认证授权审计**:admin 操作要求 ``auth_token`` 匹配
  ``admin_token``;记录审计日志到 ``self._audit_log``
- **零 3rd-party**:std http.server(用 ``socketserver`` + ``ThreadingMixIn``,
  简单同步;生产建议换 ``uvicorn`` / ``starlette``,M5.4 加迁移)
- **per-process**:每个 SentinelEngine 1 个 Dashboard;不跨进程

English
--------
Sentinel Dashboard (M5.1) — per-process embedded admin API.

``SentinelDashboard`` is the per-process control plane, exposes REST
endpoints:

- ``GET /health`` — process health.
- ``GET /metrics`` — all MetricRegistry snapshots.
- ``GET /rules`` — current active rules from RuleRepository.
- ``GET /rules/<rule_id>`` — single rule details.
- ``GET /state`` — Engine state / in-flight / last_error.
- ``POST /admin/rules/reload`` — trigger RuleSource re-pull
  (read-only by default; needs ``allow_admin=True``).
- ``POST /admin/breaker/<rule_id>/reset`` — DegradeSlot.force_reset.

Design points (PLANNING §M5.1 / §M5.2):

- **Default loopback + read-only**: bind ``127.0.0.1``; admin
  endpoints return 403 unless ``allow_admin=True``.
- **Write auth + audit**: admin ops require ``auth_token`` matches
  ``admin_token``; logged to ``self._audit_log``.
- **Zero 3rd-party**: stdlib http.server (socketserver +
  ThreadingMixIn); production should swap to uvicorn / starlette
  (M5.4 migration).
- **per-process**: 1 Dashboard per SentinelEngine; not cross-process.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.model import EngineState
from atlas_richie.sentinel.metrics import MetricRegistry
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.source.rule_source import RuleSource
from atlas_richie.sentinel.slots.degrade import DegradeSlot


@dataclass(slots=True)
class _AuditEntry:
    """中文
    ----
    审计日志条目。

    English
    --------
    Audit log entry.
    """

    at_ns: int
    op: str
    actor: str
    detail: str


@dataclass(slots=True)
class SentinelDashboard:
    """中文
    ----
    per-process 管理 API。

    English
    --------
    Per-process admin API.
    """

    engine: SentinelEngine
    metric_registry: MetricRegistry
    rule_repository: RuleRepository
    rule_source: Optional[RuleSource] = None
    degrade_slot: Optional[DegradeSlot] = None
    host: str = "127.0.0.1"
    port: int = 8719
    allow_admin: bool = False
    admin_token: str = ""
    audit_log: list = field(default_factory=list)
    _server: Any = field(default=None, init=False, repr=False)
    _thread: Any = field(default=None, init=False, repr=False)

    def _audit(self, op: str, actor: str, detail: str) -> None:
        import time
        self.audit_log.append(
            _AuditEntry(at_ns=time.time_ns(), op=op, actor=actor, detail=detail)
        )
        # Cap audit log to last 1000 entries
        if len(self.audit_log) > 1000:
            self.audit_log = self.audit_log[-1000:]

    def _check_admin(self, auth_header: str) -> tuple[bool, str]:
        """中文
        ----
        检查 admin token;失败返 (False, "Forbidden")。

        English
        --------
        Check admin token; fail returns (False, "Forbidden").
        """
        if not self.allow_admin:
            return False, "admin disabled"
        if not self.admin_token:
            return False, "admin not configured"
        # Expect "Authorization: Bearer <token>"
        if not auth_header.startswith("Bearer "):
            return False, "missing bearer"
        if auth_header[len("Bearer "):] != self.admin_token:
            return False, "invalid token"
        return True, "ok"

    def start(self) -> None:
        """中文
        ----
        启动 HTTP server(后台线程);绑 ``127.0.0.1`` 默认。

        English
        --------
        Start HTTP server (background thread); bind ``127.0.0.1`` by
        default.
        """
        if self._server is not None:
            return
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return  # suppress default logging

            def do_GET(self):  # noqa: N802
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

            def _handle(self, method: str) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                if method == "GET":
                    body, status = self._dispatch_get(path)
                else:
                    auth = self.headers.get("Authorization", "")
                    ok, reason = outer._check_admin(auth)
                    if not ok:
                        body = json.dumps({"error": reason}).encode()
                        self._send(status=403, body=body)
                        outer._audit("denied", self.client_address[0], f"{method} {path}")
                        return
                    body, status = self._dispatch_post(path)
                    outer._audit(
                        "admin",
                        self.client_address[0],
                        f"{method} {path}",
                    )
                self._send(status=status, body=body)

            def _send(self, *, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _dispatch_get(self, path: str) -> tuple[bytes, int]:
                if path == "/health":
                    return (
                        json.dumps(
                            {
                                "status": "ok",
                                "engine_state": outer.engine.state.value,
                                "in_flight": outer.engine.in_flight,
                            }
                        ).encode(),
                        200,
                    )
                if path == "/metrics":
                    snaps = outer.metric_registry.iter_snapshots()
                    return (
                        json.dumps(
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
                        ).encode(),
                        200,
                    )
                if path == "/rules":
                    return (
                        json.dumps(
                            dict(
                                outer.rule_repository.current_index.snapshot_rules()
                            ),
                            default=str,
                        ).encode(),
                        200,
                    )
                if path.startswith("/rules/"):
                    rid = path[len("/rules/"):]
                    rules = outer.rule_repository.current_index.snapshot_rules()
                    if rid in rules:
                        return (
                            json.dumps({rid: rules[rid]}, default=str).encode(),
                            200,
                        )
                    return (
                        json.dumps({"error": "rule not found"}).encode(),
                        404,
                    )
                if path == "/state":
                    return (
                        json.dumps(
                            {
                                "engine_state": outer.engine.state.value,
                                "in_flight": outer.engine.in_flight,
                                "last_error": (
                                    str(outer.engine.last_error)
                                    if outer.engine.last_error
                                    else None
                                ),
                                "rules_count": len(
                                    outer.rule_repository.current_index
                                ),
                            }
                        ).encode(),
                        200,
                    )
                return (
                    json.dumps({"error": "not found", "path": path}).encode(),
                    404,
                )

            def _dispatch_post(self, path: str) -> tuple[bytes, int]:
                if path == "/admin/rules/reload":
                    if outer.rule_source is None:
                        return (
                            json.dumps({"error": "no rule_source configured"}).encode(),
                            400,
                        )
                    snap = outer.rule_source.latest()
                    if snap is None:
                        return (
                            json.dumps({"error": "no snapshot"}).encode(),
                            500,
                        )
                    applied = outer.rule_repository.apply_snapshot(snap)
                    return (
                        json.dumps({"applied": applied}).encode(),
                        200 if applied else 500,
                    )
                if path.startswith("/admin/breaker/") and path.endswith("/reset"):
                    rid = path[len("/admin/breaker/"):-len("/reset")]
                    if outer.degrade_slot is None:
                        return (
                            json.dumps({"error": "no degrade_slot"}).encode(),
                            400,
                        )
                    outer.degrade_slot.force_reset(rid)
                    return (
                        json.dumps({"reset": rid}).encode(),
                        200,
                    )
                return (
                    json.dumps({"error": "not found", "path": path}).encode(),
                    404,
                )

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="sentinel-dashboard"
        )
        self._thread.start()

    def stop(self) -> None:
        """中文
        ----
        停止 HTTP server(幂等)。

        English
        --------
        Stop HTTP server (idempotent).
        """
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None


__all__ = ["SentinelDashboard", "_AuditEntry"]
