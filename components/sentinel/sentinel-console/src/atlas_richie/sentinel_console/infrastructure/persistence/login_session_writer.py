"""SQLAlchemy adapter for atomic browser-session issuance and last-login facts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.login_ports import LoginAuthorityUnavailable
from .models import AccountRecord, AuthenticationSessionRecord


class SqlAlchemyLoginSessionWriter:
    """Persist only credential digests and serialize issuance with account status."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def issue_login_session(
        self,
        *,
        account_id: str,
        session_digest: str,
        csrf_digest: str,
        session_epoch: str,
        created_at: datetime,
        expires_at: datetime,
        previous_session_digest: str | None,
    ) -> bool:
        """Conditionally write a session while the account is still active."""
        try:
            async with self._engine.begin() as connection:
                account = await connection.execute(
                    select(AccountRecord.account_id)
                    .where(
                        AccountRecord.account_id == account_id,
                        AccountRecord.status == "active",
                    )
                    .with_for_update()
                )
                if account.scalar_one_or_none() is None:
                    return False

                if previous_session_digest is not None:
                    await connection.execute(
                        update(AuthenticationSessionRecord)
                        .where(
                            AuthenticationSessionRecord.session_hash
                            == previous_session_digest,
                            AuthenticationSessionRecord.account_id == account_id,
                            AuthenticationSessionRecord.revoked_at.is_(None),
                        )
                        .values(revoked_at=created_at)
                    )

                await connection.execute(
                    insert(AuthenticationSessionRecord).values(
                        session_hash=session_digest,
                        account_id=account_id,
                        session_epoch=session_epoch,
                        csrf_hash=csrf_digest,
                        created_at=created_at,
                        expires_at=expires_at,
                        revoked_at=None,
                    )
                )
                await connection.execute(
                    update(AccountRecord)
                    .where(
                        AccountRecord.account_id == account_id,
                        AccountRecord.status == "active",
                    )
                    .values(last_login_at=created_at)
                )
        except SQLAlchemyError:
            raise LoginAuthorityUnavailable(
                "login session authority is unavailable"
            ) from None
        return True
