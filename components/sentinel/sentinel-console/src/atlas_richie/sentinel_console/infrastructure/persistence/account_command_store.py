"""SQLAlchemy adapter for atomic, idempotent administrator account commands."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.account_commands import (
    AccountCommandActor,
    AccountCommandCsrfFailed,
    AccountCommandForbidden,
    AccountCommandIdempotencyConflict,
    AccountCommandKind,
    AccountCommandReason,
    AccountCommandStore,
    AccountCommandUnauthenticated,
    AccountCommandUnavailable,
    AccountOperation,
    AccountOperationActor,
    AccountOperationStatus,
    AccountOperationUnavailable,
    AccountMutation,
    KeyedFingerprint,
)
from ...application.account_directory_ports import AccountDirectoryItem
from ...domain.session import AccountRole
from .models import (
    AccountRecord,
    AccountOperationRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    ConsoleGuardRecord,
)


class SqlAlchemyAccountCommandStore(AccountCommandStore):
    """Recheck authority and atomically commit mutation, receipt, and audit."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def execute_command(
        self,
        *,
        actor: AccountCommandActor,
        command: AccountMutation,
        fingerprints: tuple[KeyedFingerprint, ...],
        password_hash: str | None,
        account_id: str,
        operation_id: str,
        audit_event_id: str,
        request_id: str,
        now: datetime,
    ) -> AccountOperation:
        """Execute at most once under the singleton guard transaction."""
        try:
            async with self._engine.begin() as connection:
                await self._lock_guard(connection)
                await self._authorize(connection, actor, now)
                previous = await connection.execute(
                    select(AccountOperationRecord.__table__)
                    .where(AccountOperationRecord.request_key == command.request_key)
                    .with_for_update()
                )
                prior_record = previous.mappings().one_or_none()
                if prior_record is not None:
                    return self._recover(prior_record, actor, fingerprints)

                operation = await self._apply(
                    connection,
                    command=command,
                    password_hash=password_hash,
                    account_id=account_id,
                    now=now,
                )
                snapshot = operation.account
                audit_target_id = (
                    snapshot.account_id if snapshot else command.account_id
                )
                if (
                    audit_target_id is None
                    and command.kind is AccountCommandKind.CREATE
                    and operation.reason is AccountCommandReason.USERNAME_TAKEN
                    and command.username is not None
                ):
                    audit_target_id = await connection.scalar(
                        select(AccountRecord.account_id).where(
                            AccountRecord.username_key == command.username.lookup_key
                        )
                    )
                active_fingerprint = fingerprints[0]
                await connection.execute(
                    insert(AccountOperationRecord).values(
                        request_key=command.request_key,
                        operation_id=operation_id,
                        actor_account_id=actor.account_id,
                        fingerprint_key_id=active_fingerprint.key_id,
                        fingerprint_digest=active_fingerprint.digest,
                        status=operation.status.value,
                        reason=operation.reason.value if operation.reason else None,
                        account_id=snapshot.account_id if snapshot else None,
                        account_username=snapshot.username if snapshot else None,
                        account_role_id=snapshot.role_id if snapshot else None,
                        account_status=snapshot.status if snapshot else None,
                        account_built_in=snapshot.built_in if snapshot else None,
                        account_last_login_at=(
                            snapshot.last_login_at if snapshot else None
                        ),
                        account_revision=snapshot.revision if snapshot else None,
                        account_last_active_admin=(
                            snapshot.last_active_admin if snapshot else None
                        ),
                        created_at=now,
                    )
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=audit_event_id,
                        request_id=request_id,
                        actor_account_id=actor.account_id,
                        action=f"accounts.{command.kind.value}",
                        outcome=(
                            "completed"
                            if operation.status is AccountOperationStatus.COMPLETED
                            else "rejected"
                        ),
                        target_kind="account",
                        target_id=audit_target_id,
                        created_at=now,
                    )
                )
                return operation
        except (AccountCommandCsrfFailed, AccountCommandForbidden,
                AccountCommandIdempotencyConflict, AccountCommandUnauthenticated):
            raise
        except SQLAlchemyError:
            raise AccountCommandUnavailable(
                "account command authority is unavailable"
            ) from None

    async def read_operation(
        self, request_key: str, actor: AccountOperationActor
    ) -> AccountOperation | None:
        """Return the immutable receipt only to the actor that created it."""
        try:
            async with self._engine.begin() as connection:
                await self._authorize_operation_reader(connection, actor)
                result = await connection.execute(
                    select(AccountOperationRecord.__table__).where(
                        AccountOperationRecord.request_key == request_key,
                        AccountOperationRecord.actor_account_id == actor.account_id,
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise AccountOperationUnavailable(
                "account operation history is unavailable"
            ) from None
        return _operation_from_record(row) if row is not None else None

    async def _authorize_operation_reader(
        self, connection, actor: AccountOperationActor
    ) -> None:
        result = await connection.execute(
            select(AccountRecord.role_id)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor.account_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == actor.session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        role_id = result.scalar_one_or_none()
        if role_id is None:
            raise AccountCommandUnauthenticated("browser session is inactive")
        if role_id != AccountRole.ADMIN.value:
            raise AccountCommandForbidden("administrator role is required")

    async def _lock_guard(self, connection) -> None:
        result = await connection.execute(
            select(ConsoleGuardRecord.initialized)
            .where(ConsoleGuardRecord.singleton_id == 1)
            .with_for_update()
        )
        initialized = result.scalar_one_or_none()
        if initialized is None or not initialized:
            raise AccountCommandUnavailable("account command guard is unavailable")

    async def _authorize(
        self, connection, actor: AccountCommandActor, now: datetime
    ) -> None:
        result = await connection.execute(
            select(
                AccountRecord.role_id,
                AuthenticationSessionRecord.csrf_hash,
            )
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor.account_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == actor.session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > now,
            )
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            raise AccountCommandUnauthenticated("browser session is inactive")
        if not hmac.compare_digest(row.csrf_hash, actor.csrf_digest):
            raise AccountCommandCsrfFailed("browser CSRF proof is invalid")
        if row.role_id != AccountRole.ADMIN.value:
            raise AccountCommandForbidden("administrator role is required")

    async def _apply(
        self,
        connection,
        *,
        command: AccountMutation,
        password_hash: str | None,
        account_id: str,
        now: datetime,
    ) -> AccountOperation:
        if command.kind is AccountCommandKind.CREATE:
            if (
                password_hash is None
                or command.username is None
                or command.role_id is None
            ):
                raise AccountCommandUnavailable(
                    "validated account create input is missing"
                )
            duplicate = await connection.scalar(
                select(AccountRecord.account_id).where(
                    AccountRecord.username_key == command.username.lookup_key
                )
            )
            if duplicate is not None:
                return _rejected(
                    command.request_key, AccountCommandReason.USERNAME_TAKEN
                )
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=command.username.value,
                    username_key=command.username.lookup_key,
                    password_hash=password_hash,
                    role_id=command.role_id.value,
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            row = await self._account_row(connection, account_id)
            return AccountOperation(
                command.request_key,
                AccountOperationStatus.COMPLETED,
                _directory_item(row, await self._active_admin_count(connection)),
            )

        assert command.account_id is not None
        assert command.expected_revision is not None
        result = await connection.execute(
            select(
                AccountRecord.account_id,
                AccountRecord.role_id,
                AccountRecord.status,
                AccountRecord.built_in,
                AccountRecord.revision,
            )
            .where(AccountRecord.account_id == command.account_id)
            .with_for_update()
        )
        account = result.mappings().one_or_none()
        if account is None:
            return _rejected(command.request_key, AccountCommandReason.NOT_FOUND)
        if account["revision"] != command.expected_revision:
            return _rejected(command.request_key, AccountCommandReason.CONFLICT)
        if account["built_in"]:
            return _rejected(command.request_key, AccountCommandReason.BUILT_IN)

        removes_active_admin = account["role_id"] == AccountRole.ADMIN.value and (
            (command.kind is AccountCommandKind.STATUS and command.status == "disabled")
            or (
                command.kind is AccountCommandKind.ROLE
                and command.role_id is AccountRole.VIEW
            )
        ) and account["status"] == "active"
        if removes_active_admin and await self._active_admin_count(connection) <= 1:
            return _rejected(command.request_key, AccountCommandReason.LAST_ADMIN)

        values: dict[str, object] = {
            "revision": account["revision"] + 1,
            "updated_at": now,
        }
        if command.kind is AccountCommandKind.STATUS:
            assert command.status is not None
            if command.status == account["status"]:
                values = {}
            else:
                values["status"] = command.status
        else:
            assert command.role_id is not None
            if command.role_id.value == account["role_id"]:
                values = {}
            else:
                values["role_id"] = command.role_id.value
        if values:
            await connection.execute(
                update(AccountRecord)
                .where(
                    AccountRecord.account_id == account["account_id"],
                    AccountRecord.revision == command.expected_revision,
                )
                .values(**values)
            )
        row = await self._account_row(connection, account["account_id"])
        return AccountOperation(
            command.request_key,
            AccountOperationStatus.COMPLETED,
            _directory_item(row, await self._active_admin_count(connection)),
        )

    async def _account_row(self, connection, account_id: str):
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
        return result.mappings().one()

    async def _active_admin_count(self, connection) -> int:
        from sqlalchemy import func

        return int(
            await connection.scalar(
                select(func.count())
                .select_from(AccountRecord)
                .where(
                    AccountRecord.role_id == AccountRole.ADMIN.value,
                    AccountRecord.status == "active",
                )
            )
            or 0
        )

    def _recover(
        self,
        record,
        actor: AccountCommandActor,
        fingerprints: tuple[KeyedFingerprint, ...],
    ) -> AccountOperation:
        candidates = {item.key_id: item.digest for item in fingerprints}
        candidate = candidates.get(record["fingerprint_key_id"])
        if (
            record["actor_account_id"] != actor.account_id
            or candidate is None
            or not hmac.compare_digest(record["fingerprint_digest"], candidate)
        ):
            raise AccountCommandIdempotencyConflict(
                "request key belongs to another command"
            )
        return _operation_from_record(record)


def _rejected(request_key: str, reason: AccountCommandReason) -> AccountOperation:
    return AccountOperation(
        request_key, AccountOperationStatus.REJECTED, reason=reason
    )


def _operation_from_record(record) -> AccountOperation:
    status = AccountOperationStatus(record["status"])
    if status is AccountOperationStatus.REJECTED:
        assert record["reason"] is not None
        return AccountOperation(
            record["request_key"], status,
            reason=AccountCommandReason(record["reason"]),
        )
    assert record["account_id"] is not None
    assert record["account_username"] is not None
    assert record["account_role_id"] is not None
    assert record["account_status"] is not None
    assert record["account_built_in"] is not None
    assert record["account_revision"] is not None
    assert record["account_last_active_admin"] is not None
    last_login = record["account_last_login_at"]
    if last_login is not None and last_login.tzinfo is None:
        last_login = last_login.replace(tzinfo=UTC)
    return AccountOperation(
        record["request_key"],
        status,
        account=AccountDirectoryItem(
            account_id=record["account_id"],
            username=record["account_username"],
            role_id=record["account_role_id"],
            status=record["account_status"],
            built_in=record["account_built_in"],
            last_login_at=last_login,
            revision=record["account_revision"],
            last_active_admin=record["account_last_active_admin"],
        ),
    )


def _directory_item(row, active_admin_count: int) -> AccountDirectoryItem:
    active_admin = (
        row["role_id"] == AccountRole.ADMIN.value and row["status"] == "active"
    )
    last_login_at = row["last_login_at"]
    if last_login_at is not None and last_login_at.tzinfo is None:
        last_login_at = last_login_at.replace(tzinfo=UTC)
    return AccountDirectoryItem(
        account_id=str(row["account_id"]),
        username=str(row["username"]),
        role_id=str(row["role_id"]),
        status=str(row["status"]),
        built_in=bool(row["built_in"]),
        last_login_at=last_login_at,
        revision=int(row["revision"]),
        last_active_admin=active_admin and active_admin_count == 1,
    )
