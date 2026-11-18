# atlas-richie-tenant-core

多租户核心，零第三方依赖。对位 Java tenant-core 的可移植部分。

| 模块 | 内容 |
|---|---|
| `context` | `TenantContext` + contextvars holder（对位 ThreadLocal），`run_with_tenant` 嵌套安全、异常恢复；`propagate` 跨线程传播（对位 TenantTaskDecorator） |
| `model` | `TenantPrincipal` / `TenantInfo` / `TenantStatus` / `IsolationMode` |
| `identity` | 身份解析：assertion → JWT → unsigned header（注入式 callable，不依赖 JWT 库）；白名单/超管路径、状态校验、X-Tenant-Id 一致性 |
| `strategy` | `TenancyRouter`：按隔离模式算出 table_suffix / schema_name / data_source_key / 列过滤标志并校验 |
| `naming` | 标识符校验（防租户配置注入 SQL） |
| `provider` | `TenantInfoProvider` SPI + TTL/容量缓存 + NoOp |

**不移植**：MyBatis 拦截器（TenantLineInnerInterceptor 等）、JDBC 动态数据源、
Reactor 上下文、Spring 自动装配、Micrometer 指标。SQL 拦截由持久层适配器
消费 `TenancyRouting` 产物（后续项）。

## 用法

```python
from atlas_richie.tenant_core import (
    TenantContext, TenantPrincipal, TenantIdentityResolver, TenancyRouter,
)

# 请求入口解析并绑定
resolver = TenantIdentityResolver(provider, jwt_resolver=verify_jwt)
resolution = resolver.resolve(path, headers)
if resolution.denied:
    ...  # 由 Web 适配器拒绝
TenantContext.run_with_tenant(resolution.principal, handle_request)

# 业务内取租户
tenant_id = TenantContext.require_tenant_id()

# 隔离路由
routing = TenancyRouter().resolve(tenant_info)
```
