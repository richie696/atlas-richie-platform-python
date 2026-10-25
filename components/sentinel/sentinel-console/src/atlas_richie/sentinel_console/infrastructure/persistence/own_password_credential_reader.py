"""SQLAlchemy reader for the current account's one-way password hash."""

from __future__ import annotations

import hmac
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.change_own_password import (
    OwnPasswordActor,
    OwnPasswordCsrfFailed,
    OwnPasswordUnavailable,
)
from .models import AccountRecord, AuthenticationSessionRecord


class SqlAlchemyOwnPasswordCredentialReader:
    """Expose only the encoded hash for an active session-owned account."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_password_hash(
        self, actor: OwnPasswordActor, now: datetime
    ) -> str | None:
        """Read by session-owned account ID after checking persisted CSRF proof."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(
                        AccountRecord.password_hash,
                        AuthenticationSessionRecord.csrf_hash,
                    )
                    .join(
                        AuthenticationSessionRecord,
                        AuthenticationSessionRecord.account_id
                        == AccountRecord.account_id,
                    )
                    .where(
                        AccountRecord.account_id == actor.account_id,
                        AccountRecord.status == "active",
                        AccountRecord.deleted_at.is_(None),
                        AuthenticationSessionRecord.session_hash
                        == actor.session_digest,
                        AuthenticationSessionRecord.revoked_at.is_(None),
                        AuthenticationSessionRecord.expires_at > now,
                    )
                )
                row = result.one_or_none()
        except SQLAlchemyError:
            raise OwnPasswordUnavailable(
                "password credential authority is unavailable"
            ) from None
        if row is None:
            return None
        if not hmac.compare_digest(row.csrf_hash, actor.csrf_digest):
            raise OwnPasswordCsrfFailed("browser CSRF proof is invalid")
        return row.password_hash
