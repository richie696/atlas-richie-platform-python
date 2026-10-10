"""Atomic SQLAlchemy password replacement, session invalidation and audit."""

from __future__ import annotations

import hmac
from datetime import datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.change_own_password import (
    OwnPasswordActor,
    OwnPasswordCsrfFailed,
    OwnPasswordUnauthenticated,
    OwnPasswordUnavailable,
)
from .models import AccountRecord, AuditEventRecord, AuthenticationSessionRecord


class SqlAlchemyOwnPasswordWriter:
    """Change a password only while its verifying session/hash remain current."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def change_password(
        self,
        *,
        actor: OwnPasswordActor,
        expected_password_hash: str,
        replacement_password_hash: str,
        request_id: str,
        now: datetime,
    ) -> bool:
        """Persist the new hash, revoke every account session, and audit atomically."""
        try:
            async with self._engine.begin() as connection:
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
                        AuthenticationSessionRecord.session_hash
                        == actor.session_digest,
                        AuthenticationSessionRecord.revoked_at.is_(None),
                        AuthenticationSessionRecord.expires_at > now,
                    )
                    .with_for_update()
                )
                row = result.one_or_none()
                if row is None:
                    raise OwnPasswordUnauthenticated(
                        "current browser session is inactive"
                    )
                if not hmac.compare_digest(row.csrf_hash, actor.csrf_digest):
                    raise OwnPasswordCsrfFailed("browser CSRF proof is invalid")
                if not hmac.compare_digest(
                    row.password_hash, expected_password_hash
                ):
                    raise OwnPasswordUnauthenticated(
                        "current password is no longer valid"
                    )

                await connection.execute(
                    update(AccountRecord)
                    .where(AccountRecord.account_id == actor.account_id)
                    .values(
                        password_hash=replacement_password_hash,
                        revision=AccountRecord.revision + 1,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    update(AuthenticationSessionRecord)
                    .where(
                        AuthenticationSessionRecord.account_id == actor.account_id,
                        AuthenticationSessionRecord.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=str(uuid4()),
                        request_id=request_id,
                        actor_account_id=actor.account_id,
                        action="auth.password.change",
                        outcome="completed",
                        target_kind="account",
                        target_id=actor.account_id,
                        created_at=now,
                    )
                )
        except (OwnPasswordCsrfFailed, OwnPasswordUnauthenticated):
            raise
        except SQLAlchemyError:
            raise OwnPasswordUnavailable(
                "password change authority is unavailable"
            ) from None
        return True
