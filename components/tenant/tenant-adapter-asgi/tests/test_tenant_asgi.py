"""ASGI 租户中间件：绑定/拒绝/清理/并发隔离。"""

from __future__ import annotations

import asyncio
import json

import pytest

from atlas_richie.tenant_core import (
    TenantContext,
    TenantIdentityResolver,
    TenantInfo,
    TenantPrincipal,
    TenantStatus,
)
from atlas_richie.tenant_adapter_asgi import TenantASGIMiddleware

pytestmark = pytest.mark.unit


class _App:
    def __init__(self, status=200, fail=False) -> None:
        self.status = status
        self.fail = fail
        self.calls = 0
        self.seen_tenants: list[int | None] = []

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        self.seen_tenants.append(TenantContext.get_tenant_id())
        if self.fail:
            raise RuntimeError("app down")
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _scope(path="/api", headers=None, type_="http"):
    return {
        "type": type_,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }


async def _run(middleware, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _call(middleware, scope):
    return asyncio.run(_run(middleware, scope))


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def _body(sent):
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


class _Provider:
    def __init__(self, status=TenantStatus.ACTIVE) -> None:
        self._status = status

    def get_tenant_info(self, tenant_id):
        return TenantInfo(tenant_id=tenant_id, status=self._status)

    def exists(self, tenant_id):
        return True


def _resolver(**kwargs):
    return TenantIdentityResolver(
        _Provider(), jwt_resolver=lambda h: TenantPrincipal(tenant_id=7), **kwargs
    )


class TestBinding:
    def test_bound_request_sees_tenant(self) -> None:
        app = _App()
        middleware = TenantASGIMiddleware(app, _resolver())
        _call(middleware, _scope())
        assert app.calls == 1
        assert app.seen_tenants == [7]

    def test_context_cleared_after_request(self) -> None:
        app = _App()
        middleware = TenantASGIMiddleware(app, _resolver())
        _call(middleware, _scope())
        assert TenantContext.get() is None

    def test_context_cleared_even_when_app_raises(self) -> None:
        app = _App(fail=True)
        middleware = TenantASGIMiddleware(app, _resolver())
        with pytest.raises(RuntimeError):
            _call(middleware, _scope())
        assert TenantContext.get() is None, "应用异常不得泄漏租户上下文"

    def test_unbound_request_passes_without_tenant(self) -> None:
        app = _App()
        resolver = TenantIdentityResolver(_Provider())  # 无解析器、不强制
        middleware = TenantASGIMiddleware(app, resolver)
        _call(middleware, _scope())
        assert app.calls == 1
        assert app.seen_tenants == [None]

    def test_whitelisted_path_passes(self) -> None:
        app = _App()
        resolver = TenantIdentityResolver(_Provider(), enforce_auth_tenant=True, whitelist=["/health"])
        middleware = TenantASGIMiddleware(app, resolver)
        _call(middleware, _scope("/health"))
        assert app.calls == 1


class TestDenial:
    def test_missing_token_denied_401(self) -> None:
        app = _App()
        resolver = TenantIdentityResolver(_Provider(), enforce_auth_tenant=True)
        middleware = TenantASGIMiddleware(app, resolver)
        sent = _call(middleware, _scope())
        assert _status(sent) == 401
        assert app.calls == 0
        assert json.loads(_body(sent))["error"] == "TENANT_AUTH_MISSING_TOKEN"

    def test_inactive_tenant_denied(self) -> None:
        app = _App()
        resolver = TenantIdentityResolver(
            _Provider(status=TenantStatus.INACTIVE),
            jwt_resolver=lambda h: TenantPrincipal(tenant_id=7),
        )
        middleware = TenantASGIMiddleware(app, resolver)
        sent = _call(middleware, _scope())
        assert json.loads(_body(sent))["error"] == "TENANT_AUTH_INACTIVE"
        assert app.calls == 0

    def test_custom_deny_status(self) -> None:
        app = _App()
        resolver = TenantIdentityResolver(_Provider(), enforce_auth_tenant=True)
        middleware = TenantASGIMiddleware(app, resolver, deny_status=403)
        sent = _call(middleware, _scope())
        assert _status(sent) == 403

    def test_none_resolver_rejected(self) -> None:
        with pytest.raises(ValueError):
            TenantASGIMiddleware(_App(), None)


class TestScopeAndConcurrency:
    def test_non_http_scope_passthrough(self) -> None:
        app = _App()
        middleware = TenantASGIMiddleware(app, _resolver())
        _call(middleware, _scope(type_="lifespan"))
        assert app.calls == 1
        assert app.seen_tenants == [None]

    def test_concurrent_requests_do_not_leak_tenants(self) -> None:
        """两个不同租户的请求并发，各自看到自己的租户，互不串扰。"""
        seen: dict[str, int | None] = {}

        class _SlowApp:
            async def __call__(self, scope, receive, send):
                path = scope["path"]
                seen[path] = TenantContext.get_tenant_id()
                await asyncio.sleep(0.02)
                # 让出后再次确认上下文未被另一请求改写
                assert TenantContext.get_tenant_id() == seen[path]
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok", "more_body": False})

        def resolver_for(tenant_id):
            return TenantIdentityResolver(
                _Provider(), jwt_resolver=lambda h: TenantPrincipal(tenant_id=tenant_id)
            )

        async def scenario():
            first = TenantASGIMiddleware(_SlowApp(), resolver_for(1))
            second = TenantASGIMiddleware(_SlowApp(), resolver_for(2))
            await asyncio.gather(
                _run(first, _scope("/a")),
                _run(second, _scope("/b")),
            )

        asyncio.run(scenario())
        assert seen == {"/a": 1, "/b": 2}
        assert TenantContext.get() is None
