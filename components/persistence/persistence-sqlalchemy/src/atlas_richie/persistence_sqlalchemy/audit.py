"""审计与软删字段的 SQLAlchemy 落地（列默认值）。

对位 Java `DefaultFieldHandler` 的挂载方式：Java 用 MyBatis-Plus 的
`MetaObjectHandler` 在实体上填字段；这里用 SQLAlchemy 的列默认值
（`default=` / `onupdate=`）达成同一效果——调用方不提供该列时才填，
显式提供的值原样保留。

判定逻辑不在这里：`default` 回调一律委托给
`atlas_richie.persistence_core.AuditFieldPolicy`，因此 core 与适配器
只有一份"该填什么"的实现。

用法：

```python
from atlas_richie.persistence_sqlalchemy import audit_columns

policy = AuditFieldPolicy()
table = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    *audit_columns(policy, username_provider=current_username, clock=utc_now),
)
```
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import Boolean, Column, DateTime, String

from atlas_richie.persistence_core.audit import (
    AuditField,
    AuditFieldPolicy,
)


def utc_now() -> datetime:
    """当前 UTC 时间（tz-aware）。"""
    return datetime.now(timezone.utc)


def audit_columns(
    policy: AuditFieldPolicy,
    *,
    username_provider: Callable[[], str | None],
    clock: Callable[[], datetime] = utc_now,
) -> list[Column]:
    """构造带默认值的审计列。

    策略禁用时**仍然建列**（对位 Java：实体始终声明这五个字段，只是处理器
    不再自动填）——不建列会让历史表结构与新表结构分叉。
    """
    enabled = policy.enabled

    def _insert_default(field: AuditField):
        def _default():
            return policy.insert_value(
                field, None, username=username_provider() or "", now=clock()
            )

        return _default

    def _update_default(field: AuditField):
        def _default():
            return policy.update_value(
                field, None, username=username_provider() or "", now=clock()
            )

        return _default

    create_default = _insert_default(AuditField.CREATE_ID) if enabled else None
    update_default = _insert_default(AuditField.UPDATE_ID) if enabled else None
    update_refresh = _update_default(AuditField.UPDATE_ID) if enabled else None
    create_time_default = _insert_default(AuditField.CREATE_TIME) if enabled else None
    update_time_default = _insert_default(AuditField.UPDATE_TIME) if enabled else None
    update_time_refresh = _update_default(AuditField.UPDATE_TIME) if enabled else None
    deleted_default = _insert_default(AuditField.DELETED) if enabled else None

    return [
        Column(policy.create_id, String(64), nullable=True, default=create_default),
        Column(
            policy.update_id,
            String(64),
            nullable=True,
            default=update_default,
            onupdate=update_refresh,
        ),
        Column(
            policy.create_time,
            DateTime(timezone=True),
            nullable=True,
            default=create_time_default,
        ),
        Column(
            policy.update_time,
            DateTime(timezone=True),
            nullable=True,
            default=update_time_default,
            onupdate=update_time_refresh,
        ),
        Column(policy.deleted, Boolean, nullable=True, default=deleted_default),
    ]


__all__ = ["audit_columns", "utc_now"]
