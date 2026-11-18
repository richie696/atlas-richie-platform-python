"""租户值对象（对位 Java tenant-common / tenant-core model）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class IsolationMode(StrEnum):
    COLUMN = "COLUMN"
    TABLE = "TABLE"
    SCHEMA = "SCHEMA"
    DATABASE = "DATABASE"
    HYBRID = "HYBRID"


class TenantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MIGRATING = "MIGRATING"
    PROVISIONING = "PROVISIONING"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class TenantPrincipal:
    """The tenant bound to the current execution context."""

    tenant_id: int
    tenant_name: str | None = None
    expired_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class TenantInfo:
    """Tenant configuration as resolved by a TenantInfoProvider."""

    tenant_id: int
    mode: IsolationMode = IsolationMode.COLUMN
    data_source_name: str | None = None
    canary_data_source_name: str | None = None
    schema_name: str | None = None
    table_suffix: str | None = None
    status: TenantStatus | None = None
    valid_until: datetime | None = None
    canary: bool = False


__all__ = ["IsolationMode", "TenantStatus", "TenantPrincipal", "TenantInfo"]