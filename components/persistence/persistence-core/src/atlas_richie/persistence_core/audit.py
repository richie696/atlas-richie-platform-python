"""审计与软删字段的默认填充策略（零第三方依赖）。

对位 Java `cn.richie696.component.dao.handler.DefaultFieldHandler` 与
`DaoProperties.enableDefaultFieldHandler`。

Java 用 MyBatis-Plus 的 `MetaObjectHandler` 在**实体**上填五个字段：
`createId` / `updateId` / `createTime` / `updateTime` / `deleted`——
insert 填五个，update 只填 `updateId` / `updateTime`，且都是
"字段存在且当前值为 null 才填"（strict 语义）。

Python 侧目前没有 ORM 模型（`persistence-sqlalchemy` 是 Core 风格），
所以这里交付的是**策略**而不是拦截器：字段名、启用开关、以及"该字段该填什么"
的唯一判定入口（`AuditFieldPolicy.insert_value` / `update_value`）。
驱动相关的挂载方式由适配器包给出（默认实现是 SQLAlchemy 列默认值），
其它适配器复用同一份策略，不会出现两套判定。

与 Java 的两处差异（已核对 Java 源码）：
1. **update 路径刷新而非仅补空**。Java 的 `strictUpdateFill` 只在字段为 null
   时写入，因此实体若带着 insert 时的 `updateTime`，更新后仍是旧值。
   这里按"审计字段应反映最近一次变更"的语义，update 一律刷新
   `updateId` / `updateTime`。
2. **当前用户由调用方注入**。Java 从 `LoginUserContextHolder` 取用户名；
   本仓没有等价的登录态上下文（`tenant_core` 只承载租户身份），因此用户名
   由适配器包的 provider 提供，取不到时按 Java 语义记空串。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class AuditField(StrEnum):
    """审计与软删的五个语义字段。"""

    CREATE_ID = "CREATE_ID"
    UPDATE_ID = "UPDATE_ID"
    CREATE_TIME = "CREATE_TIME"
    UPDATE_TIME = "UPDATE_TIME"
    DELETED = "DELETED"


_FIELD_ATTRIBUTES: Mapping[AuditField, str] = MappingProxyType(
    {
        AuditField.CREATE_ID: "create_id",
        AuditField.UPDATE_ID: "update_id",
        AuditField.CREATE_TIME: "create_time",
        AuditField.UPDATE_TIME: "update_time",
        AuditField.DELETED: "deleted",
    }
)

INSERT_FIELDS: tuple[AuditField, ...] = tuple(AuditField)
"""insert 路径涉及的字段集合。"""

UPDATE_FIELDS: tuple[AuditField, ...] = (
    AuditField.UPDATE_ID,
    AuditField.UPDATE_TIME,
)
"""update 路径涉及的字段集合。"""


@dataclass(frozen=True, slots=True)
class AuditFieldPolicy:
    """审计字段策略：列名映射 + 启用开关 + 软删默认值。"""

    enabled: bool = True
    create_id: str = "createId"
    update_id: str = "updateId"
    create_time: str = "createTime"
    update_time: str = "updateTime"
    deleted: str = "deleted"
    deleted_default: bool = False

    def column_name(self, field: AuditField) -> str:
        """语义字段对应的列名。"""
        return getattr(self, _FIELD_ATTRIBUTES[field])

    def insert_value(
        self, field: AuditField, current: Any, *, username: str, now: datetime
    ) -> Any:
        """insert 路径该字段应写入的值。

        `current` 非 None 时原样保留（对位 Java 的 strict 语义）；禁用策略
        时不做任何填充。
        """
        if not self.enabled or current is not None:
            return current
        if field in (AuditField.CREATE_ID, AuditField.UPDATE_ID):
            return username or ""
        if field in (AuditField.CREATE_TIME, AuditField.UPDATE_TIME):
            return now
        return self.deleted_default

    def update_value(
        self, field: AuditField, current: Any, *, username: str, now: datetime
    ) -> Any:
        """update 路径该字段应写入的值：只动 `updateId` / `updateTime`。"""
        if not self.enabled:
            return current
        if field is AuditField.UPDATE_ID:
            return username or ""
        if field is AuditField.UPDATE_TIME:
            return now
        return current


@dataclass(frozen=True, slots=True)
class AuditFieldValues:
    """一行记录的审计字段取值。"""

    create_id: str | None = None
    update_id: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    deleted: bool | None = None

    def get(self, field: AuditField) -> Any:
        """按语义字段取值。"""
        return getattr(self, _FIELD_ATTRIBUTES[field])

    def with_field(self, field: AuditField, value: Any) -> AuditFieldValues:
        """返回替换了单个字段的新快照。"""
        return replace(self, **{_FIELD_ATTRIBUTES[field]: value})


def resolve_insert_values(
    policy: AuditFieldPolicy,
    current: AuditFieldValues,
    *,
    username: str,
    now: datetime,
) -> AuditFieldValues:
    """按 insert 路径补齐审计字段。"""
    values = current
    for field in INSERT_FIELDS:
        values = values.with_field(
            field,
            policy.insert_value(
                field, values.get(field), username=username, now=now
            ),
        )
    return values


def resolve_update_values(
    policy: AuditFieldPolicy,
    current: AuditFieldValues,
    *,
    username: str,
    now: datetime,
) -> AuditFieldValues:
    """按 update 路径刷新审计字段。"""
    values = current
    for field in UPDATE_FIELDS:
        values = values.with_field(
            field,
            policy.update_value(
                field, values.get(field), username=username, now=now
            ),
        )
    return values


def audit_column_values(
    policy: AuditFieldPolicy, values: AuditFieldValues
) -> dict[str, Any]:
    """把语义取值映射成"列名 → 值"；None 的语义值不出现。"""
    mapping: dict[str, Any] = {}
    for field in INSERT_FIELDS:
        value = values.get(field)
        if value is None:
            continue
        mapping[policy.column_name(field)] = value
    return mapping


__all__ = [
    "AuditField",
    "AuditFieldPolicy",
    "AuditFieldValues",
    "INSERT_FIELDS",
    "UPDATE_FIELDS",
    "resolve_insert_values",
    "resolve_update_values",
    "audit_column_values",
]
