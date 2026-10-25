"""SQLAlchemy adapter for atomic current-session revocation."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.errors import SessionAuthorityUnavailable
from ...domain.session import SessionRevocationResult
from .models import AuthenticationSessionRecord


class SqlAlchemyCurrentSessionRevoker:
    """Compare hashed CSRF proof and revoke only a live, unrevoked session."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def revoke_active_session(
        self,
        session_digest: str,
        csrf_digest: str,
        revoked_at: datetime,
    ) -> SessionRevocationResult:
        """Apply a conditional update so concurrent logout stays idempotent."""
        try:
            async with self._engine.begin() as connection:
                result = await connection.execute(
                    select(
                        AuthenticationSessionRecord.csrf_hash,
                        AuthenticationSessionRecord.expires_at,
                        AuthenticationSessionRecord.revoked_at,
                    ).where(AuthenticationSessionRecord.session_hash == session_digest)
                )
                row = result.one_or_none()
                if row is None:
                    return SessionRevocationResult.UNAUTHENTICATED

                now = datetime.now(UTC)
                expires_at = row.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if row.revoked_at is not None or expires_at <= now:
                    return SessionRevocationResult.UNAUTHENTICATED
                if not hmac.compare_digest(row.csrf_hash, csrf_digest):
                    return SessionRevocationResult.CSRF_FAILED

                result = await connection.execute(
                    update(AuthenticationSessionRecord)
                    .where(
                        AuthenticationSessionRecord.session_hash == session_digest,
                        AuthenticationSessionRecord.csrf_hash == csrf_digest,
                        AuthenticationSessionRecord.revoked_at.is_(None),
                        AuthenticationSessionRecord.expires_at > now,
                    )
                    .values(revoked_at=revoked_at)
                )
                if result.rowcount != 1:
                    return SessionRevocationResult.UNAUTHENTICATED
        except SQLAlchemyError:
            raise SessionAuthorityUnavailable(
                "current session authority is unavailable"
            ) from None

        return SessionRevocationResult.REVOKED
