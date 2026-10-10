"""SQLAlchemy adapter for safe account directory queries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import func, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.account_directory_ports import (
    AccountDirectoryAuthorityUnavailable,
    AccountDirectoryItem,
    AccountDirectoryPage,
    AccountDirectoryQuery,
)
from .models import AccountRecord


class SqlAlchemyAccountDirectoryReader:
    """Read only allow-listed projections; credential columns never enter queries."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_accounts(self, query: AccountDirectoryQuery) -> AccountDirectoryPage:
        """Read a deterministic page and directory facts in one connection scope."""
        conditions = []
        if query.status is not None:
            conditions.append(AccountRecord.status == query.status)
        if query.search:
            escaped = (
                query.search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            conditions.append(AccountRecord.username.ilike(f"%{escaped}%", escape="\\"))
        try:
            async with self._engine.begin() as connection:
                matching_accounts = (
                    select(
                        AccountRecord.account_id,
                        AccountRecord.username,
                        AccountRecord.role_id,
                        AccountRecord.status,
                        AccountRecord.built_in,
                        AccountRecord.last_login_at,
                        AccountRecord.revision,
                    )
                    .where(*conditions)
                    .cte("matching_accounts")
                )
                page = (
                    select(matching_accounts)
                    .order_by(
                        matching_accounts.c.username,
                        matching_accounts.c.account_id,
                    )
                    .offset((query.page - 1) * query.page_size)
                    .limit(query.page_size)
                    .cte("account_page")
                )
                total = (
                    select(func.count().label("total"))
                    .select_from(matching_accounts)
                    .cte("account_total")
                )
                active_admins = (
                    select(func.count().label("active_admins"))
                    .select_from(AccountRecord)
                    .where(
                        AccountRecord.role_id == "admin",
                        AccountRecord.status == "active",
                    )
                    .cte("active_admin_count")
                )
                result = await connection.execute(
                    select(
                        total.c.total,
                        active_admins.c.active_admins,
                        page.c.account_id,
                        page.c.username,
                        page.c.role_id,
                        page.c.status,
                        page.c.built_in,
                        page.c.last_login_at,
                        page.c.revision,
                    ).select_from(
                        total.join(active_admins, true()).outerjoin(page, true())
                    ).order_by(page.c.username, page.c.account_id)
                )
                rows = result.mappings().all()
                total_count = int(rows[0]["total"])
                active_admin_count = int(rows[0]["active_admins"])
                items = tuple(
                    _directory_item(row, active_admin_count)
                    for row in rows
                    if row["account_id"] is not None
                )
        except SQLAlchemyError:
            raise AccountDirectoryAuthorityUnavailable(
                "account directory authority is unavailable"
            ) from None

        return AccountDirectoryPage(items, query.page, query.page_size, total_count)

    async def read_account(self, account_id: str) -> AccountDirectoryItem | None:
        """Read a single safe account projection and current last-admin fact."""
        try:
            async with self._engine.begin() as connection:
                active_admins = int(
                    await connection.scalar(
                        select(func.count())
                        .select_from(AccountRecord)
                        .where(
                            AccountRecord.role_id == "admin",
                            AccountRecord.status == "active",
                        )
                    )
                    or 0
                )
                result = await connection.execute(
                    select(
                        AccountRecord.account_id,
                        AccountRecord.username,
                        AccountRecord.role_id,
                        AccountRecord.status,
                        AccountRecord.built_in,
                        AccountRecord.last_login_at,
                        AccountRecord.revision,
                    ).where(AccountRecord.account_id == account_id)
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise AccountDirectoryAuthorityUnavailable(
                "account directory authority is unavailable"
            ) from None

        return _directory_item(row, active_admins) if row is not None else None


def _directory_item(
    row: Mapping[str, object], active_admins: int
) -> AccountDirectoryItem:
    is_active_admin = row["role_id"] == "admin" and row["status"] == "active"
    return AccountDirectoryItem(
        account_id=str(row["account_id"]),
        username=str(row["username"]),
        role_id=str(row["role_id"]),
        status=str(row["status"]),
        built_in=bool(row["built_in"]),
        last_login_at=(
            row["last_login_at"]
            if isinstance(row["last_login_at"], datetime)
            else None
        ),
        revision=int(row["revision"]),
        last_active_admin=is_active_admin and active_admins == 1,
    )
