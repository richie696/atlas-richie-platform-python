"""SQL adapter for the independent encrypted monitoring-source registry."""

from __future__ import annotations

import json
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from secrets import compare_digest
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ...application.monitoring_source_registry import (
    MonitoringCredentialUpdateMode,
    MonitoringSourceCommandForbidden,
    MonitoringSourceCommandUnavailable,
    MonitoringSourceIdempotencyConflict,
    MonitoringSourceNotFound,
    MonitoringSourceMutation,
    MonitoringSourceOperation,
    MonitoringSourceOperationReason,
    MonitoringSourceOperationStatus,
    MonitoringSourceRegistryPort,
    MonitoringSourceRegistryUnavailable,
    MonitoringSourceRevisionConflict,
    MonitoringSourceSecret,
)
from ...domain.monitoring_sources import (
    MAX_MONITORING_SOURCES,
    MonitoringAuthenticationMode,
    MonitoringLabel,
    MonitoringProfile,
    MonitoringProvider,
    MonitoringSource,
    MonitoringSourcesSnapshot,
)
from ..security.secret_cipher import (
    AesGcmSecretCipher,
    EncryptedSecret,
    SecretCipherError,
    SecretCipherFormat,
    SecretContext,
)
from .models import (
    AuditEventRecord,
    HostInstanceAssociationRecord,
    MonitoringProbeReceiptRecord,
    MonitoringSourceOperationRecord,
    MonitoringSourceRecord,
)

_CREDENTIAL_CONTEXT = "monitoring-source"
_CREDENTIAL_FIELD = "authentication"


