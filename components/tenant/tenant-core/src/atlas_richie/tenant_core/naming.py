"""命名约定校验（对位 Java `NamingConventionValidator`）。

schema/tableSuffix/dataSourceKey 都会进入 SQL 标识符位置，必须是合法标识符
（字母/数字/下划线，字母或下划线开头，1–128 字符），否则拒绝——这是防止
租户配置注入 SQL 的第一道闸。
"""

from __future__ import annotations

import re

from .errors import TenantError, TenantErrorCode

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIN_LENGTH = 1
MAX_LENGTH = 128


def validate(name: str | None, label: str) -> str:
    if name is None:
        raise TenantError(TenantErrorCode.TENANT_INVALID_NAMING, f"{label} must not be null")
    if len(name) < MIN_LENGTH:
        raise TenantError(TenantErrorCode.TENANT_INVALID_NAMING, f"{label} must not be empty")
    if len(name) > MAX_LENGTH:
        raise TenantError(
            TenantErrorCode.TENANT_INVALID_NAMING,
            f"{label} exceeds max length {MAX_LENGTH}: actual={len(name)}",
        )
    if not IDENTIFIER_PATTERN.fullmatch(name):
        raise TenantError(
            TenantErrorCode.TENANT_INVALID_NAMING,
            f"{label} validation failed: '{name}'. Must match "
            "^[A-Za-z_][A-Za-z0-9_]*$ (letters/digits/underscore, "
            "must start with letter or underscore)",
        )
    return name


__all__ = ["validate", "IDENTIFIER_PATTERN", "MIN_LENGTH", "MAX_LENGTH"]