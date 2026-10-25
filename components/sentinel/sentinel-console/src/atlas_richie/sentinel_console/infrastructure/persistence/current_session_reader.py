"""SQLAlchemy adapter for active account-session lookup."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.errors import SessionAuthorityUnavailable
from ...domain.session import ActiveAccountSession
from .models import AccountRecord, AuthenticationSessionRecord


class SqlAlchemyCurrentSessionReader:
    """Resolve a session digest against live session and account state."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def read_active_session(
        self, session_digest: str
    ) -> ActiveAccountSession | None:
        """Exclude expired/revoked sessions and disabled accounts on every read."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(
                        AccountRecord.account_id,
                        AccountRecord.username,
                        AccountRecord.role_id,
                        AuthenticationSessionRecord.session_epoch,
                    )
                    .join(
                        AuthenticationSessionRecord,
                        AuthenticationSessionRecord.account_id
                        == AccountRecord.account_id,
                    )
                    .where(
                        AuthenticationSessionRecord.session_hash == session_digest,
                        AuthenticationSessionRecord.revoked_at.is_(None),
                        AuthenticationSessionRecord.expires_at > datetime.now(UTC),
                        AccountRecord.status == "active",
                        AccountRecord.deleted_at.is_(None),
                    )
                )
                row = result.one_or_none()
        except SQLAlchemyError:
            raise SessionAuthorityUnavailable(
                "current session authority is unavailable"
            ) from None

        if row is None:
            return None
        return ActiveAccountSession(
            account_id=row.account_id,
            username=row.username,
            role_id=row.role_id,
            session_epoch=row.session_epoch,
        )
