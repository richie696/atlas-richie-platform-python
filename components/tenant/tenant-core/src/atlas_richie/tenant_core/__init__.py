"""多租户核心：上下文、身份解析、隔离路由、命名校验与信息缓存。零依赖。

对位 Java tenant-core 的可移植部分。MyBatis 拦截器 / JDBC 动态数据源 /
Reactor / Spring 自动装配不移植；SQL 拦截由持久层适配器消费路由产物。
"""

from __future__ import annotations

from .context import ContextVarHolder, TenantContext, TenantContextHolder, propagate
from .errors import TenantError, TenantErrorCode
from .identity import IdentityResolution, Resolver, TenantIdentityResolver
from .model import IsolationMode, TenantInfo, TenantPrincipal, TenantStatus
from .naming import MAX_LENGTH, MIN_LENGTH, validate
from .provider import CachingTenantInfoProvider, NoOpTenantInfoProvider, TenantInfoProvider
from .strategy import TenancyRouter, TenancyRouting, validate_tenant_id

__all__ = [
    "IsolationMode",
    "TenantStatus",
    "TenantPrincipal",
    "TenantInfo",
    "TenantError",
    "TenantErrorCode",
    "TenantContextHolder",
    "ContextVarHolder",
    "TenantContext",
    "propagate",
    "validate",
    "MIN_LENGTH",
    "MAX_LENGTH",
    "TenantInfoProvider",
    "NoOpTenantInfoProvider",
    "CachingTenantInfoProvider",
    "TenancyRouter",
    "TenancyRouting",
    "validate_tenant_id",
    "TenantIdentityResolver",
    "IdentityResolution",
    "Resolver",
]