# atlas-richie-tenant-adapter-asgi

ASGI 租户身份中间件，对位 Java `TenantIdentityFilter`。纯 scope/receive/send，
不依赖任何 Web 框架。只依赖 `tenant-core`（零第三方依赖）。

流程：解析（`TenantIdentityResolver`）→ 拒绝（带错误码）或绑定
（`TenantContext.bind`，请求结束自动恢复）→ 放行。

```python
from atlas_richie.tenant_core import TenantIdentityResolver
from atlas_richie.tenant_adapter_asgi import TenantASGIMiddleware

resolver = TenantIdentityResolver(provider, jwt_resolver=verify_jwt)
app = TenantASGIMiddleware(app, resolver)
```

非 HTTP scope（lifespan/websocket）直接透传。拒绝响应为
`{"error": code, "message": ...}`，状态码可配（默认 401）。
