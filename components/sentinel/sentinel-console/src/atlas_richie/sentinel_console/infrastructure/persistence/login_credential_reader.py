"""SQLAlchemy adapter that returns minimal login credential facts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.login_ports import (
    LoginAuthorityUnavailable,
    LoginCredential,
)
from .models import AccountRecord


class SqlAlchemyLoginCredentialReader:
    """Read only the single account projection needed for password verification."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_login_credential(self, username_key: str) -> LoginCredential | None:
        """Resolve the canonical digest without accepting raw login identifiers."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(
                        AccountRecord.account_id,
                        AccountRecord.username,
                        AccountRecord.role_id,
                        AccountRecord.status,
                        AccountRecord.password_hash,
                    ).where(AccountRecord.username_key == username_key)
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise LoginAuthorityUnavailable(
                "login credential authority is unavailable"
            ) from None

        if row is None:
            return None
        return LoginCredential(
            account_id=str(row["account_id"]),
            username=str(row["username"]),
            role_id=str(row["role_id"]),
            status=str(row["status"]),
            password_hash=str(row["password_hash"]),
        )
