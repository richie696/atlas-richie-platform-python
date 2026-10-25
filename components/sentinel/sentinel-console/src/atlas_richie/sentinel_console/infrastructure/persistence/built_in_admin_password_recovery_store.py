"""SQL adapter for the explicitly local built-in admin recovery command."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.recover_built_in_admin_password import (
    AdminPasswordRecoveryResult,
    BuiltInAdminPasswordRecoveryStore,
)
from ...domain.session import AccountRole
from .models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    ConsoleGuardRecord,
)


class LocalBuiltInAdminPasswordRecoveryStore(BuiltInAdminPasswordRecoveryStore):
    """Commit password replacement, session revocation, and audit atomically."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def recover_built_in_admin_password(
        self,
        *,
        password_hash: str,
        now: datetime,
        event_id: str,
        request_id: str,
    ) -> AdminPasswordRecoveryResult:
        """Update exactly one built-in admin; never create or enable accounts."""
        try:
            async with self._engine.begin() as connection:
                initialized = await connection.scalar(
                    select(ConsoleGuardRecord.initialized)
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .with_for_update()
                )
                if initialized is not True:
                    raise RuntimeError("Sentinel is not initialized")

                rows = await connection.execute(
                    select(
                        AccountRecord.account_id,
                        AccountRecord.username,
                        AccountRecord.role_id,
                        AccountRecord.status,
                        AccountRecord.revision,
                    )
                    .where(
                        AccountRecord.built_in.is_(True),
                        AccountRecord.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                admins = rows.mappings().all()
                if len(admins) != 1:
                    raise RuntimeError(
                        "Expected exactly one built-in administrator account"
                    )
                admin = admins[0]
                if (
                    admin["role_id"] != AccountRole.ADMIN.value
                    or admin["status"] != "active"
                ):
                    raise RuntimeError(
                        "Built-in administrator account is not in a recoverable state"
                    )

                await connection.execute(
                    update(AccountRecord)
                    .where(AccountRecord.account_id == admin["account_id"])
                    .values(
                        password_hash=password_hash,
                        revision=admin["revision"] + 1,
                        updated_at=now,
                    )
                )
                revoked = await connection.execute(
                    update(AuthenticationSessionRecord)
                    .where(
                        AuthenticationSessionRecord.account_id
                        == admin["account_id"],
                        AuthenticationSessionRecord.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=event_id,
                        request_id=request_id,
                        actor_account_id=None,
                        action="accounts.local_password_recovery",
                        outcome="completed",
                        target_kind="account",
                        target_id=admin["account_id"],
                        created_at=now,
                    )
                )
                return AdminPasswordRecoveryResult(
                    username=admin["username"],
                    revoked_sessions=max(0, int(revoked.rowcount or 0)),
                )
        except RuntimeError:
            raise
        except SQLAlchemyError:
            raise RuntimeError(
                "Database recovery failed; no password change was committed"
            ) from None
