"""SQLAlchemy authority for registered sources and original command receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from secrets import compare_digest
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from sqlalchemy import and_, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.check_registered_source import (
    RegisteredSourceCredentialResolver,
    RegisteredSourceCredentialsUnavailable,
    RegisteredSourceCheckResult,
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from ...application.mutate_registered_source import (
    RegisteredSourceMutation,
    RegisteredSourceMutationAuthority,
    RegisteredSourceOperation,
    SourceMutationAuthorityUnavailable,
    SourceMutationForbidden,
    SourceMutationIdempotencyConflict,
    SourceMutationKind,
    SourceMutationRejection,
    SourceMutationStatus,
    SourceMutationUnauthenticated,
)
from ...application.registered_source_ports import (
    RegisteredSourceProbe,
    RegisteredSourceProbeAuthorityUnavailable,
    RegisteredSourceProbeReader,
    RegisteredSourceProbeRecorder,
    RegisteredSourcesAuthorityUnavailable,
    RegisteredSourcesReader,
)
from ...domain.configuration_source import ConfigurationSourceProvider
from ...domain.registered_sources import (
    RegisteredConfigurationSource,
    RegisteredSourcesSnapshot,
    SourceAuthenticationMode,
)
from ...domain.session import AccountRole
from ..security.secret_cipher import (
    AesGcmSecretCipher,
    EncryptedSecret,
    SecretCipherFormat,
    SecretContext,
)
from .models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RegisteredSourceProbeRecord,
    RegisteredSourceOperationRecord,
)

_FINGERPRINT_DOMAIN = b"atlas-richie-sentinel-source-mutation:v1\x00"
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class SqlAlchemyRegisteredSourceStore(
    RegisteredSourceMutationAuthority,
    RegisteredSourcesReader,
    RegisteredSourceCredentialResolver,
    RegisteredSourceProbeRecorder,
    RegisteredSourceProbeReader,
):
    """Atomically mutate registry facts, protected credentials, receipts and audit."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        secret_cipher: AesGcmSecretCipher,
        fingerprint_keys: Mapping[str, bytes],
        active_fingerprint_key_id: str,
    ) -> None:
        if not fingerprint_keys or active_fingerprint_key_id not in fingerprint_keys:
            raise ValueError("an active source-command fingerprint key is required")
        copied_keys = dict(fingerprint_keys)
        if any(
            _KEY_ID_PATTERN.fullmatch(key_id) is None
            or not isinstance(key, bytes)
            or len(key) < 32
            for key_id, key in copied_keys.items()
        ):
            raise ValueError("source-command fingerprint key ring is invalid")
        self._engine = engine
        self._secret_cipher = secret_cipher
        self._fingerprint_keys = MappingProxyType(copied_keys)
        self._active_fingerprint_key_id = active_fingerprint_key_id

    async def mutate(
        self,
        command: RegisteredSourceMutation,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RegisteredSourceOperation:
        """Reauthorize and atomically commit one idempotent source mutation."""
        instant = _aware_utc(now)
        fingerprint_key_id, fingerprints = self._fingerprints(command)
        fingerprint_digest = fingerprints[fingerprint_key_id]
        operation_id = str(uuid4())
        audit_event_id = str(uuid4())
        try:
            async with self._engine.begin() as connection:
                await self._authorize_write(
                    connection,
                    actor_id=actor_id,
                    session_digest=session_digest,
                    csrf_digest=csrf_digest,
                    now=instant,
                )
                prior = await connection.execute(
                    select(RegisteredSourceOperationRecord.__table__)
                    .where(
                        RegisteredSourceOperationRecord.request_key
                        == command.request_key
                    )
                    .with_for_update()
                )
                prior_row = prior.mappings().one_or_none()
                if prior_row is not None:
                    return self._recover(
                        prior_row,
                        actor_id=actor_id,
                        session_digest=session_digest,
                        fingerprints=fingerprints,
                    )

                operation = await self._apply_mutation(
                    connection,
                    command=command,
                    actor_id=actor_id,
                    now=instant,
                )
                await connection.execute(
                    insert(RegisteredSourceOperationRecord).values(
                        **self._operation_values(
                            operation,
                            operation_id=operation_id,
                            actor_id=actor_id,
                            session_digest=session_digest,
                            fingerprint_key_id=fingerprint_key_id,
                            fingerprint_digest=fingerprint_digest,
                            now=instant,
                        )
                    )
                )
                await connection.execute(
                    insert(AuditEventRecord).values(
                        event_id=audit_event_id,
                        request_id=request_id,
                        actor_account_id=actor_id,
                        action=f"configuration.source.{command.kind.value}",
                        outcome=(
                            "completed"
                            if operation.status is SourceMutationStatus.COMPLETED
                            else "rejected"
                        ),
                        target_kind="configuration_source",
                        target_id=(
                            operation.record.id
                            if operation.record
                            else command.source.source_id
                        ),
                        created_at=instant,
                    )
                )
                return operation
        except (
            SourceMutationForbidden,
            SourceMutationIdempotencyConflict,
            SourceMutationUnauthenticated,
        ):
            raise
        except IntegrityError:
            return await self._recover_after_integrity_conflict(
                command,
                actor_id=actor_id,
                session_digest=session_digest,
                fingerprints=fingerprints,
            )
        except (SQLAlchemyError, ValueError):
            raise SourceMutationAuthorityUnavailable(
                "registered source mutation authority is unavailable"
            ) from None

    async def read_operation(
        self, request_key: str, *, actor_id: str, session_digest: str
    ) -> RegisteredSourceOperation | None:
        """Return an operation only to its original actor and browser session."""
        try:
            async with self._engine.connect() as connection:
                await self._authorize_read(
                    connection, actor_id=actor_id, session_digest=session_digest
                )
                result = await connection.execute(
                    select(RegisteredSourceOperationRecord.__table__).where(
                        RegisteredSourceOperationRecord.request_key == request_key,
                        RegisteredSourceOperationRecord.actor_account_id == actor_id,
                        RegisteredSourceOperationRecord.session_hash == session_digest,
                    )
                )
                row = result.mappings().one_or_none()
        except (SourceMutationForbidden, SourceMutationUnauthenticated):
            raise
        except SQLAlchemyError:
            raise SourceMutationAuthorityUnavailable(
                "registered source operation history is unavailable"
            ) from None
        return _operation_from_row(row) if row is not None else None

    async def read_registered_sources(self) -> RegisteredSourcesSnapshot:
        """Read safe registry facts without decrypting or probing credentials."""
        try:
            async with self._engine.connect() as connection:
                rows = (
                    await connection.execute(
                        select(RegisteredConfigurationSourceRecord.__table__)
                        .order_by(RegisteredConfigurationSourceRecord.source_id)
                        .limit(501)
                    )
                ).mappings().all()
            if len(rows) > 500:
                raise ValueError("registered source limit exceeded")
            sources = tuple(_source_from_registry_row(row) for row in rows)
            return RegisteredSourcesSnapshot(datetime.now(UTC), sources)
        except (SQLAlchemyError, KeyError, TypeError, ValueError):
            raise RegisteredSourcesAuthorityUnavailable(
                "registered source authority is unavailable"
            ) from None

    async def record_registered_source_probe(
        self,
        command: SourceConnectionInput,
        result: RegisteredSourceCheckResult,
    ) -> bool:
        """Save a probe only when its unchanged form still matches registry facts."""
        if (
            command.authentication_mode is not SourceCheckAuthenticationMode.KEEP
            or command.source_id is None
            or command.expected_revision is None
            or result.latency_ms is None
        ):
            return False
        values = _probe_values(result)
        try:
            async with self._engine.begin() as connection:
                current = (
                    await connection.execute(
                        select(RegisteredConfigurationSourceRecord.__table__)
                        .where(
                            RegisteredConfigurationSourceRecord.source_id
                            == command.source_id,
                            RegisteredConfigurationSourceRecord.revision
                            == command.expected_revision,
                            RegisteredConfigurationSourceRecord.provider
                            == command.provider.value,
                            RegisteredConfigurationSourceRecord.endpoint
                            == command.endpoint,
                            RegisteredConfigurationSourceRecord.location
                            == command.location,
                        )
                        .with_for_update()
                    )
                ).mappings().one_or_none()
                if current is None:
                    return False
                existing = (
                    await connection.execute(
                        select(RegisteredSourceProbeRecord.__table__)
                        .where(
                            RegisteredSourceProbeRecord.source_id
                            == command.source_id
                        )
                        .with_for_update()
                    )
                ).mappings().one_or_none()
                if existing is None:
                    await connection.execute(
                        insert(RegisteredSourceProbeRecord.__table__).values(
                            source_id=command.source_id,
                            revision=command.expected_revision,
                            **values,
                        )
                    )
                else:
                    await connection.execute(
                        update(RegisteredSourceProbeRecord)
                        .where(
                            RegisteredSourceProbeRecord.source_id
                            == command.source_id
                        )
                        .values(revision=command.expected_revision, **values)
                    )
            return True
        except SQLAlchemyError:
            raise RegisteredSourceProbeAuthorityUnavailable(
                "registered source probe authority is unavailable"
            ) from None

    async def read_registered_source_probes(
        self, sources: tuple[tuple[str, str], ...]
    ) -> tuple[RegisteredSourceProbe, ...]:
        """Read only probe rows whose source revision is still authoritative."""
        if not sources:
            return ()
        if len(sources) > 500 or len({source_id for source_id, _ in sources}) != len(
            sources
        ):
            raise RegisteredSourceProbeAuthorityUnavailable(
                "registered source probe request is invalid"
            ) from None
        revisions = dict(sources)
        try:
            async with self._engine.connect() as connection:
                rows = (
                    await connection.execute(
                        select(RegisteredSourceProbeRecord.__table__)
                        .select_from(RegisteredSourceProbeRecord)
                        .join(
                            RegisteredConfigurationSourceRecord,
                            and_(
                                RegisteredConfigurationSourceRecord.source_id
                                == RegisteredSourceProbeRecord.source_id,
                                RegisteredConfigurationSourceRecord.revision
                                == RegisteredSourceProbeRecord.revision,
                            ),
                        )
                        .where(
                            RegisteredConfigurationSourceRecord.source_id.in_(
                                tuple(revisions)
                            )
                        )
                        .order_by(RegisteredSourceProbeRecord.source_id)
                        .limit(501)
                    )
                ).mappings().all()
            if len(rows) > 500:
                raise ValueError("registered source probe limit exceeded")
            return tuple(
                _registered_source_probe_from_row(row)
                for row in rows
                if revisions.get(row["source_id"]) == row["revision"]
            )
        except (SQLAlchemyError, KeyError, TypeError, ValueError):
            raise RegisteredSourceProbeAuthorityUnavailable(
                "registered source probe authority is unavailable"
            ) from None

    async def resolve_credentials(
        self,
        source_id: str,
        expected_revision: str,
        provider: ConfigurationSourceProvider,
    ) -> SourceConnectionInput | None:
        """Decrypt only the credential envelope for the exact requested revision."""
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RegisteredConfigurationSourceRecord.__table__).where(
                        RegisteredConfigurationSourceRecord.source_id == source_id,
                        RegisteredConfigurationSourceRecord.revision
                        == expected_revision,
                        RegisteredConfigurationSourceRecord.provider == provider.value,
                    )
                )
                row = result.mappings().one_or_none()
            if row is None:
                return None
            return self._connection_from_row(row)
        except (SQLAlchemyError, KeyError, TypeError, ValueError):
            raise RegisteredSourceCredentialsUnavailable(
                "registered source credentials are unavailable"
            ) from None

    def _connection_from_row(self, row) -> SourceConnectionInput:
        provider = ConfigurationSourceProvider(row["provider"])
        stored_mode = SourceAuthenticationMode(row["authentication_mode"])
        common = {
            "source_id": row["source_id"],
            "expected_revision": row["revision"],
            "provider": provider,
            "endpoint": row["endpoint"],
            "location": row["location"],
        }
        if stored_mode is SourceAuthenticationMode.NONE:
            if row["credential_payload"] is not None:
                raise ValueError("no-auth source unexpectedly has a credential")
            return SourceConnectionInput(
                **common,
                authentication_mode=SourceCheckAuthenticationMode.NONE,
            )

        envelope = _encrypted_from_row(row)
        if envelope is None:
            raise ValueError("registered source credential envelope is missing")
        serialized = self._secret_cipher.decrypt(
            envelope,
            SecretContext(
                "configuration-source", row["source_id"], "authentication"
            ),
        )
        payload = json.loads(serialized, object_pairs_hook=_unique_object_keys)
        if not isinstance(payload, dict):
            raise ValueError("registered source credential payload is invalid")
        if stored_mode is SourceAuthenticationMode.CREDENTIAL_REFERENCE:
            if set(payload) != {"mode", "reference"} or payload["mode"] != "credential-reference":
                raise ValueError("stored credential reference shape is invalid")
            return SourceConnectionInput(
                **common,
                authentication_mode=SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
                credential_reference=_required_text(payload, "reference"),
            )

        if payload.get("mode") != "direct":
            raise ValueError("stored direct credential mode is invalid")
        if provider is ConfigurationSourceProvider.NACOS:
            if set(payload) != {"mode", "username", "password"}:
                raise ValueError("stored Nacos credential shape is invalid")
            return SourceConnectionInput(
                **common,
                authentication_mode=SourceCheckAuthenticationMode.DIRECT,
                username=_required_text(payload, "username"),
                password=_required_text(payload, "password"),
            )
        if set(payload) != {"mode", "aclToken"}:
            raise ValueError("stored Consul credential shape is invalid")
        return SourceConnectionInput(
            **common,
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            acl_token=_required_text(payload, "aclToken"),
        )

    async def _apply_mutation(
        self,
        connection,
        *,
        command: RegisteredSourceMutation,
        actor_id: str,
        now: datetime,
    ) -> RegisteredSourceOperation:
        if command.kind is SourceMutationKind.REGISTER:
            source_id = str(uuid4())
            revision = str(uuid4())
            values = self._source_values(
                command.source,
                source_id=source_id,
                revision=revision,
                name=command.name,
                actor_id=actor_id,
                now=now,
            )
            await connection.execute(
                insert(RegisteredConfigurationSourceRecord).values(**values)
            )
            return RegisteredSourceOperation(
                command.request_key,
                SourceMutationStatus.COMPLETED,
                record=_source_from_values(values),
            )

        assert command.source.source_id is not None
        assert command.source.expected_revision is not None
        result = await connection.execute(
            select(RegisteredConfigurationSourceRecord.__table__)
            .where(
                RegisteredConfigurationSourceRecord.source_id
                == command.source.source_id
            )
            .with_for_update()
        )
        current = result.mappings().one_or_none()
        if current is None:
            return _rejected(command.request_key, SourceMutationRejection.NOT_FOUND)
        if current["revision"] != command.source.expected_revision:
            return _rejected(command.request_key, SourceMutationRejection.CONFLICT)
        if (
            command.source.authentication_mode is SourceCheckAuthenticationMode.KEEP
            and current["provider"] != command.source.provider.value
        ):
            return _rejected(command.request_key, SourceMutationRejection.VALIDATION)

        new_values = self._source_values(
            command.source,
            source_id=command.source.source_id,
            revision=str(uuid4()),
            name=command.name,
            actor_id=actor_id,
            now=now,
            existing=current,
        )
        updated = await connection.execute(
            update(RegisteredConfigurationSourceRecord)
            .where(
                RegisteredConfigurationSourceRecord.source_id
                == command.source.source_id,
                RegisteredConfigurationSourceRecord.revision
                == command.source.expected_revision,
            )
            .values(**new_values)
        )
        if updated.rowcount != 1:
            return _rejected(command.request_key, SourceMutationRejection.CONFLICT)
        return RegisteredSourceOperation(
            command.request_key,
            SourceMutationStatus.COMPLETED,
            record=_source_from_values(new_values),
        )

    def _source_values(
        self,
        source: SourceConnectionInput,
        *,
        source_id: str,
        revision: str,
        name: str,
        actor_id: str,
        now: datetime,
        existing=None,
    ) -> dict[str, object]:
        mode = source.authentication_mode
        if mode is SourceCheckAuthenticationMode.KEEP:
            if existing is None:
                raise ValueError("credential preservation requires an existing source")
            encrypted = _encrypted_from_row(existing)
            auth_mode = existing["authentication_mode"]
            credential_configured = existing["credential_configured"]
        elif mode is SourceCheckAuthenticationMode.NONE:
            encrypted = None
            auth_mode = SourceAuthenticationMode.NONE.value
            credential_configured = False
        else:
            encrypted = encrypt_registered_source_credentials(
                source, source_id, self._secret_cipher
            )
            auth_mode = (
                SourceAuthenticationMode.CREDENTIAL_REFERENCE.value
                if mode is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE
                else SourceAuthenticationMode.DIRECT.value
            )
            credential_configured = True

        return {
            "source_id": source_id,
            "revision": revision,
            "name": name,
            "endpoint": source.endpoint,
            "provider": source.provider.value,
            "location": source.location,
            "authentication_mode": auth_mode,
            "credential_configured": credential_configured,
            "credential_cipher_format": encrypted.format.value if encrypted else None,
            "credential_key_id": encrypted.key_id if encrypted else None,
            "credential_payload": encrypted.payload if encrypted else None,
            "created_at": existing["created_at"] if existing is not None else now,
            "updated_at": now,
            "updated_by_account_id": actor_id,
        }

    async def _authorize_write(
        self,
        connection,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        now: datetime,
    ) -> None:
        row = await connection.execute(
            select(AccountRecord.role_id, AuthenticationSessionRecord.csrf_hash)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > now,
            )
            .with_for_update()
        )
        active = row.one_or_none()
        if active is None or not compare_digest(active.csrf_hash, csrf_digest):
            raise SourceMutationUnauthenticated("browser session is inactive")
        if active.role_id != AccountRole.ADMIN.value:
            raise SourceMutationForbidden("administrator role is required")

    async def _authorize_read(
        self, connection, *, actor_id: str, session_digest: str
    ) -> None:
        result = await connection.execute(
            select(AccountRecord.role_id)
            .join(
                AuthenticationSessionRecord,
                AuthenticationSessionRecord.account_id == AccountRecord.account_id,
            )
            .where(
                AccountRecord.account_id == actor_id,
                AccountRecord.status == "active",
                AuthenticationSessionRecord.session_hash == session_digest,
                AuthenticationSessionRecord.revoked_at.is_(None),
                AuthenticationSessionRecord.expires_at > datetime.now(UTC),
            )
        )
        role_id = result.scalar_one_or_none()
        if role_id is None:
            raise SourceMutationUnauthenticated("browser session is inactive")
        if role_id != AccountRole.ADMIN.value:
            raise SourceMutationForbidden("administrator role is required")

    def _fingerprints(
        self, command: RegisteredSourceMutation
    ) -> tuple[str, Mapping[str, str]]:
        source = command.source
        payload: dict[str, object] = {
            "kind": command.kind.value,
            "requestKey": command.request_key,
            "name": command.name,
            "sourceId": source.source_id,
            "expectedRevision": source.expected_revision,
            "provider": source.provider.value,
            "endpoint": source.endpoint,
            "location": source.location,
            "authenticationMode": source.authentication_mode.value,
            "credentialReference": source.credential_reference,
            "username": source.username,
            "password": source.password,
            "aclToken": source.acl_token,
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        active_key_id = self._active_fingerprint_key_id
        fingerprints = {
            key_id: hmac.new(
                key,
                _FINGERPRINT_DOMAIN + canonical,
                hashlib.sha256,
            ).hexdigest()
            for key_id, key in self._fingerprint_keys.items()
        }
        return active_key_id, MappingProxyType(fingerprints)

    @staticmethod
    def _operation_values(
        operation: RegisteredSourceOperation,
        *,
        operation_id: str,
        actor_id: str,
        session_digest: str,
        fingerprint_key_id: str,
        fingerprint_digest: str,
        now: datetime,
    ) -> dict[str, object]:
        record = operation.record
        return {
            "request_key": operation.request_key,
            "operation_id": operation_id,
            "actor_account_id": actor_id,
            "session_hash": session_digest,
            "fingerprint_key_id": fingerprint_key_id,
            "fingerprint_digest": fingerprint_digest,
            "status": operation.status.value,
            "reason": operation.reason.value if operation.reason else None,
            "source_id": record.id if record else None,
            "source_revision": record.revision if record else None,
            "source_name": record.name if record else None,
            "source_endpoint": record.endpoint if record else None,
            "source_provider": record.provider.value if record else None,
            "source_location": record.location if record else None,
            "source_authentication_mode": (
                record.authentication_mode.value if record else None
            ),
            "source_credential_configured": (
                record.credential_configured if record else None
            ),
            "created_at": now,
        }

    async def _recover_after_integrity_conflict(
        self,
        command: RegisteredSourceMutation,
        *,
        actor_id: str,
        session_digest: str,
        fingerprints: Mapping[str, str],
    ) -> RegisteredSourceOperation:
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    select(RegisteredSourceOperationRecord.__table__).where(
                        RegisteredSourceOperationRecord.request_key
                        == command.request_key
                    )
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError:
            raise SourceMutationAuthorityUnavailable(
                "registered source mutation authority is unavailable"
            ) from None
        if row is None:
            raise SourceMutationAuthorityUnavailable(
                "registered source mutation authority is unavailable"
            ) from None
        return self._recover(
            row,
            actor_id=actor_id,
            session_digest=session_digest,
            fingerprints=fingerprints,
        )

    @staticmethod
    def _recover(
        row,
        *,
        actor_id: str,
        session_digest: str,
        fingerprints: Mapping[str, str],
    ) -> RegisteredSourceOperation:
        if (
            row["actor_account_id"] != actor_id
            or row["session_hash"] != session_digest
        ):
            raise SourceMutationForbidden("operation belongs to another actor")
        fingerprint = fingerprints.get(row["fingerprint_key_id"])
        if fingerprint is None or not hmac.compare_digest(
            row["fingerprint_digest"], fingerprint
        ):
            raise SourceMutationIdempotencyConflict("request key was reused")
        return _operation_from_row(row)


def _source_from_registry_row(row) -> RegisteredConfigurationSource:
    return RegisteredConfigurationSource(
        id=row["source_id"],
        revision=row["revision"],
        name=row["name"],
        endpoint=row["endpoint"],
        provider=ConfigurationSourceProvider(row["provider"]),
        location=row["location"],
        authentication_mode=SourceAuthenticationMode(row["authentication_mode"]),
        credential_configured=row["credential_configured"],
    )


def encrypt_registered_source_credentials(
    source: SourceConnectionInput,
    source_id: str,
    secret_cipher: AesGcmSecretCipher,
) -> EncryptedSecret | None:
    """Encode source authentication using the registry's one storage contract."""
    mode = source.authentication_mode
    if mode is SourceCheckAuthenticationMode.NONE:
        return None
    if mode is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE:
        payload: dict[str, str] = {
            "mode": "credential-reference",
            "reference": source.credential_reference or "",
        }
    elif source.provider is ConfigurationSourceProvider.NACOS:
        payload = {
            "mode": "direct",
            "username": source.username or "",
            "password": source.password or "",
        }
    else:
        payload = {"mode": "direct", "aclToken": source.acl_token or ""}
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return secret_cipher.encrypt(
        serialized,
        SecretContext("configuration-source", source_id, "authentication"),
    )


def _source_from_values(values: Mapping[str, object]) -> RegisteredConfigurationSource:
    return RegisteredConfigurationSource(
        id=str(values["source_id"]),
        revision=str(values["revision"]),
        name=str(values["name"]),
        endpoint=str(values["endpoint"]),
        provider=ConfigurationSourceProvider(str(values["provider"])),
        location=str(values["location"]),
        authentication_mode=SourceAuthenticationMode(
            str(values["authentication_mode"])
        ),
        credential_configured=bool(values["credential_configured"]),
    )


def _operation_from_row(row) -> RegisteredSourceOperation:
    status = SourceMutationStatus(row["status"])
    reason = (
        SourceMutationRejection(row["reason"]) if row["reason"] is not None else None
    )
    record = None
    if status is SourceMutationStatus.COMPLETED:
        record = RegisteredConfigurationSource(
            id=row["source_id"],
            revision=row["source_revision"],
            name=row["source_name"],
            endpoint=row["source_endpoint"],
            provider=ConfigurationSourceProvider(row["source_provider"]),
            location=row["source_location"],
            authentication_mode=SourceAuthenticationMode(
                row["source_authentication_mode"]
            ),
            credential_configured=row["source_credential_configured"],
        )
    return RegisteredSourceOperation(row["request_key"], status, record, reason)


def _rejected(
    request_key: str, reason: SourceMutationRejection
) -> RegisteredSourceOperation:
    return RegisteredSourceOperation(
        request_key, SourceMutationStatus.REJECTED, reason=reason
    )


def _encrypted_from_row(row) -> EncryptedSecret | None:
    if row["credential_payload"] is None:
        return None
    return EncryptedSecret(
        SecretCipherFormat(row["credential_cipher_format"]),
        row["credential_key_id"],
        row["credential_payload"],
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source mutation time must be timezone-aware")
    return value.astimezone(UTC)


def _probe_values(result: RegisteredSourceCheckResult) -> dict[str, object]:
    if result.latency_ms is None:
        raise ValueError("registered source probe requires measured latency")
    return {
        "checked_at": _aware_utc(result.checked_at),
        "expires_at": _aware_utc(result.expires_at),
        "latency_ms": float(result.latency_ms),
        "capabilities": [capability.value for capability in result.capabilities],
        "reason": result.reason.value if result.reason is not None else None,
    }


def _registered_source_probe_from_row(row) -> RegisteredSourceProbe:
    capabilities = row["capabilities"]
    if not isinstance(capabilities, list) or any(
        not isinstance(item, str) for item in capabilities
    ):
        raise ValueError("registered source probe capabilities are invalid")
    result = RegisteredSourceCheckResult(
        checked_at=_database_utc(row["checked_at"]),
        expires_at=_database_utc(row["expires_at"]),
        capabilities=tuple(SourceCheckCapability(item) for item in capabilities),
        reason=(
            SourceCheckFailureReason(row["reason"])
            if row["reason"] is not None
            else None
        ),
        latency_ms=float(row["latency_ms"]),
    )
    return RegisteredSourceProbe(row["source_id"], row["revision"], result)


def _database_utc(value: datetime) -> datetime:
    """Normalize SQL drivers that discard timezone metadata for UTC columns."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else _aware_utc(value)


def _unique_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys in the authenticated credential payload."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("stored credential payload contains duplicate fields")
        result[key] = value
    return result


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("stored credential payload has an invalid field")
    return value
