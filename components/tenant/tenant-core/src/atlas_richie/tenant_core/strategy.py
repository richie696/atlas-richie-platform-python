"""隔离模式路由（对位 Java `TenancyStrategy` 族的纯算法部分）。

Java 的策略把路由产物写进 MyBatis `Invocation` / JDBC Connection；那层是
框架绑定，不可移植。这里只交付**路由决策**：给定 TenantInfo 与租户 id，
校验并算出该租户应使用的 table_suffix / schema_name / data_source_key /
列过滤标志。实际的 SQL 拦截由持久层适配器消费这些产物（后续项）。

HYBRID 是路由器自身的分派模式，不能作为租户的具体 mode（对位 Java
`HybridStrategy.resolveDelegate` 对 HYBRID 抛错）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import TenantError, TenantErrorCode
from .model import IsolationMode, TenantInfo
from .naming import validate


@dataclass(frozen=True, slots=True)
class TenancyRouting:
    mode: IsolationMode
    column_filter: bool = False
    table_suffix: str | None = None
    schema_name: str | None = None
    data_source_key: str | None = None


def validate_tenant_id(tenant_id: int | None) -> int:
    if tenant_id is None or tenant_id <= 0:
        raise TenantError(TenantErrorCode.INVALID_TENANT_ID, f"Invalid tenant ID: {tenant_id}")
    return tenant_id


class TenancyRouter:
    """Computes isolation routing artifacts for a tenant."""

    def resolve(self, tenant_info: TenantInfo, tenant_id: int | None = None) -> TenancyRouting:
        if tenant_info is None:
            raise TenantError(TenantErrorCode.TENANT_NOT_FOUND, "tenant info must not be None")
        effective_id = validate_tenant_id(
            tenant_id if tenant_id is not None else tenant_info.tenant_id
        )
        mode = tenant_info.mode
        if mode is IsolationMode.COLUMN:
            return TenancyRouting(mode=mode, column_filter=True)
        if mode is IsolationMode.TABLE:
            suffix = validate(tenant_info.table_suffix, "tableSuffix")
            return TenancyRouting(mode=mode, table_suffix=suffix)
        if mode is IsolationMode.SCHEMA:
            schema = validate(tenant_info.schema_name, "schemaName")
            return TenancyRouting(mode=mode, schema_name=schema)
        if mode is IsolationMode.DATABASE:
            if tenant_info.data_source_name is None:
                raise TenantError(
                    TenantErrorCode.TENANT_INVALID_NAMING,
                    f"No datasource configured for tenant {effective_id}",
                )
            key = validate(tenant_info.data_source_name, "dataSourceKey")
            return TenancyRouting(mode=mode, data_source_key=key)
        raise TenantError(
            "TENANT_HYBRID_DELEGATE_INVALID",
            f"Hybrid strategy cannot delegate to itself for tenant: {effective_id}",
        )


__all__ = ["TenancyRouting", "TenancyRouter", "validate_tenant_id"]