"""持久层租户拦截：消费 `TenancyRouting` 的三种隔离模式。

对位 Java `TenantLineInnerInterceptor` / `DynamicTableNameInnerInterceptor`
的可移植部分。Java 在 MyBatis 拦截器里改写 SQL；这里交付 SQLAlchemy 的
等价机制：

- **COLUMN**：给 Select 注入 `tenant_id = :tid` 谓词（行级隔离）。
- **SCHEMA**：`schema_translate_map` execution option——SQLAlchemy 原生
  支持把默认 schema 映射到租户 schema，无需改写语句。
- **TABLE**：表名加租户后缀。

自动 ORM 拦截（do_orm_execute）需要平台定义 ORM 模型，目前未定义，故交付
显式可组合的助手 + 真实 PostgreSQL 跨租户隔离测试；自动拦截留待有模型时。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, Table
from sqlalchemy.engine import Connection

from atlas_richie.tenant_core import (
    IsolationMode,
    TenancyRouter,
    TenancyRouting,
    TenantContext,
    TenantInfo,
)


class TenantInterceptor:
    def __init__(
        self,
        *,
        tenant_column: str = "tenant_id",
        router: TenancyRouter | None = None,
    ) -> None:
        self._tenant_column = tenant_column
        self._router = router or TenancyRouter()

    @property
    def tenant_column(self) -> str:
        return self._tenant_column

    def routing_for(self, tenant_info: TenantInfo) -> TenancyRouting:
        return self._router.resolve(tenant_info)

    # ── COLUMN ──────────────────────────────────────────────────────

    def filter_select(
        self, stmt: Select, table: Table, tenant_id: int | None = None
    ) -> Select:
        """Inject the tenant predicate into a Core Select (行级隔离)."""
        effective = tenant_id if tenant_id is not None else TenantContext.require_tenant_id()
        if self._tenant_column not in table.c:
            raise ValueError(
                f"table {table.name!r} has no tenant column {self._tenant_column!r}"
            )
        return stmt.where(table.c[self._tenant_column] == effective)

    def select(self, table: Table, tenant_id: int | None = None) -> Select:
        from sqlalchemy import select

        return self.filter_select(select(table), table, tenant_id)

    # ── SCHEMA ──────────────────────────────────────────────────────

    def schema_translate_map(self, tenant_info: TenantInfo) -> dict[Any, str] | None:
        """Map the default schema to the tenant schema (SCHEMA mode)."""
        routing = self.routing_for(tenant_info)
        if routing.mode is not IsolationMode.SCHEMA:
            return None
        return {None: routing.schema_name}

    def execution_options(self, tenant_info: TenantInfo) -> dict[str, Any]:
        translate = self.schema_translate_map(tenant_info)
        return {"schema_translate_map": translate} if translate else {}

    def schema_connection(self, connection: Connection, tenant_info: TenantInfo) -> Connection:
        """A connection execution-scoped to the tenant schema."""
        options = self.execution_options(tenant_info)
        return connection.execution_options(**options) if options else connection

    # ── TABLE ───────────────────────────────────────────────────────

    def resolve_table_name(self, base_name: str, tenant_info: TenantInfo) -> str:
        routing = self.routing_for(tenant_info)
        if routing.mode is not IsolationMode.TABLE:
            return base_name
        return f"{base_name}_{routing.table_suffix}"


__all__ = ["TenantInterceptor"]