class SQLAlchemyMonitoringSourceStore(MonitoringSourceRegistryPort):
    """Persist source metadata and authenticated ciphertext through SQLAlchemy."""

    def __init__(
        self,
        engine_resolver: Callable[[], Awaitable[AsyncEngine]],
        secret_cipher: AesGcmSecretCipher,
        fingerprint_key: bytes | None = None,
    ) -> None:
        if fingerprint_key is not None and (
            not isinstance(fingerprint_key, bytes) or len(fingerprint_key) < 32
        ):
            raise ValueError("monitoring command fingerprint key is invalid")
        self._engine_resolver = engine_resolver
        self._secret_cipher = secret_cipher
        self._fingerprint_key = fingerprint_key

    async def read_monitoring_sources(self) -> MonitoringSourcesSnapshot:
        try:
            factory = await self._session_factory()
            async with factory() as session:
                rows = (
                    await session.scalars(
                        select(MonitoringSourceRecord)
                        .order_by(
                            MonitoringSourceRecord.environment_id,
                            MonitoringSourceRecord.display_name,
                            MonitoringSourceRecord.source_id,
                        )
                        .limit(MAX_MONITORING_SOURCES + 1)
                    )
                ).all()
            if len(rows) > MAX_MONITORING_SOURCES:
                raise MonitoringSourceRegistryUnavailable
            sources = tuple(_source_from_row(row) for row in rows)
            return MonitoringSourcesSnapshot(_now_utc(), sources)
        except MonitoringSourceRegistryUnavailable:
            raise
        except (SQLAlchemyError, TypeError, ValueError, KeyError):
            raise MonitoringSourceRegistryUnavailable from None

    async def read_monitoring_source(self, source_id: str) -> MonitoringSource:
        try:
            factory = await self._session_factory()
            async with factory() as session:
                row = await session.get(MonitoringSourceRecord, source_id)
            if row is None:
                raise MonitoringSourceNotFound
            return _source_from_row(row)
        except MonitoringSourceNotFound:
            raise
        except (SQLAlchemyError, TypeError, ValueError, KeyError):
            raise MonitoringSourceRegistryUnavailable from None

    async def create_monitoring_source(
        self,
        source: MonitoringSource,
        *,
        secret: MonitoringSourceSecret | None,
        now: datetime,
    ) -> MonitoringSource:
        instant = _aware_utc(now)
        envelope = _encrypt_credentials(source, secret, self._secret_cipher)
        revision = uuid4().hex
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                count = await session.scalar(
                    select(func.count()).select_from(MonitoringSourceRecord)
                )
                if count is not None and count >= MAX_MONITORING_SOURCES:
                    raise MonitoringSourceRegistryUnavailable
                session.add(
                    _record(
                        replace(source, revision=revision),
                        envelope,
                        created_at=instant,
                        updated_at=instant,
                    )
                )
                await session.flush()
            return replace(source, revision=revision)
        except MonitoringSourceRegistryUnavailable:
            raise
        except IntegrityError:
            raise MonitoringSourceRevisionConflict from None
        except SQLAlchemyError:
            raise MonitoringSourceRegistryUnavailable from None

    async def update_monitoring_source(
        self,
        source: MonitoringSource,
        *,
        expected_revision: str,
        credential_update: MonitoringCredentialUpdateMode,
        secret: MonitoringSourceSecret | None,
        now: datetime,
    ) -> MonitoringSource:
        instant = _aware_utc(now)
        next_secret: EncryptedSecret | None = None
        revision = uuid4().hex
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                current = await session.scalar(
                    select(MonitoringSourceRecord)
                    .where(MonitoringSourceRecord.source_id == source.source_id)
                    .with_for_update()
                )
                if current is None:
                    raise MonitoringSourceNotFound
                if not compare_digest(current.revision, expected_revision):
                    raise MonitoringSourceRevisionConflict
                next_secret = _secret_for_update(
                    source,
                    current,
                    credential_update,
                    secret,
                    self._secret_cipher,
                )
                values = _record_values(
                    replace(source, revision=revision),
                    next_secret,
                    created_at=_stored_utc(current.created_at),
                    updated_at=instant,
                )
                result = await session.execute(
                    update(MonitoringSourceRecord)
                    .where(
                        MonitoringSourceRecord.source_id == source.source_id,
                        MonitoringSourceRecord.revision == expected_revision,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise MonitoringSourceRevisionConflict
                await session.execute(
                    delete(MonitoringProbeReceiptRecord).where(
                        MonitoringProbeReceiptRecord.source_id == source.source_id
                    )
                )
            return replace(source, revision=revision)
        except (MonitoringSourceNotFound, MonitoringSourceRevisionConflict):
            raise
        except (SQLAlchemyError, TypeError, ValueError, KeyError, SecretCipherError):
            raise MonitoringSourceRegistryUnavailable from None

    async def delete_monitoring_source(
        self,
        source_id: str,
        *,
        expected_revision: str,
        now: datetime,
    ) -> None:
        _aware_utc(now)
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                current = await session.scalar(
                    select(MonitoringSourceRecord)
                    .where(MonitoringSourceRecord.source_id == source_id)
                    .with_for_update()
                )
                if current is None:
                    raise MonitoringSourceNotFound
                if not compare_digest(current.revision, expected_revision):
                    raise MonitoringSourceRevisionConflict
                result = await session.execute(
                    delete(MonitoringSourceRecord).where(
                        MonitoringSourceRecord.source_id == source_id,
                        MonitoringSourceRecord.revision == expected_revision,
                    )
                )
                if result.rowcount != 1:
                    raise MonitoringSourceRevisionConflict
                await session.execute(
                    delete(MonitoringProbeReceiptRecord).where(
                        MonitoringProbeReceiptRecord.source_id == source_id
                    )
                )
        except (MonitoringSourceNotFound, MonitoringSourceRevisionConflict):
            raise
        except SQLAlchemyError:
            raise MonitoringSourceRegistryUnavailable from None

    async def resolve_monitoring_source_secret(
        self, source_id: str, *, expected_revision: str
    ) -> MonitoringSourceSecret | None:
        try:
            factory = await self._session_factory()
            async with factory() as session:
                row = await session.get(MonitoringSourceRecord, source_id)
            if row is None:
                raise MonitoringSourceNotFound
            if not compare_digest(row.revision, expected_revision):
                raise MonitoringSourceRevisionConflict
            envelope = _encrypted_from_row(row)
            if envelope is None:
                return None
            plaintext = self._secret_cipher.decrypt(
                envelope,
                SecretContext(_CREDENTIAL_CONTEXT, source_id, _CREDENTIAL_FIELD),
            )
            decoded = json.loads(plaintext)
            return _secret_from_document(row.authentication_mode, decoded)
        except (MonitoringSourceNotFound, MonitoringSourceRevisionConflict):
            raise
        except (
            SQLAlchemyError,
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            SecretCipherError,
        ):
            raise MonitoringSourceRegistryUnavailable from None

    async def execute_monitoring_source_mutation(
        self, command: MonitoringSourceMutation
    ) -> MonitoringSourceOperation:
        """Commit registry change, consumed probe receipt, audit and replay fact atomically."""
        if self._fingerprint_key is None:
            raise MonitoringSourceCommandUnavailable
        instant = _aware_utc(command.now or _now_utc())
        fingerprint = _command_fingerprint(command, self._fingerprint_key)
        try:
            factory = await self._session_factory()
            async with factory.begin() as session:
                previous = await session.scalar(
                    select(MonitoringSourceOperationRecord)
                    .where(
                        MonitoringSourceOperationRecord.request_key
                        == command.request_key
                    )
                    .with_for_update()
                )
                if previous is not None:
                    return _replay_operation(previous, command, fingerprint)

                verified = False
                if command.kind == "delete":
                    result = await self._delete_in_transaction(session, command)
                elif command.kind == "set-enabled":
                    result = await self._set_enabled_in_transaction(session, command, instant)
                else:
                    assert command.source is not None
                    if command.check_id is not None:
                        verified = await self._consume_check_in_transaction(
                            session, command, instant
                        )
                        if not verified:
                            result = _rejected_operation(
                                command,
                                MonitoringSourceOperationReason.CHECK_MISMATCH,
                            )
                            self._persist_operation(
                                session, command, fingerprint, result, instant
                            )
                            self._persist_audit(session, command, result, instant)
                            return result
                    elif not command.skip_check:
                        result = _rejected_operation(
                            command,
                            MonitoringSourceOperationReason.CHECK_REQUIRED,
                        )
                        self._persist_operation(
                            session, command, fingerprint, result, instant
                        )
                        self._persist_audit(session, command, result, instant)
                        return result
                    if command.kind == "create":
                        result = await self._create_in_transaction(
                            session, command, instant, verified
                        )
                    else:
                        result = await self._update_in_transaction(
                            session, command, instant, verified
                        )
                self._persist_operation(session, command, fingerprint, result, instant)
                self._persist_audit(session, command, result, instant)
                return result
        except (
            MonitoringSourceCommandForbidden,
            MonitoringSourceIdempotencyConflict,
        ):
            raise
        except (SQLAlchemyError, TypeError, ValueError, KeyError, SecretCipherError):
            raise MonitoringSourceCommandUnavailable from None

    async def read_monitoring_source_operation(
        self, request_key: str, *, actor_id: str, session_digest: str
    ) -> MonitoringSourceOperation | None:
        if not request_key or not actor_id or len(session_digest) != 64:
            return None
        try:
            factory = await self._session_factory()
            async with factory() as session:
                row = await session.get(MonitoringSourceOperationRecord, request_key)
            if row is None:
                return None
            if row.actor_account_id != actor_id or not compare_digest(
                row.session_hash, session_digest
            ):
                raise MonitoringSourceCommandForbidden
            return _operation_from_row(row)
        except MonitoringSourceCommandForbidden:
            raise
        except SQLAlchemyError:
            raise MonitoringSourceCommandUnavailable from None

    async def _create_in_transaction(
        self,
        session: AsyncSession,
        command: MonitoringSourceMutation,
        instant: datetime,
        verified: bool,
    ) -> MonitoringSourceOperation:
        source = command.source
        assert source is not None
        count = await session.scalar(
            select(func.count()).select_from(MonitoringSourceRecord)
        )
        if count is not None and count >= MAX_MONITORING_SOURCES:
            return _rejected_operation(
                command, MonitoringSourceOperationReason.CONFLICT
            )
        if await session.get(MonitoringSourceRecord, source.source_id) is not None:
            return _rejected_operation(
                command, MonitoringSourceOperationReason.CONFLICT
            )
        envelope = _encrypt_credentials(source, command.secret, self._secret_cipher)
        revision = uuid4().hex
        persisted = replace(source, revision=revision)
        session.add(
            _record(persisted, envelope, created_at=instant, updated_at=instant)
        )
        await session.flush()
        return _completed_operation(persisted, command.request_key, verified)

    async def _update_in_transaction(
        self,
        session: AsyncSession,
        command: MonitoringSourceMutation,
        instant: datetime,
        verified: bool,
    ) -> MonitoringSourceOperation:
        source = command.source
        expected_revision = command.expected_revision
        assert source is not None and expected_revision is not None
        current = await session.scalar(
            select(MonitoringSourceRecord)
            .where(MonitoringSourceRecord.source_id == source.source_id)
            .with_for_update()
        )
        if current is None:
            return _rejected_operation(
                command, MonitoringSourceOperationReason.NOT_FOUND
            )
        if not compare_digest(current.revision, expected_revision):
            return _rejected_operation(
                command, MonitoringSourceOperationReason.CONFLICT
            )
        if command.credential_update is None:
            return _rejected_operation(
                command, MonitoringSourceOperationReason.CHECK_MISMATCH
            )
        envelope = _secret_for_update(
            source,
            current,
            command.credential_update,
            command.secret,
            self._secret_cipher,
        )
        revision = uuid4().hex
        persisted = replace(source, revision=revision)
        await session.execute(
            update(MonitoringSourceRecord)
            .where(
                MonitoringSourceRecord.source_id == source.source_id,
                MonitoringSourceRecord.revision == expected_revision,
            )
            .values(
                **_record_values(
                    persisted,
                    envelope,
                    created_at=_stored_utc(current.created_at),
                    updated_at=instant,
                )
            )
        )
        await session.execute(
            delete(MonitoringProbeReceiptRecord).where(
                MonitoringProbeReceiptRecord.source_id == source.source_id
            )
        )
        return _completed_operation(persisted, command.request_key, verified)

    async def _delete_in_transaction(
        self, session: AsyncSession, command: MonitoringSourceMutation
    ) -> MonitoringSourceOperation:
        source_id = command.source_id
        expected_revision = command.expected_revision
        assert source_id is not None and expected_revision is not None
        current = await session.scalar(
            select(MonitoringSourceRecord)
            .where(MonitoringSourceRecord.source_id == source_id)
            .with_for_update()
        )
        if current is None:
            return _rejected_operation(
                command, MonitoringSourceOperationReason.NOT_FOUND
            )
        if not compare_digest(current.revision, expected_revision):
            return _rejected_operation(
                command, MonitoringSourceOperationReason.CONFLICT
            )
        association_count = await session.scalar(
            select(func.count())
            .select_from(HostInstanceAssociationRecord)
            .where(HostInstanceAssociationRecord.source_id == source_id)
        )
        if association_count:
            return _rejected_operation(
                command, MonitoringSourceOperationReason.SOURCE_IN_USE
            )
        await session.execute(
            delete(MonitoringSourceRecord).where(
                MonitoringSourceRecord.source_id == source_id,
                MonitoringSourceRecord.revision == expected_revision,
            )
        )
        await session.execute(
            delete(MonitoringProbeReceiptRecord).where(
                MonitoringProbeReceiptRecord.source_id == source_id
            )
        )
        return MonitoringSourceOperation(
            command.request_key,
            MonitoringSourceOperationStatus.COMPLETED,
            source_id=source_id,
            source_revision=expected_revision,
            enabled=False,
            verified=None,
        )

    async def _set_enabled_in_transaction(
        self,
        session: AsyncSession,
        command: MonitoringSourceMutation,
        instant: datetime,
    ) -> MonitoringSourceOperation:
        source_id = command.source_id
        expected_revision = command.expected_revision
        assert source_id is not None and expected_revision is not None
        current = await session.scalar(
            select(MonitoringSourceRecord)
            .where(MonitoringSourceRecord.source_id == source_id)
            .with_for_update()
        )
        if current is None:
            return _rejected_operation(command, MonitoringSourceOperationReason.NOT_FOUND)
        if not compare_digest(current.revision, expected_revision):
            return _rejected_operation(command, MonitoringSourceOperationReason.CONFLICT)
        next_revision = uuid4().hex
        await session.execute(
            update(MonitoringSourceRecord)
            .where(
                MonitoringSourceRecord.source_id == source_id,
                MonitoringSourceRecord.revision == expected_revision,
            )
            .values(enabled=command.enabled, revision=next_revision, updated_at=instant)
        )
        return MonitoringSourceOperation(
            command.request_key,
            MonitoringSourceOperationStatus.COMPLETED,
            source_id=source_id,
            source_revision=next_revision,
            enabled=command.enabled,
            verified=None,
        )

    async def _consume_check_in_transaction(
        self,
        session: AsyncSession,
        command: MonitoringSourceMutation,
        instant: datetime,
    ) -> bool:
        source = command.source
        assert source is not None and command.check_id is not None
        receipt = await session.scalar(
            select(MonitoringProbeReceiptRecord)
            .where(MonitoringProbeReceiptRecord.check_id == command.check_id)
            .with_for_update()
        )
        if (
            receipt is None
            or receipt.actor_account_id != command.actor_id
            or not compare_digest(receipt.session_hash, command.session_digest)
            or receipt.source_id != source.source_id
            or receipt.source_revision != source.revision
            or _stored_utc(receipt.expires_at) <= instant
            or command.candidate_fingerprint is None
            or not compare_digest(
                receipt.candidate_fingerprint, command.candidate_fingerprint
            )
            or receipt.connection != "reachable"
            or receipt.query_api != "available"
            or receipt.profile != "supported"
        ):
            return False
        await session.execute(
            delete(MonitoringProbeReceiptRecord).where(
                MonitoringProbeReceiptRecord.check_id == command.check_id
            )
        )
        return True

    @staticmethod
    def _persist_operation(
        session: AsyncSession,
        command: MonitoringSourceMutation,
        fingerprint: str,
        operation: MonitoringSourceOperation,
        instant: datetime,
    ) -> None:
        session.add(
            MonitoringSourceOperationRecord(
                request_key=command.request_key,
                operation_id=str(uuid4()),
                actor_account_id=command.actor_id,
                session_hash=command.session_digest,
                fingerprint_digest=fingerprint,
                status=operation.status.value,
                reason=operation.reason.value if operation.reason else None,
                source_id=operation.source_id,
                source_revision=operation.source_revision,
                enabled=operation.enabled,
                verified=operation.verified,
                created_at=instant,
            )
        )

    @staticmethod
    def _persist_audit(
        session: AsyncSession,
        command: MonitoringSourceMutation,
        operation: MonitoringSourceOperation,
        instant: datetime,
    ) -> None:
        action = {
            "create": "monitoring.source.create",
            "update": "monitoring.source.update",
            "delete": "monitoring.source.delete",
        }.get(command.kind)
        if action is None:
            action = (
                "monitoring.source.enable"
                if command.enabled
                else "monitoring.source.disable"
            )
        target_id = (
            operation.source_id
            if operation.source_id is not None and len(operation.source_id) <= 128
            else None
        )
        session.add(
            AuditEventRecord(
                event_id=str(uuid4()),
                request_id=command.request_id,
                actor_account_id=command.actor_id,
                action=action,
                outcome=(
                    "completed"
                    if operation.status is MonitoringSourceOperationStatus.COMPLETED
                    else "rejected"
                ),
                target_kind="monitoring-source",
                target_id=target_id,
                created_at=instant,
            )
        )

    async def _session_factory(self) -> async_sessionmaker[AsyncSession]:
        engine = await self._engine_resolver()
        return async_sessionmaker(engine, expire_on_commit=False)


def _encrypt_credentials(
    source: MonitoringSource,
    secret: MonitoringSourceSecret | None,
    cipher: AesGcmSecretCipher,
) -> EncryptedSecret | None:
    mode = source.authentication_mode
    if mode is MonitoringAuthenticationMode.NONE:
        if source.credential_configured or secret is not None:
            raise ValueError("unauthenticated source cannot store credentials")
        return None
    if not source.credential_configured or secret is None:
        raise ValueError("authenticated source requires write-only credentials")
    _validate_secret_mode(mode, secret)
    payload = json.dumps(
        {
            "username": secret.username,
            "password": secret.password,
            "bearerToken": secret.bearer_token,
            "credentialReference": secret.credential_reference,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return cipher.encrypt(
        payload,
        SecretContext(_CREDENTIAL_CONTEXT, source.source_id, _CREDENTIAL_FIELD),
    )


def _command_fingerprint(
    command: MonitoringSourceMutation, key: bytes
) -> str:
    source = command.source
    canonical = json.dumps(
        {
            "kind": command.kind,
            "requestKey": command.request_key,
            "sourceId": source.source_id if source else command.source_id,
            "revision": source.revision if source else command.expected_revision,
            "expectedRevision": command.expected_revision,
            "candidateFingerprint": command.candidate_fingerprint,
            "checkId": command.check_id,
            "skipCheck": command.skip_check,
            "enabled": command.enabled,
            "credentialUpdate": (
                command.credential_update.value
                if command.credential_update is not None
                else None
            ),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(
        key, b"sentinel-monitoring-source-command:v1\x00" + canonical, hashlib.sha256
    ).hexdigest()


def _completed_operation(
    source: MonitoringSource, request_key: str, verified: bool
) -> MonitoringSourceOperation:
    return MonitoringSourceOperation(
        request_key,
        MonitoringSourceOperationStatus.COMPLETED,
        source_id=source.source_id,
        source_revision=source.revision,
        enabled=source.enabled,
        verified=verified,
    )


def _rejected_operation(
    command: MonitoringSourceMutation, reason: MonitoringSourceOperationReason
) -> MonitoringSourceOperation:
    return MonitoringSourceOperation(
        command.request_key,
        MonitoringSourceOperationStatus.REJECTED,
        reason=reason,
    )


def _operation_from_row(
    row: MonitoringSourceOperationRecord,
) -> MonitoringSourceOperation:
    try:
        return MonitoringSourceOperation(
            request_key=row.request_key,
            status=MonitoringSourceOperationStatus(row.status),
            source_id=row.source_id,
            source_revision=row.source_revision,
            enabled=row.enabled,
            verified=row.verified,
            reason=(
                MonitoringSourceOperationReason(row.reason)
                if row.reason is not None
                else None
            ),
        )
    except (TypeError, ValueError):
        raise MonitoringSourceCommandUnavailable from None


def _replay_operation(
    row: MonitoringSourceOperationRecord,
    command: MonitoringSourceMutation,
    fingerprint: str,
) -> MonitoringSourceOperation:
    if row.actor_account_id != command.actor_id or not compare_digest(
        row.session_hash, command.session_digest
    ):
        raise MonitoringSourceCommandForbidden
    if not compare_digest(row.fingerprint_digest, fingerprint):
        raise MonitoringSourceIdempotencyConflict
    return _operation_from_row(row)


def _secret_for_update(
    source: MonitoringSource,
    current: MonitoringSourceRecord,
    update_mode: MonitoringCredentialUpdateMode,
    secret: MonitoringSourceSecret | None,
    cipher: AesGcmSecretCipher,
) -> EncryptedSecret | None:
    if source.authentication_mode is MonitoringAuthenticationMode.NONE:
        if (
            update_mode is not MonitoringCredentialUpdateMode.CLEAR
            or secret is not None
            or source.credential_configured
        ):
            raise ValueError("clearing credentials requires explicit unauthenticated mode")
        return None
    if update_mode is MonitoringCredentialUpdateMode.REPLACE:
        return _encrypt_credentials(source, secret, cipher)
    if update_mode is MonitoringCredentialUpdateMode.KEEP:
        if (
            secret is not None
            or not current.credential_configured
            or current.authentication_mode != source.authentication_mode.value
            or not source.credential_configured
        ):
            raise ValueError("credentials can be kept only for the same configured mode")
        return _encrypted_from_row(current)
    raise ValueError("authenticated source cannot clear credentials")


def _validate_secret_mode(
    mode: MonitoringAuthenticationMode, secret: MonitoringSourceSecret
) -> None:
    valid = (
        mode is MonitoringAuthenticationMode.DIRECT_BASIC
        and secret.username is not None
        and secret.password is not None
        and secret.bearer_token is None
        and secret.credential_reference is None
    ) or (
        mode is MonitoringAuthenticationMode.DIRECT_BEARER
        and secret.bearer_token is not None
        and secret.username is None
        and secret.password is None
        and secret.credential_reference is None
    ) or (
        mode is MonitoringAuthenticationMode.CREDENTIAL_REFERENCE
        and secret.credential_reference is not None
        and secret.username is None
        and secret.password is None
        and secret.bearer_token is None
    )
    if not valid:
        raise ValueError("stored secret does not match monitoring authentication mode")


def _secret_from_document(
    mode_value: str, value: object
) -> MonitoringSourceSecret:
    mode = MonitoringAuthenticationMode(mode_value)
    keys = {"username", "password", "bearerToken", "credentialReference"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("monitoring credential document is invalid")
    secret = MonitoringSourceSecret(
        username=value["username"],
        password=value["password"],
        bearer_token=value["bearerToken"],
        credential_reference=value["credentialReference"],
    )
    _validate_secret_mode(mode, secret)
    return secret


def _record(
    source: MonitoringSource,
    envelope: EncryptedSecret | None,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> MonitoringSourceRecord:
    return MonitoringSourceRecord(**_record_values(source, envelope, created_at=created_at, updated_at=updated_at))


def _record_values(
    source: MonitoringSource,
    envelope: EncryptedSecret | None,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "revision": source.revision,
        "display_name": source.display_name,
        "environment_id": source.environment_id,
        "endpoint": source.endpoint,
        "provider": source.provider.value,
        "profile": source.profile.value,
        "authentication_mode": source.authentication_mode.value,
        "credential_configured": source.credential_configured,
        "credential_cipher_format": envelope.format.value if envelope else None,
        "credential_key_id": envelope.key_id if envelope else None,
        "credential_payload": envelope.payload if envelope else None,
        "enabled": source.enabled,
        "identity_labels": list(source.identity_labels),
        "selector_labels": [
            {"name": item.name, "value": item.value}
            for item in source.selector_labels
        ],
        "scrape_interval_seconds": source.scrape_interval_seconds,
        "stale_after_seconds": source.stale_after_seconds,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _source_from_row(row: MonitoringSourceRecord) -> MonitoringSource:
    identity_labels = row.identity_labels
    selectors = row.selector_labels
    if (
        not isinstance(identity_labels, list)
        or any(not isinstance(item, str) for item in identity_labels)
        or not isinstance(selectors, list)
    ):
        raise ValueError("monitoring source label mapping is corrupt")
    return MonitoringSource(
        source_id=row.source_id,
        revision=row.revision,
        display_name=row.display_name,
        environment_id=row.environment_id,
        endpoint=row.endpoint,
        provider=MonitoringProvider(row.provider),
        profile=MonitoringProfile(row.profile),
        authentication_mode=MonitoringAuthenticationMode(row.authentication_mode),
        credential_configured=row.credential_configured,
        enabled=row.enabled,
        identity_labels=tuple(identity_labels),
        selector_labels=tuple(
            MonitoringLabel(item["name"], item["value"]) for item in selectors
        ),
        scrape_interval_seconds=row.scrape_interval_seconds,
        stale_after_seconds=row.stale_after_seconds,
    )


def _encrypted_from_row(row: MonitoringSourceRecord) -> EncryptedSecret | None:
    if row.credential_payload is None:
        return None
    if row.credential_cipher_format is None or row.credential_key_id is None:
        raise ValueError("monitoring credential envelope is incomplete")
    return EncryptedSecret(
        SecretCipherFormat(row.credential_cipher_format),
        row.credential_key_id,
        row.credential_payload,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("monitoring source timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _stored_utc(value: datetime) -> datetime:
    """Normalize SQL timestamps; SQLite drops timezone offsets for UTC values."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = ["SQLAlchemyMonitoringSourceStore"]
