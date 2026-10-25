"""Atomic first-admin/source initialization inside a caller-selected SQL DB."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.bootstrap_initialization import (
    BootstrapInitializationForbidden,
    BootstrapInitializationIdempotencyConflict,
    BootstrapInitializationInput,
    BootstrapInitializationOperationReader,
    BootstrapInitializationReceipt,
    BootstrapInitializationReason,
    BootstrapInitializationStatus,
    BootstrapInitializer,
)
from ...application.bootstrap_ports import BootstrapOperatorSessionVerifier
from ...application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from ...application.errors import BootstrapAuthorityUnavailable
from ...application.bootstrap_source_check import (
    BootstrapSourceCandidate,
    ConsulDirectCredentials,
    NacosDirectCredentials,
    NoSourceAuthentication,
    SourceCredentialReference,
)
from ...domain.configuration_source import ConfigurationSourceProvider
from ...domain.session import AccountRole
from ..security.secret_cipher import AesGcmSecretCipher
from ..security.password_hash import PasswordHashService
from .models import (
    AccountRecord,
    AuditEventRecord,
    ConsoleGuardRecord,
    InitializationOperationRecord,
    RegisteredConfigurationSourceRecord,
)
from .registered_source_store import encrypt_registered_source_credentials

_FINGERPRINT_DOMAIN = b"atlas-richie-sentinel-bootstrap-initialize:v1\x00"


class _PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str: ...


class SqlAlchemyBootstrapInitializationTransaction(
    BootstrapInitializer, BootstrapInitializationOperationReader
):
    """Commit the first admin, source, receipt, audit and guard in one SQL tx.

    The engine is deliberately caller-owned and must already target the exact,
    deployment-approved database selected for this initialization. This adapter
    does not resolve network targets, create databases, run migrations, write the
    external runtime locator, or close the external setup window. Those are
    orchestration responsibilities and are not a distributed transaction.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        operator_verifier: BootstrapOperatorSessionVerifier,
        password_hasher: _PasswordHasher | None = None,
        source_secret_cipher: AesGcmSecretCipher,
        idempotency_key: bytes,
    ) -> None:
        if not isinstance(engine, AsyncEngine):
            raise TypeError("bootstrap target engine is required")
        if not isinstance(source_secret_cipher, AesGcmSecretCipher):
            raise TypeError("registered-source secret cipher is required")
        if not isinstance(idempotency_key, bytes) or len(idempotency_key) < 32:
            raise ValueError("bootstrap idempotency key must be at least 32 bytes")
        self._engine = engine
        self._operator_verifier = operator_verifier
        self._password_hasher = password_hasher or PasswordHashService()
        self._source_secret_cipher = source_secret_cipher
        self._idempotency_key = bytes(idempotency_key)

    async def initialize(
        self,
        *,
        operator_session: str,
        request_key: str,
        input: BootstrapInitializationInput,
    ) -> BootstrapInitializationReceipt:
        """Atomically establish the initialized database state or return a receipt."""
        if not await self._operator_verifier.is_current_operator(operator_session):
            raise BootstrapInitializationForbidden
        if not isinstance(input, BootstrapInitializationInput):
            raise ValueError("bootstrap input is invalid")
        session_hash = hashlib.sha256(operator_session.encode("utf-8")).hexdigest()
        input_digest = self._input_digest(input)
        now = datetime.now(UTC)
        operation_id = str(uuid4())

        try:
            async with self._engine.begin() as connection:
                guard = await connection.execute(
                    select(ConsoleGuardRecord.initialized)
                    .where(ConsoleGuardRecord.singleton_id == 1)
                    .with_for_update()
                )
                initialized = guard.scalar_one_or_none()
                if type(initialized) is not bool:
                    raise BootstrapAuthorityUnavailable(
                        "bootstrap initialization authority is unavailable"
                    )

                previous = await connection.execute(
                    select(InitializationOperationRecord.__table__)
                    .where(
                        InitializationOperationRecord.request_key == request_key
                    )
                    .with_for_update()
                )
                prior_row = previous.mappings().one_or_none()
                if prior_row is not None:
                    return self._recover(
                        prior_row,
                        session_hash=session_hash,
                        input_digest=input_digest,
                    )

                if initialized:
                    receipt = BootstrapInitializationReceipt(
                        request_key,
                        BootstrapInitializationStatus.REJECTED,
                        operation_id,
                        BootstrapInitializationReason.SETUP_CLOSED,
                    )
                    await self._insert_operation(
                        connection,
                        receipt,
                        operation_id=operation_id,
                        session_hash=session_hash,
                        input_digest=input_digest,
                        now=now,
                    )
                    await self._insert_audit(
                        connection,
                        operation_id=operation_id,
                        request_key=request_key,
                        outcome="rejected",
                        now=now,
                    )
                    return receipt

                account_id = str(uuid4())
                source_id = str(uuid4())
                account_password_hash = await asyncio.to_thread(
                    self._password_hasher.hash_password, input.admin_password.value
                )
                source_values = self._source_values(
                    input.source,
                    source_id=source_id,
                    account_id=account_id,
                    now=now,
                )
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id=account_id,
                        username=input.admin_username.value,
                        username_key=input.admin_username.lookup_key,
                        password_hash=account_password_hash,
                        role_id=AccountRole.ADMIN.value,
                        status="active",
                        built_in=True,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(RegisteredConfigurationSourceRecord).values(
                        **source_values
                    )
                )
                receipt = BootstrapInitializationReceipt(
                    request_key,
                    BootstrapInitializationStatus.COMPLETED,
                    operation_id,
                )
                await self._insert_operation(
                    connection,
                    receipt,
                    operation_id=operation_id,
                    session_hash=session_hash,
                    input_digest=input_digest,
                    now=now,
                )
                await self._insert_audit(
                    connection,
                    operation_id=operation_id,
                    request_key=request_key,
                    outcome="completed",
                    now=now,
                )
                updated = await connection.execute(
                    update(ConsoleGuardRecord)
                    .where(
                        ConsoleGuardRecord.singleton_id == 1,
                        ConsoleGuardRecord.initialized.is_(False),
                    )
                    .values(
                        initialized=True,
                        revision=ConsoleGuardRecord.revision + 1,
                        initialized_at=now,
                    )
                )
                if updated.rowcount != 1:
                    raise BootstrapAuthorityUnavailable(
                        "bootstrap initialization authority is unavailable"
                    )
                return receipt
        except (
            BootstrapInitializationForbidden,
            BootstrapInitializationIdempotencyConflict,
            BootstrapAuthorityUnavailable,
        ):
            raise
        except (SQLAlchemyError, ValueError, TypeError):
            raise BootstrapAuthorityUnavailable(
                "bootstrap initialization authority is unavailable"
            ) from None

    async def read(
        self, operator_session: str, request_key: str
    ) -> BootstrapInitializationReceipt | None:
        """Return an operation only to its original one-time setup grant."""
        session_hash = hashlib.sha256(operator_session.encode("utf-8")).hexdigest()
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(InitializationOperationRecord.__table__).where(
                        InitializationOperationRecord.request_key == request_key,
                        InitializationOperationRecord.operator_session_hash
                        == session_hash,
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise BootstrapAuthorityUnavailable(
                "bootstrap initialization authority is unavailable"
            ) from None
        return _receipt_from_row(row) if row is not None else None

    def _input_digest(self, input: BootstrapInitializationInput) -> str:
        database = input.database
        source = input.source
        auth = source.authentication
        if isinstance(auth, NoSourceAuthentication):
            authentication: dict[str, str | None] = {"mode": "none"}
        elif isinstance(auth, SourceCredentialReference):
            authentication = {
                "mode": "credential-reference",
                "reference": auth.reference,
            }
        elif isinstance(auth, NacosDirectCredentials):
            authentication = {
                "mode": "direct",
                "username": auth.username,
                "password": auth.password,
            }
        elif isinstance(auth, ConsulDirectCredentials):
            authentication = {"mode": "direct", "aclToken": auth.acl_token}
        else:
            raise ValueError("bootstrap source authentication is invalid")
        payload = {
            "database": {
                "kind": database.kind.value,
                "host": database.host,
                "port": database.port,
                "database": database.database,
                "username": database.username,
                "password": database.password,
            },
            "admin": {
                "username": input.admin_username.value,
                "password": input.admin_password.value,
            },
            "source": {
                "provider": source.provider.value,
                "endpoint": source.endpoint,
                "location": source.location,
                "authentication": authentication,
            },
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hmac.new(
            self._idempotency_key,
            _FINGERPRINT_DOMAIN + canonical,
            hashlib.sha256,
        ).hexdigest()

    def _source_values(
        self,
        source: BootstrapSourceCandidate,
        *,
        source_id: str,
        account_id: str,
        now: datetime,
    ) -> dict[str, object]:
        provider = ConfigurationSourceProvider(source.provider.value)
        connection_input = _connection_input(source, provider)
        encrypted = encrypt_registered_source_credentials(
            connection_input, source_id, self._source_secret_cipher
        )
        return {
            "source_id": source_id,
            "revision": str(uuid4()),
            "name": provider.value.capitalize(),
            "endpoint": source.endpoint,
            "provider": provider.value,
            "location": source.location,
            "authentication_mode": connection_input.authentication_mode.value,
            "credential_configured": encrypted is not None,
            "credential_cipher_format": encrypted.format.value if encrypted else None,
            "credential_key_id": encrypted.key_id if encrypted else None,
            "credential_payload": encrypted.payload if encrypted else None,
            "created_at": now,
            "updated_at": now,
            "updated_by_account_id": account_id,
        }

    @staticmethod
    async def _insert_operation(
        connection,
        receipt: BootstrapInitializationReceipt,
        *,
        operation_id: str,
        session_hash: str,
        input_digest: str,
        now: datetime,
    ) -> None:
        await connection.execute(
            insert(InitializationOperationRecord).values(
                request_key=receipt.request_key,
                operation_id=operation_id,
                operator_session_hash=session_hash,
                input_digest=input_digest,
                status=receipt.status.value,
                reason=receipt.reason.value if receipt.reason else None,
                created_at=now,
                updated_at=now,
            )
        )

    @staticmethod
    async def _insert_audit(
        connection,
        *,
        operation_id: str,
        request_key: str,
        outcome: str,
        now: datetime,
    ) -> None:
        await connection.execute(
            insert(AuditEventRecord).values(
                event_id=operation_id,
                request_id=request_key,
                actor_account_id=None,
                action="system.bootstrap.initialize",
                outcome=outcome,
                target_kind="initialization",
                target_id=operation_id,
                created_at=now,
            )
        )

    @staticmethod
    def _recover(
        row,
        *,
        session_hash: str,
        input_digest: str,
    ) -> BootstrapInitializationReceipt:
        if not hmac.compare_digest(row["operator_session_hash"], session_hash):
            raise BootstrapInitializationForbidden
        if not hmac.compare_digest(row["input_digest"], input_digest):
            raise BootstrapInitializationIdempotencyConflict
        return _receipt_from_row(row)


def _receipt_from_row(row) -> BootstrapInitializationReceipt:
    status = BootstrapInitializationStatus(row["status"])
    reason = (
        BootstrapInitializationReason(row["reason"])
        if row["reason"] is not None
        else None
    )
    return BootstrapInitializationReceipt(
        row["request_key"], status, row["operation_id"], reason
    )


def _connection_input(
    source: BootstrapSourceCandidate,
    provider: ConfigurationSourceProvider,
) -> SourceConnectionInput:
    auth = source.authentication
    common = {
        "source_id": None,
        "expected_revision": None,
        "provider": provider,
        "endpoint": source.endpoint,
        "location": source.location,
    }
    if isinstance(auth, NoSourceAuthentication):
        return SourceConnectionInput(
            **common, authentication_mode=SourceCheckAuthenticationMode.NONE
        )
    if isinstance(auth, SourceCredentialReference):
        return SourceConnectionInput(
            **common,
            authentication_mode=SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
            credential_reference=auth.reference,
        )
    if isinstance(auth, NacosDirectCredentials):
        return SourceConnectionInput(
            **common,
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username=auth.username,
            password=auth.password,
        )
    if isinstance(auth, ConsulDirectCredentials):
        return SourceConnectionInput(
            **common,
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token=auth.acl_token,
        )
    raise ValueError("bootstrap source authentication is invalid")


__all__ = ["SqlAlchemyBootstrapInitializationTransaction"]
